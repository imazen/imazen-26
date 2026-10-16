#!/usr/bin/env python3
"""Size the export repositories from a finished render v4 output (EXPORT-PLAN.md, "Repositories").

    export_sizing.py <render-dir> [--out sizing.tsv]

Reads the render's report.tsv, hdr-report.tsv, jxl-report.tsv and jxl-hdr-report.tsv (those
present), the manifests (each original's size) and the successor family map (each image's
bucket, which list.tsv must agree with), and prints:

- per layer (originals, png-p3, png-srgb, jxl-p3, jxl-srgb) and bucket: files and bytes, against
  GitHub's 10 GB repository cap;
- the XL images: every export id with a file over GitHub's 100 MiB per-file limit in any layer,
  with that file. An XL image leaves the other repositories completely, so the totals are also
  given without the XL images.

Writes one row per (layer, bucket) to --out.
"""
import argparse
import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE_LIMIT = 100 * 1024 * 1024
REPO_LIMIT = 10 * 1000 ** 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("render")
    ap.add_argument("--out", default="sizing.tsv")
    a = ap.parse_args()
    bucket = {"1" + r["id"]: r["split"] for r in csv.DictReader(
        open(os.path.join(REPO, "manifests", "split_map_family_v2.tsv")), delimiter="\t")}
    for line in open(os.path.join(a.render, "list.tsv")):
        f = line.rstrip("\n").split("\t")
        if json.loads(f[3])["split"] != bucket.get(f[0]):
            sys.exit(f"{f[0]}: list.tsv's bucket is not the family map's")
    files = []  # (export id, layer, path, bytes)
    for b in ("train", "validate", "test"):
        for r in csv.DictReader(open(os.path.join(REPO, "manifests", f"{b}.tsv")), delimiter="\t"):
            files.append(("1" + r["id"], "originals", r["path"], int(r["bytes_actual"])))
    for name in ("report.tsv", "hdr-report.tsv", "jxl-report.tsv", "jxl-hdr-report.tsv"):
        p = os.path.join(a.render, name)
        if not os.path.exists(p):
            print(f"note: no {name}", file=sys.stderr)
            continue
        for r in csv.DictReader(open(p), delimiter="\t"):
            if r["error"]:
                continue
            layer = r["layer"].removesuffix("-hdr")
            files.append((r["id"], layer, r["path"], int(r["bytes"])))
    xl = {}
    for i, layer, path, n in files:
        if n > FILE_LIMIT:
            xl.setdefault(i, []).append((layer, path, n))
    rows = []
    for layer in ("originals", "png-p3", "png-srgb", "jxl-p3", "jxl-srgb"):
        for b in ("train", "validate", "test"):
            sel = [(i, n) for i, l, _, n in files if l == layer and bucket.get(i) == b]
            kept = [(i, n) for i, n in sel if i not in xl]
            rows.append((layer, b, len(sel), sum(n for _, n in sel), len(kept), sum(n for _, n in kept)))
    with open(a.out, "w") as f:
        f.write("layer\tbucket\tfiles\tbytes\tfiles_without_xl\tbytes_without_xl\n")
        f.writelines("\t".join(map(str, r)) + "\n" for r in rows)
    print(f"{'layer':<10} {'bucket':<9} {'files':>6} {'GB':>7} {'GB w/o XL':>10}")
    for layer, b, nf, nb, nk, kb in rows:
        flag = "  over 10 GB" if kb > REPO_LIMIT else ""
        print(f"{layer:<10} {b:<9} {nf:>6} {nb / 1e9:>7.2f} {kb / 1e9:>10.2f}{flag}")
    for layer in ("originals", "png-p3", "png-srgb", "jxl-p3", "jxl-srgb"):
        tot = sum(r[5] for r in rows if r[0] == layer)
        print(f"{layer:<10} all       {sum(r[4] for r in rows if r[0] == layer):>6} {'':>7} {tot / 1e9:>10.2f}"
              + ("  over 10 GB" if tot > REPO_LIMIT else ""))
    print(f"\nXL images (a file over 100 MiB in some layer): {len(xl)}")
    for i in sorted(xl):
        biggest = max(xl[i], key=lambda x: x[2])
        print(f"  {i} ({bucket.get(i, '?')}): {len(xl[i])} files over; largest {biggest[0]} "
              f"{biggest[2] / 2**20:.1f} MiB  {biggest[1]}")


if __name__ == "__main__":
    main()
