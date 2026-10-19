#!/usr/bin/env python3
"""Replace only a verified redo's decoder rows in the full bitmap hash table."""
import argparse
import csv
import json
from pathlib import Path
import shutil

import check_jxl_subset as check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("render", type=Path)
    parser.add_argument("number", type=int)
    args = parser.parse_args()
    check.verify(args.candidate)
    report = check.table(args.render / f"jxl-redo-{args.number}-report.tsv")
    wanted = {row["path"] for row in report}
    for row in report:
        if check.digest(args.render / row["path"]) != row["sha256"]:
            raise ValueError("promoted file no longer matches its redo report")
    evidence = args.candidate / "subset-check"
    fresh = {}
    for row in check.table(evidence / "native.tsv") + check.table(evidence / "libjxl.tsv"):
        relative = str(Path(row["path"]).relative_to(args.candidate))
        key = relative, row["decoder"]
        if relative not in wanted or key in fresh or row["status"] != "ok" or row["error"]:
            raise ValueError("unexpected or failed redo decoder row")
        fresh[key] = row
    expected = {(path, name) for path in wanted for name in ["zenjxl", "jxl-rs", "libjxl"]}
    if set(fresh) != expected:
        raise ValueError("incomplete three-reader redo coverage")
    path = args.render / "decoded-xxh3.tsv"
    text = path.read_text()
    comments = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    reader = csv.DictReader((line for line in text.splitlines() if not line.startswith("#")), delimiter="\t")
    columns, rows = reader.fieldnames, list(reader)
    keys = {(row["path"], row["decoder"]) for row in rows}
    if len(keys) != len(rows) or not expected <= keys:
        raise ValueError("duplicate or missing full-table rows")
    replaced = changed = 0
    for row in rows:
        key = row["path"], row["decoder"]
        if key not in fresh:
            continue
        new = fresh[key]
        if (row["width"], row["height"]) != (new["width"], new["height"]):
            raise ValueError("unexpected geometry change in redo")
        changed += row["xxh3"] != new["xxh3"]
        for field in columns:
            if field not in ["path", "layer"]:
                row[field] = new[field]
        replaced += 1
    backup = args.render / f"decoded-xxh3.before-jxl-redo-{args.number}.tsv"
    if backup.exists():
        raise ValueError("hash table has already been updated for this redo")
    pending = args.render / f"decoded-xxh3.prepared-jxl-redo-{args.number}.tsv"
    with pending.open("x", newline="") as stream:
        stream.write(comments)
        writer = csv.DictWriter(stream, columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    shutil.copyfile(path, backup)
    pending.replace(path)
    summary = {"rows": len(rows), "replaced_rows": replaced, "changed_bitmap_hashes": changed,
               "unrelated_rows_unchanged": len(rows) - replaced,
               "before_sha256": check.digest(backup), "after_sha256": check.digest(path)}
    (args.render / f"jxl-redo-{args.number}-evidence/hash-merge.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
