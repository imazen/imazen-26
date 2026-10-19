#!/usr/bin/env python3
"""Compare two complete jxl-decode-check tables, including gain-map metadata."""

import argparse
import csv
import json
from pathlib import Path


def read(path, files):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    keyed = {}
    for row in rows:
        key = (row["path"], row["decoder"])
        if key in keyed:
            raise ValueError(f"duplicate decoder row: {key}")
        if row["status"] != "ok" or row["gm_status"] not in ("", "ok", "-"):
            raise ValueError(f"unsuccessful decoder row: {key}")
        keyed[key] = row
    if len({key[0] for key in keyed}) != files:
        raise ValueError(f"expected {files} files in {path}")
    if len(keyed) != files * 2:
        raise ValueError(f"expected two decoder rows per file in {path}")
    return keyed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--files", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    before = read(args.baseline, args.files)
    after = read(args.candidate, args.files)
    if before.keys() != after.keys():
        raise ValueError("decoder row identities changed")
    changes = []
    for key, row in before.items():
        fields = sorted(k for k in row if row[k] != after[key].get(k))
        if fields:
            changes.append({"path": key[0], "decoder": key[1], "fields": fields})
    result = {"files": args.files, "rows": len(before), "changed_rows": changes}
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{args.files} files, {len(before)} rows, {len(changes)} changed rows")
    if changes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
