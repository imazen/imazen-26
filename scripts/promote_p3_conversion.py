#!/usr/bin/env python3
"""Promote the two approved Adobe RGB→P3 conversions, preserving prior files and reports."""
import argparse
import csv
import io
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import check_jxl_subset as check

IDS = {"13005", "13006"}


def write(path, rows, comments=""):
    with path.open("x", newline="") as stream:
        stream.write(comments)
        writer = csv.DictWriter(stream, list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("render", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    candidate, render = args.candidate, args.render
    check.verify(candidate)
    conversions = json.loads((candidate / "colour-conversion-check.json").read_text())
    if {r["id"] for r in conversions} != IDS or any(
            r[k] > 1 for r in conversions for k in ["textbook_max_error", "littlecms_max_error"]):
        raise ValueError("independent colour conversion checks missing or failed")
    backup = render / "before-p3-conversion-2026-10-20"
    if backup.exists():
        raise ValueError("conversion already promoted or partially applied; inspect journal")
    report_names = ["report.tsv", "jxl-report.tsv", "imi-report.tsv", "imi-check.tsv"]
    fresh, previous, merged = {}, {}, {}
    files = []
    for name in report_names:
        old = check.table(render / name)
        new = [r for r in check.table(candidate / name) if r["layer"].endswith("-p3")]
        if {r["id"] for r in new} != IDS or len(new) != 2 or any(r["error"] for r in new):
            raise ValueError(f"unexpected coverage/errors in {name}")
        keyed = {(r["id"], r["layer"], r["path"]): r for r in old}
        replacements = {(r["id"], r["layer"], r["path"]): r for r in new}
        if len(keyed) != len(old) or not replacements.keys() <= keyed.keys():
            raise ValueError("duplicate/missing prior rows")
        for row in new:
            prior = keyed[row["id"], row["layer"], row["path"]]
            if row["path"] != prior["path"]:
                raise ValueError("conversion changed the filename")
            if name != "imi-check.tsv":
                expected_prior_colour = "icc" if name == "imi-report.tsv" else "adobe-rgb"
                if prior["colour"] != expected_prior_colour or row["colour"] != "display-p3":
                    raise ValueError("unexpected prior/converted colour")
                if check.digest(render / prior["path"]) != prior["sha256"]:
                    raise ValueError("prior file changed since report")
                if check.digest(candidate / row["path"]) != row["sha256"]:
                    raise ValueError("candidate file differs from report")
                files.append(row)
            elif any(row[k] != "ok" for k in ["imij", "oracle", "metadata"]):
                raise ValueError("IMI checks failed")
        fresh[name], previous[name] = new, old
        merged[name] = [replacements.get((r["id"], r["layer"], r["path"]), r) for r in old]
    # Only P3 files change. Both generated sRGB twins must retain their prior sample hashes.
    for name, field in [("report.tsv", "rgba_sha256"), ("jxl-report.tsv", "pixels_sha256")]:
        old = {(r["id"], r["layer"]): r for r in previous[name]}
        for row in check.table(candidate / name):
            if row["layer"].endswith("-srgb") and row[field] != old[row["id"], row["layer"]][field]:
                raise ValueError("sRGB samples changed")
    print(json.dumps({"files": len(files), "ids": sorted(IDS), "backup": str(backup)}), flush=True)
    if not args.apply:
        return
    build = json.loads((candidate / "build.json").read_text())
    backup.mkdir()
    for name in [*report_names, "RUN.meta", "decoded-xxh3.tsv"]:
        shutil.copyfile(render / name, backup / name)
    shutil.copytree(render / "manifests", backup / "manifests")
    journal = backup / "promotion.jsonl"
    for row in files:
        source, destination = render / row["path"], backup / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = source.with_name(source.name + ".p3-prepared")
        if pending.exists():
            raise ValueError("pending conversion already exists")
        shutil.copyfile(candidate / row["path"], pending)
        if check.digest(pending) != row["sha256"]:
            raise ValueError("copied conversion hash differs")
        source.rename(destination)
        pending.rename(source)
        with journal.open("a") as stream:
            stream.write(json.dumps({"path": row["path"], "sha256": row["sha256"]}) + "\n")
    for name in report_names:
        pending = render / (name + ".p3-prepared")
        write(pending, merged[name])
        pending.replace(render / name)
    for name, redo in [("report.tsv", "redo-3-report.tsv"),
                       ("jxl-report.tsv", "jxl-redo-6-report.tsv"),
                       ("imi-report.tsv", "imi-redo-2-report.tsv")]:
        write(render / redo, fresh[name])
    details = {"date": datetime.now(timezone.utc).isoformat(), "ids": ",".join(sorted(IDS)),
               "kind": "Adobe RGB to Display P3; relative colorimetric, gamut clipping",
               "tool_commit": build["tool_commit"],
               "render_v4_cargo_lock_sha256": build["cargo_lock_sha256"],
               "binary_sha256": build["binary_sha256"]}
    with (render / "RUN.meta").open("a") as stream:
        for prefix in ["redo_3_", "jxl_redo_6_", "p3_conversion_"]:
            for key, value in details.items():
                stream.write(f"{prefix}{key}\t{value}\n")
    subprocess.run([sys.executable, str(Path(__file__).with_name("export_manifests.py")), str(render)], check=True)
    # Replace precisely eight bitmap rows: two PNGs plus each JXL in three readers.
    fresh_hashes = {}
    for name in ["png.tsv", "native.tsv", "libjxl.tsv"]:
        for row in check.table(candidate / "subset-check" / name):
            relative = str(Path(row["path"]).relative_to(candidate))
            if relative.startswith(("png-p3/", "jxl-p3/")):
                fresh_hashes[relative, row["decoder"]] = row
    if len(fresh_hashes) != 8:
        raise ValueError("expected eight fresh bitmap rows")
    text = (backup / "decoded-xxh3.tsv").read_text()
    comments = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    old_hashes = list(csv.DictReader(io.StringIO("".join(line for line in text.splitlines(keepends=True)
                                                       if not line.startswith("#"))), delimiter="\t"))
    replaced = 0
    for row in old_hashes:
        new = fresh_hashes.get((row["path"], row["decoder"]))
        if new:
            for key in row:
                if key not in ["path", "layer"]:
                    row[key] = new[key]
            replaced += 1
    if replaced != 8:
        raise ValueError("bitmap table does not contain precisely the expected eight rows")
    pending = render / "decoded-xxh3.p3-prepared.tsv"
    write(pending, old_hashes, comments)
    pending.replace(render / "decoded-xxh3.tsv")
    for name in ["png-srgb", "jxl-srgb"]:
        if (render / "manifests" / (name + ".tsv")).read_bytes() != (backup / "manifests" / (name + ".tsv")).read_bytes():
            raise ValueError("unrelated sRGB manifest changed")
    print(json.dumps({"promoted_files": len(files), "bitmap_rows": replaced, "old_files_retained": True}))


if __name__ == "__main__":
    main()
