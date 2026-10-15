#!/usr/bin/env python3
"""Third-party read-back of the staged PNGs (EXPORT-PLAN.md, Gates).

For every PNG the originals pass recompressed, two independent decoders read both the
staged file and the file it was made from, and must produce the same RGBA8 pixels:

  - Pillow's own PNG decoder;
  - ImageMagick (libpng), as raw RGBA after `-alpha on -depth 8`.

The source is the published file, except where the pass replaced the bytes first: the
whitelist-v2 output for camera files and the flattened file for 9869/9874 (the screenshots'
metadata policy leaves pixels alone, so their published file is the source). ImageMagick
must also read each staged file with `-regard-warnings`.

Usage: png_readback.py <staging-dir> <published-dir> <whitelist-v2-dir> <flatten-dir> [--jobs 8]
Writes <staging-dir>/png_readback.tsv; exits 1 if any file fails.
"""
import argparse
import concurrent.futures as cf
import csv
import hashlib
import os
import subprocess
import sys

from PIL import Image


def pil_rgba(path):
    with Image.open(path) as im:
        return hashlib.sha256(im.convert("RGBA").tobytes()).hexdigest(), im.size


def magick_rgba(path):
    r = subprocess.run(["magick", "-regard-warnings", path, "-alpha", "on", "-depth", "8", "rgba:-"],
                       capture_output=True)
    if r.returncode != 0:
        return None, r.stderr.decode(errors="replace").strip()[:200]
    return hashlib.sha256(r.stdout).hexdigest(), ""


def check(job):
    rid, staged, source = job
    try:
        a, size_a = pil_rgba(staged)
        b, size_b = pil_rgba(source)
        if (a, size_a) != (b, size_b):
            return rid, "Pillow pixels differ"
        ma, err = magick_rgba(staged)
        if ma is None:
            return rid, f"ImageMagick: {err}"
        mb, err = magick_rgba(source)
        if mb is None:
            return rid, f"ImageMagick on the source: {err}"
        if ma != mb:
            return rid, "ImageMagick pixels differ"
        return rid, ""
    except Exception as ex:  # a decoder that cannot read the file is a failure, not a skip
        return rid, f"{type(ex).__name__}: {ex}"


def main():
    ap = argparse.ArgumentParser()
    for a in ("staging", "published", "whitelist_v2", "flatten"):
        ap.add_argument(a)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    v2 = {}
    with open(os.path.join(a.whitelist_v2, "manifest.tsv")) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            v2[r["id"]] = os.path.join(a.whitelist_v2, r["output"])
    jobs = []
    with open(os.path.join(a.staging, "changes.tsv")) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if not r["new_path"].endswith(".png"):
                continue
            if "white-background flatten" in r["steps"]:
                source = os.path.join(a.flatten, os.path.basename(r["path"]))
            elif r["steps"].startswith("whitelist-v2"):
                source = v2[r["id"]]
            else:
                source = os.path.join(a.published, r["path"])
            jobs.append((r["id"], os.path.join(a.staging, r["new_path"]), source))
    jobs.sort(key=lambda j: -os.path.getsize(j[1]))
    failed = 0
    with cf.ThreadPoolExecutor(a.jobs) as ex, open(os.path.join(a.staging, "png_readback.tsv"), "w") as out:
        out.write("id\tresult\n")
        for rid, err in ex.map(check, jobs):
            out.write(f"{rid}\t{err or 'ok'}\n")
            failed += bool(err)
            if err:
                print(f"FAILED {rid}: {err}", file=sys.stderr)
    print(f"{len(jobs)} PNGs read back by Pillow and ImageMagick, {failed} failed", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
