#!/usr/bin/env python3
"""Rebuild variant-sets/png-v3-index.tsv by probing R2 for what actually exists.

Render URLs must never be derived from the corpus filename. The corpus name
embeds a `_WxH` token from the *stored* dimensions, while the PNG-v3 pass wrote
EXIF-rotated output named by the *rotated* dimensions — so every original with
EXIF Orientation 5/6/7/8 has a render whose name transposes those two numbers.
A naive extension swap produced 404s for 196 of 2,160 rows and looked correct.

This probes both candidate stems and records what responds, plus whether an
`.hdr.png` companion exists (76 do; they cannot be inferred from the SDR name).

  python3 scripts/build_png_v3_index.py [--jobs 10] [-o variant-sets/png-v3-index.tsv]

Columns: id, path, sdr_url, sdr_present, hdr_url, stem_differs
  sdr_present  0 means no render exists on R2 for this image (do not link it)
  hdr_url      empty means no HDR companion
  stem_differs 1 means the render name transposes the corpus WxH token
"""
import argparse
import csv
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

R2 = "https://codec-corpus.r2.imazen.org"
PREFIX = "imazen-26-png-v3"
WXH = re.compile(r"_(\d+)x(\d+)$")


# Cloudflare 403s urllib's default User-Agent. A bare `except: return False`
# turns that into "the object is absent", which is exactly the silent failure
# this whole index exists to prevent — so only a real 404 counts as absent and
# anything else raises.
UA = {"User-Agent": "imazen-26-index (jill@imazen.io)"}


def head_ok(url):
    """True if the object exists, False on a genuine 404. Raises otherwise."""
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status == 200
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            last = e
        except Exception as e:  # transient network
            last = e
    raise RuntimeError(f"probe failed (not a 404) for {url}: {last}")


def candidates(path):
    stem = os.path.splitext(path)[0]
    m = WXH.search(stem)
    alt = WXH.sub(lambda g: f"_{g.group(2)}x{g.group(1)}", stem) if m else None
    return stem, alt


def resolve(row):
    rid, path = row
    stem, alt = candidates(path)
    for cand, differs in ((stem, "0"), (alt, "1")):
        if not cand:
            continue
        sdr = f"{R2}/{PREFIX}/{cand}.sdr.png"
        if head_ok(sdr):
            hdr = sdr.replace(".sdr.png", ".hdr.png")
            return (rid, path, sdr, "1", hdr if head_ok(hdr) else "", differs)
    return (rid, path, f"{R2}/{PREFIX}/{stem}.sdr.png", "0", "", "0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="CORPUS-MANIFEST.tsv")
    ap.add_argument("-o", "--out", default="variant-sets/png-v3-index.tsv")
    ap.add_argument("--jobs", type=int, default=10)
    a = ap.parse_args()

    with open(a.manifest, encoding="utf-8", newline="") as fh:
        rows = [(r["number"], r["path"]) for r in csv.DictReader(fh, delimiter="\t")]
    print(f"probing {len(rows)} images x up to 3 requests, {a.jobs} at a time...",
          file=sys.stderr)
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        out = sorted(ex.map(resolve, rows), key=lambda r: int(r[0]))

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "path", "sdr_url", "sdr_present", "hdr_url", "stem_differs"])
        w.writerows(out)

    absent = sum(1 for r in out if r[3] == "0")
    print(f"wrote {a.out}: {len(out)} rows, {sum(1 for r in out if r[4])} with HDR, "
          f"{sum(1 for r in out if r[5] == '1')} transposed, {absent} absent",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
