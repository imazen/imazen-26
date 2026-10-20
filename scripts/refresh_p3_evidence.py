#!/usr/bin/env python3
"""Refresh retained PNG/JXL readback tables and the two affected private IMI sets."""
import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

from check_jxl_subset import digest, table
from promote_p3_conversion import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("render", type=Path)
    parser.add_argument("imi_tool", type=Path)
    parser.add_argument("--baseline-decodes", type=Path, help="verified full decode tables from the latest corpus recheck")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    candidate, render = args.candidate, args.render
    if not (args.resume and (candidate / "readback.tsv").exists()):
        subprocess.run([sys.executable, str(Path(__file__).with_name("render_v4_readback.py")),
                        str(candidate), "--jobs", "2"], check=True)
    backup = render / "before-p3-conversion-2026-10-20"
    for name in ["readback.tsv", "jxl-check.tsv"]:
        old = table(render / name)
        new = {(r["id"], r["layer"], r["path"]): r for r in table(candidate / name)
               if r["layer"].endswith("-p3")}
        if len(new) != 2:
            raise ValueError("expected two new P3 reader checks")
        if name == "jxl-check.tsv" and any(r["result"] != "ok" for r in new.values()):
            raise ValueError("JXL structural checks failed")
        if name == "readback.tsv" and any(r["error"] for r in new.values()):
            raise ValueError("PNG readback failed")
        if not (backup / name).exists():
            shutil.copyfile(render / name, backup / name)
        merged = [new.get((r["id"], r["layer"], r["path"]), r) for r in old]
        if sum((r["id"], r["layer"], r["path"]) in new for r in old) != 2:
            raise ValueError("missing/duplicate prior reader checks")
        pending = render / (name + ".p3-prepared")
        write(pending, merged)
        pending.replace(render / name)
    # Refresh the raw inputs used by the full decoder report, preserving all unrelated rows.
    dc = render / "decode-check"
    saved_dc = backup / "decode-check"
    saved_dc.mkdir(exist_ok=args.resume)
    for name in ["png.tsv", "jxl.tsv", "jxl-libjxl.tsv", "report.tsv", "gain-maps.tsv", "summary.txt"]:
        if not (saved_dc / name).exists():
            shutil.copyfile(dc / name, saved_dc / name)
    for name, fresh_name in [("png.tsv", "png.tsv"), ("jxl.tsv", "native.tsv"),
                             ("jxl-libjxl.tsv", "libjxl.tsv")]:
        old = table((args.baseline_decodes or dc) / name)
        if args.baseline_decodes:
            for row in old:
                row["path"] = str(render / Path(row["path"]).relative_to(args.baseline_decodes.parent))
        replacements = {}
        for row in table(candidate / "subset-check" / fresh_name):
            relative = Path(row["path"]).relative_to(candidate)
            if str(relative).startswith(("png-p3/", "jxl-p3/")):
                row["path"] = str(render / relative)
                replacements[row["path"], row["decoder"]] = row
        merged = [replacements.get((r["path"], r["decoder"]), r) for r in old]
        if sum((r["path"], r["decoder"]) in replacements for r in old) != len(replacements):
            raise ValueError("incomplete full decoder table replacement")
        pending = dc / (name + ".p3-prepared")
        write(pending, merged)
        pending.replace(dc / name)
    summary = candidate / "full-decode-summary.txt"
    if summary.exists():
        summary = candidate / "full-decode-summary-refreshed.txt"
    with summary.open("x") as stream:
        subprocess.run([sys.executable, str(Path(__file__).with_name("render_v4_decode_report.py")),
                        str(render)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    shutil.copyfile(summary, dc / "summary.txt")
    def bitmaps(path):
        with path.open() as stream:
            return {(r["path"], r["decoder"]): r for r in csv.DictReader(
                (line for line in stream if not line.startswith("#")), delimiter="\t")}
    prior = bitmaps(backup / "decoded-xxh3.tsv")
    current = bitmaps(render / "decoded-xxh3.tsv")
    changed = {key for key in prior if prior[key] != current.get(key)}
    expected_changes = {(str(Path(r["path"]).relative_to(candidate)), r["decoder"])
                        for name in ["png.tsv", "native.tsv", "libjxl.tsv"]
                        for r in table(candidate / "subset-check" / name)
                        if str(Path(r["path"]).relative_to(candidate)).startswith(("png-p3/", "jxl-p3/"))}
    if prior.keys() != current.keys() or changed != expected_changes or len(changed) != 8:
        raise ValueError("full readback changed unrelated bitmap rows")

    selected = []
    for name in ["report.tsv", "jxl-report.tsv"]:
        for row in table(candidate / name):
            if row["layer"].endswith("-p3"):
                selected.append({"id": row["id"], "layer": row["layer"],
                                 "path": str(candidate / row["path"]), "sha256": row["sha256"]})
    inputs = candidate / "p3-inventory-list.tsv"
    write(inputs, selected)
    inventory_tool = args.imi_tool.parent / "zencodecs-main-841a171c"
    subprocess.run([sys.executable, str(Path(__file__).parents[1] / "tools/metadata-loss-audit/inventory_routes.py"),
                    str(inputs), str(candidate / "p3-inventory"), "--inventory", str(inventory_tool),
                    "--inventory-commit", "841a171c63933a66bd834fab5cbfe0086908cf34"], check=True)
    full_inventory = render / "inventory-full.tsv"
    shutil.copyfile(full_inventory, backup / full_inventory.name)
    old = table(full_inventory)
    new = table(candidate / "p3-inventory/inventory.tsv")
    for row in new:
        row["file"] = str(render / Path(row["file"]).relative_to(candidate))
    wanted = {row["file"] for row in new}
    if len(wanted) != 4:
        raise ValueError("expected four updated inventories")
    # Match the full table's column order, despite CLI versions ordering fields differently.
    new = [{key: row[key] for key in old[0]} for row in new]
    pending = render / "inventory-full.p3-prepared.tsv"
    write(pending, [row for row in old if row["file"] not in wanted] + new)
    pending.replace(full_inventory)
    for layer in ["png-p3", "png-srgb"]:
        subprocess.run([sys.executable, str(Path(__file__).with_name("byte_scan.py")),
                        str(candidate / layer), "--out", str(candidate / ("byte-scan-" + layer + ".tsv"))], check=True)
    # Pack and read back both new archives before moving either previous archive.
    results = []
    for bucket in ["train", "validate"]:
        archive = candidate / f"imazen-26-imi-p3-{bucket}.imiset"
        subprocess.run([str(args.imi_tool), "pack", str(render), "imi-p3", bucket, str(archive)], check=True)
        results.append({"bucket": bucket, "archive": archive.name, "sha256": digest(archive),
                        "bytes": archive.stat().st_size})
    saved = render / "imi-sets/before-p3-conversion-2026-10-20"
    saved.mkdir()
    for row in results:
        target = render / "imi-sets" / row["archive"]
        target.rename(saved / target.name)
        shutil.copyfile(candidate / row["archive"], target)
        if digest(target) != row["sha256"]:
            raise ValueError("copied IMI archive hash differs")
    with (candidate / "imi-sets.json").open("x") as stream:
        stream.write(json.dumps(results, indent=2) + "\n")
    with (render / "RUN.meta").open("a") as stream:
        for row in results:
            stream.write("p3_conversion_imi_set\t" + json.dumps(row) + "\n")
    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
