#!/usr/bin/env python3
"""Prepare and verify an explicit lossless JXL redo, without changing the render."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inputs(root):
    rows = table(root / "jxl-report.tsv")
    keys = [(row["id"], row["layer"]) for row in rows]
    if not rows or len(keys) != len(set(keys)):
        raise ValueError("empty or duplicate redo rows")
    for row in rows:
        path = root / row["path"]
        if row["error"] or row["kind"] != "lossless":
            raise ValueError("redo contains an error or non-lossless row")
        if path.stat().st_size != int(row["bytes"]) or digest(path) != row["sha256"]:
            raise ValueError("redo file differs from its encoded report")
        if path.stat().st_size > 100 * 1024 * 1024:
            raise ValueError("redo file exceeds the 100 MiB limit")
    twins = {(row["id"], row["layer"].replace("png-", "jxl-")): row
             for row in table(root / "report.tsv")}
    if set(keys) != set(twins):
        raise ValueError("redo and PNG twin coverage differ")
    for row in rows:
        twin = twins[row["id"], row["layer"]]
        if twin["error"] or row["pixels_sha256"] != twin["rgba_sha256"]:
            raise ValueError("redo does not claim the exact PNG twin samples")
        if digest(root / twin["path"]) != twin["sha256"]:
            raise ValueError("PNG twin file changed")
    return rows, twins


def prepare(root):
    rows, twins = inputs(root)
    out = root / "subset-check"
    out.mkdir(exist_ok=False)
    (out / "jxl.list").write_text("".join(str(root / r["path"]) + "\n" for r in rows))
    (out / "png.list").write_text("".join(str(root / twins[r["id"], r["layer"]]["path"]) + "\n"
                                         for r in rows))
    with (out / "inventory-list.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "layer", "path", "sha256"])
        writer.writerows([r["id"], r["layer"], root / r["path"], r["sha256"]] for r in rows)
    print(json.dumps({"prepared_jxl": len(rows), "png_twins": len(twins)}), flush=True)


def verify(root):
    rows, twins = inputs(root)
    out = root / "subset-check"
    native, reference, png = table(out / "native.tsv"), table(out / "libjxl.tsv"), table(out / "png.tsv")
    decoded = {}
    for row in native + reference + png:
        key = row["path"], row["decoder"]
        if key in decoded or row["status"] != "ok" or row["error"]:
            raise ValueError("duplicate or failed decoder row")
        decoded[key] = row
    expected = set()
    for row in rows:
        path = str(root / row["path"])
        twin = twins[row["id"], row["layer"]]
        png_path = str(root / twin["path"])
        keys = [(path, name) for name in ["zenjxl", "jxl-rs", "libjxl"]] + [(png_path, "zenpng")]
        expected.update(keys)
        signatures = [tuple(decoded[key][field] for field in
                            ["width", "height", "channels", "bits", "xxh3"]) for key in keys]
        if len(set(signatures)) != 1:
            raise ValueError("three JXL readers and PNG twin disagree")
        if signatures[0][:2] != (row["width"], row["height"]):
            raise ValueError("decoded geometry differs from the redo report")
    if set(decoded) != expected:
        raise ValueError("decoder coverage differs from the explicit redo")
    checks = table(root / "jxl-check.tsv")
    if (len(checks) != len(rows)
            or {row["path"] for row in checks} != {row["path"] for row in rows}
            or any(row["result"] != "ok" for row in checks)):
        raise ValueError("JXL box/color/pixel check did not pass every redo file")
    inventory = json.loads((out / "inventory/summary.json").read_text())
    if (inventory["routes"] != len(rows) or inventory["failures"]
            or inventory["provenance"]["list_sha256"] != digest(out / "inventory-list.tsv")):
        raise ValueError("inventory did not pass every redo file")
    for layer in ["jxl-p3", "jxl-srgb"]:
        scan = table(out / ("byte-scan-" + layer + ".tsv"))
        # The scanner emits a row for every file, including files without findings.
        expected_paths = {str(Path(row["path"]).relative_to(layer))
                          for row in rows if row["layer"] == layer}
        if len(scan) != len(expected_paths) or {row["path"] for row in scan} != expected_paths:
            raise ValueError("byte-scan coverage differs from the redo")
        if any(row["findings"] for row in scan):
            raise ValueError("redo byte scan has findings")
    result = {"jxl_files": len(rows), "decoder_rows": len(decoded),
              "three_decoders_and_png_twins_identical": True,
              "jxl_report_sha256": digest(root / "jxl-report.tsv")}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "verify"])
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    {"prepare": prepare, "verify": verify}[args.mode](args.root)


if __name__ == "__main__":
    main()
