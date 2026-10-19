#!/usr/bin/env python3
"""Build encoded-file inventory routes from the gain-map sample-hash report."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("render", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    report = args.render / "gain-maps-report.tsv"
    with report.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows or any(row["error"] for row in rows):
        raise ValueError("missing or failed gain-map rows")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate gain-map ids")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "layer", "path", "sha256"])
        for row in rows:
            path = (args.render / row["path"]).absolute()
            # map_sha256 hashes decoded map.data, not the encoded PNG.
            writer.writerow([row["id"], "gain-maps", path, digest(path)])
    provenance = {"routes": len(rows), "report_sha256": digest(report),
                  "list_sha256": digest(args.out), "tool_sha256": digest(Path(__file__)),
                  "hash_domain": "encoded PNG file bytes; report map_sha256 is decoded samples"}
    args.out.with_suffix(".json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance))


if __name__ == "__main__":
    main()
