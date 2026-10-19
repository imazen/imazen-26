#!/usr/bin/env python3
"""Recover a suppressed candidate report only from exactly matching reference files.

Every candidate must equal its reference row's byte count and SHA256. A changed,
missing, duplicate or extra bitstream fails; no pixel hash is inferred for it.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    rows, columns, references = [], None, {}
    for name in ["report.initial.tsv", "report.remaining-small.tsv", "report.remaining-large.tsv"]:
        path = args.reference / name
        references[name] = sha(path)
        with path.open() as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if columns is not None and reader.fieldnames != columns:
                raise ValueError("reference schemas differ")
            columns = reader.fieldnames
            rows.extend(reader)
    ids = {line.split("\t", 1)[0] for line in (args.candidate / "list.tsv").read_text().splitlines()}
    expected = {row["path"] for row in rows}
    actual = {str(path.relative_to(args.candidate)) for path in args.candidate.glob("jxl-*/*/*.jxl")}
    if len(expected) != len(rows) or expected != actual or len(rows) != 2 * len(ids):
        raise ValueError("missing, duplicate or extra candidate files")
    if {row["id"] for row in rows} != ids:
        raise ValueError("candidate and reference ids differ")
    for row in rows:
        path = args.candidate / row["path"]
        if row["error"] or row["kind"] != "lossless":
            raise ValueError("reference is not a passing lossless row")
        if path.stat().st_size != int(row["bytes"]) or sha(path) != row["sha256"]:
            raise ValueError("candidate differs from reference: " + row["id"])
    suppressed = args.candidate / "report.tsv"
    if suppressed.exists():
        if suppressed.stat().st_size:
            raise ValueError("refusing to replace an existing report")
        suppressed.rename(args.candidate / "report.suppressed.tsv")
    destination = args.candidate / "jxl-report.tsv"
    with destination.open("x") as stream:
        writer = csv.DictWriter(stream, columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row["id"], row["layer"])))
    provenance = {"method": "reference rows reused only after exact byte-count/SHA256 equality",
                  "files": len(rows), "reference_reports": references,
                  "report_sha256": sha(destination), "tool_sha256": sha(Path(__file__)),
                  "candidate_build_sha256": sha(args.candidate / "build.json")}
    (args.candidate / "report-recovery.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance))


if __name__ == "__main__":
    main()
