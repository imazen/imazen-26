#!/usr/bin/env python3
"""The export's inventory gate (EXPORT-PLAN.md, Gates): an unknown part blocks a file.

Reads `zencodecs inventory --tsv --unconsumed <tree>` output and
manifests/inventory_allowlist.tsv. A part with disposition `unknown` passes only when an
allow-list row matches its file format, kind and tag (and label prefix, when the row gives
one). Every image file must have been inventoried: a file-level `error` on an image fails
too. Files outside the class folders (the staging tree's TSVs) are ignored.

Prints the parts each allow-list row admitted and every violation; exits 1 on any violation.

Usage: inventory_gate.py <inventory.tsv> [--allowlist manifests/inventory_allowlist.tsv]
"""
import argparse
import collections
import csv
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASS_DIR = re.compile(r"(^|/)\d{4,5}-[^/]+/")  # corpus ids, or export ids with the leading 1
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".dng", ".pdf", ".webp", ".gif", ".tif", ".tiff", ".jxl"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tsv")
    ap.add_argument("--allowlist", default=os.path.join(REPO, "manifests", "inventory_allowlist.tsv"))
    a = ap.parse_args()
    csv.field_size_limit(sys.maxsize)
    with open(a.allowlist, newline="") as f:
        allow = list(csv.DictReader(f, delimiter="\t"))
    admitted = collections.Counter()
    violations, files = [], set()
    with open(a.tsv, newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            path = r["file"]
            ext = os.path.splitext(path)[1].lower()
            if not CLASS_DIR.search(path) or ext not in IMAGE_EXT:
                continue
            files.add(path)
            if r["kind"] == "file" and r["disposition"] == "error":
                violations.append((path, f"not inventoried: {r['detail']}"))
            if r["disposition"] != "unknown":
                continue
            fmt = "jpg" if ext == ".jpeg" else ext[1:]
            hit = next((i for i, w in enumerate(allow)
                        if w["format"] == fmt and w["kind"] == r["kind"] and w["tag"] == r["tag"]
                        and r["label"].startswith(w["label_prefix"])), None)
            if hit is None:
                violations.append((path, f"unknown {r['kind']} {r['tag']} {r['label'][:60]} "
                                         f"({r['length']} bytes at {r['offset']})"))
            else:
                admitted[hit] += 1
    print(f"{len(files)} image files inventoried")
    for i, w in enumerate(allow):
        print(f"allowed: {admitted[i]} × {w['format']} {w['kind']} {w['tag']} {w['label_prefix']}".rstrip())
    for path, msg in violations:
        print(f"BLOCKED {path}: {msg}")
    print(f"{len(violations)} violations")
    if not files:
        sys.exit("no image files in the inventory: nothing was checked")
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
