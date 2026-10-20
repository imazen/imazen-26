#!/usr/bin/env python3
"""Compare retained sample encodes with a prior probe and the stored corpus."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


REPORTS = ("report.tsv", "gain-maps-report.tsv", "hdr-report.tsv",
           "jxl-report.tsv", "jxl-hdr-report.tsv")


def rows(root, report):
    with (root / report).open() as stream:
        records = list(csv.DictReader(stream, delimiter="\t"))
    result = {row["path"]: row for row in records}
    if len(result) != len(records) or any(row.get("error") for row in records):
        raise ValueError("duplicate or failed sample rows")
    return result


def check_file(root, row):
    path = root / row["path"]
    if "bytes" in row and path.stat().st_size != int(row["bytes"]):
        raise ValueError("sample byte count mismatch")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if "sha256" in row and digest != row["sha256"]:
        raise ValueError("sample encoded hash mismatch")
    if row.get("metadata_path"):
        with (root / row["metadata_path"]).open("rb") as stream:
            metadata_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if metadata_digest != row["metadata_sha256"]:
            raise ValueError("gain-map metadata hash mismatch")
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stored", type=Path)
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    compared = []
    for report in REPORTS:
        stored, previous, current = (rows(root, report) for root in
                                     (args.stored, args.previous, args.current))
        if current.keys() != previous.keys() or not current:
            raise ValueError("sample membership changed")
        for path, row in current.items():
            old, prior = stored[path], previous[path]
            encoded = [check_file(root, record) for root, record in
                       ((args.stored, old), (args.previous, prior), (args.current, row))]
            pixels = [key for key in row if (key.endswith("_sha256") and "pixel" in key)
                      or key in ("rgba_sha256", "rgb16_sha256", "map_sha256")]
            compared.append({"report": report, "path": path,
                             "previous_bytes_identical": encoded[2] == encoded[1],
                             "stored_bytes_identical": encoded[2] == encoded[0],
                             "stored_bytes": (args.stored / path).stat().st_size,
                             "current_bytes": (args.current / path).stat().st_size,
                             "metadata_changed": row.get("metadata_sha256") != old.get("metadata_sha256"),
                             "pixel_fields": pixels,
                             "pixel_changes": [key for key in pixels if row[key] != old[key]]})
    result = {"files": len(compared),
              "previous_sample_byte_changes": sum(not r["previous_bytes_identical"] for r in compared),
              "stored_byte_changes": sum(not r["stored_bytes_identical"] for r in compared),
              "reported_pixel_changes": sum(bool(r["pixel_changes"]) for r in compared),
              "gain_map_metadata_changes": sum(r["metadata_changed"] for r in compared),
              "rows": compared}
    (args.current / "final-byte-comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    main()
