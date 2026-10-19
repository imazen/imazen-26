#!/usr/bin/env python3
"""Promote a checked PNG-twin redo, retaining every replaced file and report."""
import argparse
import csv
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys

import check_jxl_subset as check


def write_table(path, rows, columns):
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("render", type=Path)
    parser.add_argument("--ids", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    candidate, render = args.candidate.absolute(), args.render.absolute()
    ids = set(args.ids.split(","))
    check.verify(candidate)
    fresh = check.table(candidate / "jxl-report.tsv")
    expected = {(cid, layer) for cid in ids for layer in ["jxl-p3", "jxl-srgb"]}
    if {(r["id"], r["layer"]) for r in fresh} != expected:
        raise ValueError("candidate coverage differs from authorized ids/layers")
    old = check.table(render / "jxl-report.tsv")
    old_by_key = {(r["id"], r["layer"]): r for r in old}
    if len(old_by_key) != len(old):
        raise ValueError("duplicate current render rows")
    for row in fresh:
        prior = old_by_key[row["id"], row["layer"]]
        if prior["kind"] != "jpeg-in-jxl-codestream" or prior["path"] != row["path"]:
            raise ValueError("current file is not the expected coefficient-only fallback")
        if check.digest(render / prior["path"]) != prior["sha256"]:
            raise ValueError("current file changed since its render report")
    replacements = {(r["id"], r["layer"]): r for r in fresh}
    merged = [replacements.get((r["id"], r["layer"]), r) for r in old]
    # The five XL ids are routed to their separate repository.
    xl = {"11455", "11458", "11521", "11540", "12402"}
    totals = {layer: sum(int(r["bytes"]) for r in merged + check.table(render / "jxl-hdr-report.tsv")
                         if r["layer"].removesuffix("-hdr") == layer and r["id"] not in xl)
              for layer in ["jxl-p3", "jxl-srgb"]}
    if any(total >= 10_000_000_000 for total in totals.values()):
        raise ValueError("replacement exceeds a 10 GB layer repository limit")
    number = 1
    while (render / f"jxl-redo-{number}-report.tsv").exists():
        number += 1
    backup = render / f"before-jxl-redo-{number}"
    stage = render / f"jxl-redo-{number}-staged"
    if backup.exists() or stage.exists():
        raise ValueError("redo already staged or partially applied; inspect its journal")
    plan = {"redo": number, "ids": sorted(ids), "files": len(fresh),
            "largest_file_bytes": max(int(r["bytes"]) for r in fresh),
            "repository_bytes_excluding_xl": totals,
            "candidate_report_sha256": check.digest(candidate / "jxl-report.tsv"),
            "prior_report_sha256": check.digest(render / "jxl-report.tsv")}
    print(json.dumps(plan), flush=True)
    if not args.apply:
        return
    # Copy and verify all new files before moving a single existing file.
    stage.mkdir()
    for row in fresh:
        target = stage / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate / row["path"], target)
        if check.digest(target) != row["sha256"]:
            raise ValueError("staged file hash differs from its candidate")
    if check.digest(render / "jxl-report.tsv") != plan["prior_report_sha256"]:
        raise ValueError("current render report changed while staging the redo")
    backup.mkdir()
    for name in ["jxl-report.tsv", "jxl-hdr-report.tsv", "RUN.meta"]:
        shutil.copyfile(render / name, backup / name)
    shutil.copytree(render / "manifests", backup / "manifests")
    evidence = render / f"jxl-redo-{number}-evidence"
    shutil.copytree(candidate / "subset-check", evidence)
    for name in ["build.json", "Cargo.lock", "COMMITS.tsv", "report-recovery.json", "jxl-check.tsv"]:
        shutil.copyfile(candidate / name, evidence / name)
    journal = backup / "promotion.jsonl"
    journal.write_text(json.dumps({"plan": plan}) + "\n")
    for row in fresh:
        source, saved = render / row["path"], backup / row["path"]
        saved.parent.mkdir(parents=True, exist_ok=True)
        if check.digest(source) != old_by_key[row["id"], row["layer"]]["sha256"]:
            raise ValueError("current file changed while staging the redo")
        source.rename(saved)
        (stage / row["path"]).rename(source)
        with journal.open("a") as stream:
            stream.write(json.dumps({"replaced": row["path"], "sha256": row["sha256"]}) + "\n")
    columns = list(old[0])
    write_table(render / f"jxl-redo-{number}-report.tsv", fresh, columns)
    # Keep the prior reports in the conventional redo locations too.
    shutil.copyfile(backup / "jxl-report.tsv", render / f"jxl-report.before-jxl-redo-{number}.tsv")
    pending = render / f"jxl-report.prepared-redo-{number}.tsv"
    write_table(pending, merged, columns)
    pending.replace(render / "jxl-report.tsv")
    build = json.loads((candidate / "build.json").read_text())
    prefix = f"jxl_redo_{number}_"
    details = {"date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "kind": "lossless PNG-twin replacement for twelve coefficient-only progressive JPEGs",
               "ids": ",".join(sorted(ids)), "tool_commit": build["tool_commit"],
               "render_v4_cargo_lock_sha256": check.digest(candidate / "Cargo.lock"),
               "binary_sha256": build["binary_sha256"], "effort": build["effort"],
               "encoder_revision": build["encoder_revision"], "zenjxl_revision": build["zenjxl_revision"],
               "checked_files": len(fresh), "exit": 0}
    with (render / "RUN.meta").open("a") as stream:
        for key, value in details.items():
            stream.write(f"{prefix}{key}\t{value}\n")
    subprocess.run([sys.executable, str(Path(__file__).with_name("export_manifests.py")), str(render)], check=True)
    for layer in ["jxl-p3", "jxl-srgb"]:
        manifest = {(r["id"], r["path"]): r for r in check.table(render / "manifests" / (layer + ".tsv"))}
        for row in fresh:
            if row["layer"] != layer:
                continue
            recorded = manifest[row["id"], row["path"]]
            if recorded["sha256"] != row["sha256"] or recorded["form"] != "lossless":
                raise ValueError("promoted manifest does not record the replacement")
            if recorded["tool_commit"] != build["tool_commit"]:
                raise ValueError("promoted manifest lost encoder provenance")
    (evidence / "promotion-summary.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps({"promoted": len(fresh), "redo": number, "old_files_retained": str(backup)}), flush=True)


if __name__ == "__main__":
    main()
