#!/usr/bin/env python3
"""Check stored sequential-JPEG diagnostics with native inventories and libjxl.

All inputs are already-public originals or diagnostic bytes made by our codecs.
Native labels/details and subprocess diagnostics are captured in memory only.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("strip_review", ROOT / "tools/metadata-loss-audit/strip_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results")
    parser.add_argument("originals")
    parser.add_argument("artifacts")
    parser.add_argument("out")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--djxl", required=True)
    args = parser.parse_args()
    version = subprocess.run([args.djxl, "--version"], capture_output=True, text=True)
    if "v0.12.0" not in version.stdout + version.stderr:
        raise review.AuditError("WrongLibjxlVersion")
    originals = dict(line.rstrip("\n").split("\t", 1) for line in Path(args.originals).read_text().splitlines())
    rows = review.table(args.results)
    ids = [row["id"] for row in rows]
    if not ids or len(set(ids)) != len(ids) or set(ids) != set(originals):
        raise review.AuditError("IncompleteOrDuplicateCases")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    artifact = Path(args.artifacts)
    records = []
    for row in rows:
        cid = row["id"]
        if not cid.isdecimal():
            raise review.AuditError("NondecimalId")
        if row["error"] or any(row[key] != "1" for key in (
                "seq_coeff_equal", "seq_jxl_rebuild_exact", "seq_vs_orig_jxl_pixels_equal")):
            raise review.AuditError("NativeParityFailed")
        if row["seq_pixel_maxdiff"] != "0" or row["original_coeff_sha256"] != row["sequential_coeff_sha256"]:
            raise review.AuditError("CoefficientOrPixelChange")
        jpeg = artifact / "jpeg" / (row["sequential_sha256"] + ".jpg")
        jxl = artifact / "jxl" / (row["sequential_jxl_sha256"] + ".jxl")
        paths = {"original": Path(originals[cid]), "sequential": jpeg, "jxl": jxl}
        expected = {"original": row["original_sha256"], "sequential": row["sequential_sha256"],
                    "jxl": row["sequential_jxl_sha256"]}
        inventories = {}
        for kind, path in paths.items():
            data = path.read_bytes()
            if review.digest(data) != expected[kind]:
                raise review.AuditError("ArtifactHashMismatch")
            inventories[kind] = review.inventory(args.inventory, data)
        if not any(part["tag"] == "jbrd" for part in inventories["jxl"]):
            raise review.AuditError("MissingJbrdInventoryPart")
        rebuilt = out / (cid + ".libjxl.jpg")
        result = subprocess.run([args.djxl, str(jxl), str(rebuilt), "--quiet"], capture_output=True)
        if result.returncode or review.digest(rebuilt.read_bytes()) != row["sequential_sha256"]:
            raise review.AuditError("IndependentRebuildMismatch")
        record = {"id": cid, "coefficient_payload_sha256": row["original_coeff_sha256"],
                  "original_sha256": row["original_sha256"], "sequential_sha256": row["sequential_sha256"],
                  "sequential_jxl_sha256": row["sequential_jxl_sha256"],
                  "libjxl_rebuild_exact": True, "native_inventories": inventories}
        (out / (cid + ".json")).write_text(json.dumps(record, indent=2) + "\n")
        records.append(record)
        print(json.dumps({"complete": len(records), "total": len(rows)}), flush=True)
    summary = {"cases": len(records), "coefficient_payloads_unchanged": len(records),
               "native_and_libjxl_rebuild_exact": len(records),
               "native_inventories": len(records) * 3,
               "results_sha256": review.digest(Path(args.results).read_bytes()),
               "tool_sha256": review.digest(Path(__file__).read_bytes()),
               "parser_sha256": review.digest(Path(review.__file__).read_bytes()),
               "inventory_sha256": review.digest(Path(args.inventory).read_bytes()),
               "djxl_sha256": review.digest(Path(args.djxl).read_bytes())}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    sys.excepthook = lambda kind, value, trace: print("fatal: " + kind.__name__, file=sys.stderr)
    try:
        main()
    except review.AuditError as error:
        print("fatal: " + str(error), file=sys.stderr)
        sys.exit(1)
