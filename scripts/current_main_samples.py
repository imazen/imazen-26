#!/usr/bin/env python3
"""Plan one retained re-encode sample per existing layer kind/color/layout.

Select the smallest encoded member of each group to keep this compatibility
probe bounded. This is a sample comparison, not a quality or performance sweep.
"""
import argparse
import csv
import json
from pathlib import Path


def table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("render", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    selected, coverage = set(), []
    for report, fields in [
        ("report.tsv", ["layout", "colour", "gain_map"]),
        ("jxl-report.tsv", ["kind", "colour"]),
        ("hdr-report.tsv", ["colour", "gain_map"]),
        ("imi-report.tsv", ["sample", "channels", "colour", "gain_map"]),
    ]:
        groups = {}
        for row in table(args.render / report):
            if row["error"]:
                raise ValueError("input render contains failed rows")
            key = tuple(row[field] for field in fields)
            if key not in groups or int(row["bytes"]) < int(groups[key]["bytes"]):
                groups[key] = row
        for key, row in sorted(groups.items()):
            selected.add(row["id"])
            coverage.append({"report": report, "group": list(key), "id": row["id"],
                             "path": row["path"], "sha256": row["sha256"]})
    lines = {}
    for line in (args.render / "list.tsv").read_text().splitlines():
        cid, source, stem, provenance = line.split("\t", 3)
        if cid in selected:
            if not Path(source).is_file():
                raise FileNotFoundError("selected original is missing: " + cid)
            json.loads(provenance)
            lines[cid] = line
    if set(lines) != selected:
        raise ValueError("selected ids are absent from source list")
    hdr = {row["id"] for row in table(args.render / "hdr-report.tsv")}
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "list.tsv").write_text("".join(lines[cid] + "\n" for cid in sorted(lines)))
    (args.out / "hdr-list.tsv").write_text("".join(lines[cid] + "\n" for cid in sorted(selected & hdr)))
    (args.out / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    print(json.dumps({"groups": len(coverage), "ids": len(selected), "hdr_ids": len(selected & hdr)}))


if __name__ == "__main__":
    main()
