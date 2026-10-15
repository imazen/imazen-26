#!/usr/bin/env python3
"""Check a png-srgb render of a wide-gamut source against two independent conversions.

    colour_oracle.py <report.tsv> <render-dir> <originals-dir> <list.tsv> [--ids 11044,13005]
                     [--code-values <code-values report.tsv>]

For every `png-srgb` row of render-v4's report whose colour is display-p3 or adobe-rgb, the
source's code values (decoded by Pillow, or by ImageMagick/libheif for HEIC, displayed
orientation, no colour conversion) are converted to sRGB twice:

- textbook: the published primaries' RGB->XYZ matrices (D65 throughout, so no adaptation),
  the source curve (sRGB piecewise for Display P3, a 563/256 power for Adobe RGB), clip,
  sRGB encode, round;
- LittleCMS, through ImageMagick: relative colorimetric to sRGB from the source's own profile.

and compared with the render. The textbook comparison is also made on the render's own
`png-p3` twin when there is one (same decoder as the render, so decoder differences drop out),
and a row fails when the render differs from that result by more than 1 code value.
Gain-map sources have no `png-p3` twin (their p3 layers are the PQ renders): for them, pass
the report of a `render-v4 code-values` run (same list, its files under <render-dir>), whose
files hold the same decoded code values. A row with neither compares only against
third-party decodes and is printed as `info`, ungated, and counted.
Prints one line per file and exits 1 on any failure.
"""
import argparse
import csv
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageOps

SRGB_ICC = "/usr/share/color/icc/sRGB-v2-micro.icc"
TO_XYZ = {
    "display-p3": np.array([[0.4865709, 0.2656677, 0.1982173], [0.2289746, 0.6917385, 0.0792869],
                            [0.0, 0.0451134, 1.0439444]]),
    "adobe-rgb": np.array([[0.5767309, 0.1855540, 0.1881852], [0.2973769, 0.6273491, 0.0752741],
                           [0.0270343, 0.0706872, 0.9911085]]),
}
XYZ_TO_SRGB = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560],
                        [0.0556434, -0.2040259, 1.0572252]])


def decode_code_values(path, shape):
    try:
        with Image.open(path) as im:
            return np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
    except Exception:
        raw = subprocess.run(["magick", path, "-auto-orient", "-depth", "8", "rgb:-"], capture_output=True,
                             check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(shape)


def textbook(cv, space):
    v = cv.astype(np.float64) / 255.0
    lin = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4) if space == "display-p3" \
        else v ** (563 / 256)
    s = np.clip(lin @ (XYZ_TO_SRGB @ TO_XYZ[space]).T, 0.0, 1.0)
    return np.round(np.where(s <= 0.0031308, 12.92 * s, 1.055 * s ** (1 / 2.4) - 0.055) * 255).astype(np.int16)


def littlecms(path, shape):
    raw = subprocess.run(["magick", path, "-auto-orient", "-intent", "Relative", "-profile", SRGB_ICC, "-depth",
                          "8", "rgb:-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(shape).astype(np.int16)


def stats(a, b):
    d = np.abs(a - b)
    return f"max {d.max()} mean {d.mean():.4f} >1 {int((d > 1).any(axis=-1).sum())}px"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("render")
    ap.add_argument("originals")
    ap.add_argument("list")
    ap.add_argument("--ids")
    ap.add_argument("--code-values")
    a = ap.parse_args()
    keep = set(a.ids.split(",")) if a.ids else None
    with open(a.list) as f:
        source = {line.split("\t")[0]: line.split("\t")[1] for line in f if line.strip()}
    with open(a.report, newline="") as f:
        rows = [r for r in csv.DictReader(f, delimiter="\t") if not r["error"]]
    p3 = {r["id"]: r["path"] for r in rows if r["layer"] == "png-p3"}
    if a.code_values:
        with open(a.code_values, newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if r["layer"] == "code-values" and not r["error"]:
                    p3.setdefault(r["id"], r["path"])
    failed = ungated = 0
    for r in rows:
        if r["layer"] != "png-srgb" or r["colour"] not in TO_XYZ or (keep and r["id"] not in keep):
            continue
        with Image.open(os.path.join(a.render, r["path"])) as im:
            ours = np.asarray(im.convert("RGB")).astype(np.int16)
        src = decode_code_values(source[r["id"]], ours.shape)
        if src.shape != ours.shape:
            print(f"{r['id']} FAIL shape {src.shape} vs {ours.shape}")
            failed += 1
            continue
        ref = textbook(src, r["colour"])
        lc = littlecms(source[r["id"]], ours.shape)
        line = f"{r['id']} {r['colour']}: ours-textbook {stats(ours, ref)}; lcms-textbook {stats(lc, ref)}; " \
               f"ours-lcms {stats(ours, lc)}"
        bad = None
        if r["id"] in p3:
            with Image.open(os.path.join(a.render, p3[r["id"]])) as im:
                own = np.asarray(im.convert("RGB"))
            own_ref = textbook(own, r["colour"])
            line += f"; ours-textbook(own decode) {stats(ours, own_ref)}"
            bad = np.abs(ours - own_ref).max() > 1
        print({None: "info ", True: "FAIL ", False: "ok   "}[bad] + line, flush=True)
        failed += bad is True
        ungated += bad is None
    print(f"{failed} failed, {ungated} ungated (no own decode)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
