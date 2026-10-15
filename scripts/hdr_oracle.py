#!/usr/bin/env python3
"""Rebuild every render-v4 `png-hdr` file from third-party decodes and compare.

    hdr_oracle.py <hdr-report.tsv> <render-dir> <list.tsv> <hdr-info.tsv> [--ids 11064,11498]

For each `png-p3-hdr` row:

- SDR base: Pillow (JPEG, EXIF orientation applied) or libheif's `heif-dec` (HEIC, its
  transforms applied), code values without colour conversion.
- Gain map: exiftool's `-b -MPImage2` decoded by Pillow (JPEG), or `heif-dec --with-aux`
  (HEIC: the `urn:com:apple:photo:2020:aux:hdrgainmap` image, which the iPhone 16/17 `tmap`
  files share). Oriented like the base: kept when its aspect matches, rotated by the source
  orientation when the axes are swapped.
- Parameters: exiftool's `hdrgm` XMP for JPEG; for HEIC, render-v4's `hdr-info` (the Apple
  MakerNote headroom, or the parsed `tmap` payload).
- Reconstruction in numpy, f64: sRGB EOTF; each gain-map value mapped to its gain (Apple
  legacy `1 + (H - 1) * sRGB_EOTF(g)`, ISO 21496-1 `2^(min + (max - min) * g^(1/gamma))`),
  then the gains blended with Shepard's inverse-distance weights at corner-aligned gain-map
  coordinates (ultrahdr-core's sampling, which render-v4 uses for both curves); ISO offsets
  `(sdr + k_sdr) * gain - k_hdr`; 203 nits per 1.0; ST 2084; 16-bit rounding. For
  information it also reports the libultrahdr variant, which blends the stored values first.

The bases come from other decoders, which differ from zen's in a few pixels, so the gate is
statistical: a row fails when the mean absolute difference exceeds 1 code, the 99.9th
percentile of the difference above 1 nit exceeds 0.01 stops, or either cLLI value differs
from the oracle's own measurement by more than 0.5%.
"""
import argparse
import csv
import glob
import json
import os
import struct
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageOps

M1, M2 = 2610 / 16384, 2523 / 4096 * 128
C1, C2, C3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32


def pq(nits):
    y = np.clip(nits / 10000.0, 0, 1) ** M1
    return ((C1 + C2 * y) / (1 + C3 * y)) ** M2


def pq_nits(e):
    p = np.clip(e, 0, 1) ** (1 / M2)
    return 10000.0 * (np.maximum(p - C1, 0) / (C2 - C3 * p)) ** (1 / M1)


def eotf(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def axis(n, gn, integer):
    """Corner-aligned sample index, fraction and next-sample distance along one axis."""
    if integer:
        s = n // gn
        i = np.arange(n)
        i0 = np.minimum(i // s, gn - 1)
        f = (i % s) / s
    else:
        g = (np.arange(n, dtype=np.float32) * np.float32(1.0 / n)) * np.float32(gn)
        i0 = np.minimum(np.floor(g).astype(int), gn - 1)
        f = (g - np.floor(g)).astype(np.float64)
    i1 = np.minimum(i0 + 1, gn - 1)
    nxt = np.where((i0 == i1) & integer, 0.0, 1.0)
    return i0, i1, f, nxt


def shepard(values, w, h, gain_of):
    """Blend per-sample gains with Shepard's weights (ultrahdr-core's sampler)."""
    gh, gw = values.shape
    # ultrahdr-core takes the integer path only when both axes divide (and the table fits).
    integer = w % gw == 0 and h % gh == 0 and (w // gw) * (h // gh) <= 4096
    x0, x1, fx, nx = axis(w, gw, integer)
    y0, y1, fy, ny = axis(h, gh, integer)
    fx, nx = fx[None, :], nx[None, :]
    fy, ny = fy[:, None], ny[:, None]
    d = np.stack([np.hypot(fx, fy), np.hypot(fx, fy - ny), np.hypot(fx - nx, fy), np.hypot(fx - nx, fy - ny)])
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / d
        zero = d == 0
        first = zero.argmax(axis=0)
        hit = zero.any(axis=0)
        wts = np.where(hit, np.arange(4)[:, None, None] == first, inv / inv.sum(axis=0))
    g = gain_of(values.astype(np.float64))
    return wts[0] * g[y0][:, x0] + wts[1] * g[y1][:, x0] + wts[2] * g[y0][:, x1] + wts[3] * g[y1][:, x1]


def png16(path):
    raw = subprocess.run(["magick", path, "-depth", "16", "-endian", "LSB", "rgb:-"], capture_output=True,
                         check=True).stdout
    with Image.open(path) as im:
        w, h = im.size
    return np.frombuffer(raw, "<u2").reshape(h, w, 3)


def clli(path):
    d = open(path, "rb").read()
    pos = 8
    while pos < len(d):
        n, t = struct.unpack(">I4s", d[pos:pos + 8])
        if t == b"cLLI":
            return [v / 10000 for v in struct.unpack(">II", d[pos + 8:pos + 16])]
        pos += 12 + n
    return None


def exif_orientation_rotate(gm, orientation):
    if orientation == "Rotate90":
        return np.rot90(gm, k=-1)
    if orientation == "Rotate270":
        return np.rot90(gm, k=1)
    raise SystemExit(f"oracle has no rule for orientation {orientation}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("render")
    ap.add_argument("list")
    ap.add_argument("hdr_info")
    ap.add_argument("--ids")
    a = ap.parse_args()
    keep = set(a.ids.split(",")) if a.ids else None
    source = {l.split("\t")[0]: l.split("\t")[1] for l in open(a.list) if l.strip()}
    info = {r["id"]: r for r in csv.DictReader(open(a.hdr_info), delimiter="\t")}
    rows = [r for r in csv.DictReader(open(a.report), delimiter="\t")
            if r["layer"] == "png-p3-hdr" and not r["error"] and (keep is None or r["id"] in keep)]
    failed = 0
    with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/tmp")) as tmp:
        for r in rows:
            src, inf = source[r["id"]], info[r["id"]]
            ours = png16(os.path.join(a.render, r["path"]))
            h, w, _ = ours.shape
            work = os.path.join(tmp, r["id"])
            os.makedirs(work)
            if src.lower().endswith((".jpg", ".jpeg")):
                with Image.open(src) as im:
                    base = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
                gm_path = os.path.join(work, "gm.jpg")
                with open(gm_path, "wb") as f:
                    subprocess.run(["exiftool", "-b", "-MPImage2", src], stdout=f, check=True)
                with Image.open(gm_path) as im:
                    gm = np.asarray(im.convert("L"))
                x = json.loads(subprocess.run(["exiftool", "-j", "-n", "-XMP-hdrgm:all", gm_path],
                                              capture_output=True, check=True).stdout)[0]
                curve = ("iso", x["GainMapMin"], x["GainMapMax"], x["Gamma"], x["OffsetSDR"], x["OffsetHDR"])
            else:
                subprocess.run(["heif-dec", "--with-aux", "--no-colons", src, os.path.join(work, "b.png")],
                               capture_output=True, check=True)
                with Image.open(os.path.join(work, "b.png")) as im:
                    base = np.asarray(im.convert("RGB"))
                aux = glob.glob(os.path.join(work, "b-urn_com_apple_photo_2020_aux_hdrgainmap.png"))
                if not aux:
                    raise SystemExit(f"{r['id']}: libheif wrote no Apple gain-map image")
                with Image.open(aux[0]) as im:
                    gm = np.asarray(im.convert("RGB"))[:, :, 0]
                if inf["gain_map"] == "heic-apple-legacy":
                    curve = ("apple", float(inf["headroom_stops"]))
                else:
                    p = inf["params"]  # "base B alt A; min m max M gamma g offsets s/h"
                    f = p.replace(";", "").split()
                    curve = ("iso", float(f[f.index("min") + 1]), float(f[f.index("max") + 1]),
                             float(f[f.index("gamma") + 1]), *map(float, f[f.index("offsets") + 1].split("/")))
            if base.shape[:2] != (h, w):
                print(f"FAIL {r['id']}: base {base.shape[1]}x{base.shape[0]} vs render {w}x{h}")
                failed += 1
                continue
            gh, gw = gm.shape
            if abs((gw / gh) / (w / h) - 1) >= 0.02:
                gm = exif_orientation_rotate(gm, inf["source_orientation"])
            lin = eotf(base.astype(np.float64) / 255.0)
            if curve[0] == "apple":
                gain_of = lambda v: 1 + (2 ** curve[1] - 1) * eotf(v / 255.0)
                k_sdr = k_hdr = 0.0
            else:
                _, mn, mx, gamma, k_sdr, k_hdr = curve
                gain_of = lambda v: 2 ** (mn + (mx - mn) * (v / 255.0) ** (1 / gamma))
            gain = shepard(gm, w, h, gain_of)[:, :, None]
            hdr = (lin + k_sdr) * gain - k_hdr
            ref = np.round(pq(np.maximum(hdr, 0) * 203.0) * 65535).astype(np.int32)
            # libultrahdr's variant, for information: blend the stored values, then map.
            code = shepard(gm, w, h, lambda v: v)[:, :, None]
            alt = (lin + k_sdr) * gain_of(code) - k_hdr
            alt = np.round(pq(np.maximum(alt, 0) * 203.0) * 65535).astype(np.int32)
            an = pq_nits(alt / 65535.0)
            d = np.abs(ours.astype(np.int32) - ref)
            on, rn = pq_nits(ours / 65535.0), pq_nits(ref / 65535.0)
            lit = (on > 1) & (rn > 1)
            stops = np.abs(np.log2(on[lit] / rn[lit]))
            lit_alt = (on > 1) & (an > 1)
            alt_stops = np.abs(np.log2(on[lit_alt] / an[lit_alt]))
            peak = rn.max(axis=2)
            ref_clli = [peak.max(), peak.mean()]
            got_clli = clli(os.path.join(a.render, r["path"]))
            clli_err = max(abs(got_clli[i] / ref_clli[i] - 1) for i in range(2))
            p999 = float(np.quantile(stops, 0.999)) if stops.size else 0.0
            bad = d.mean() > 1 or p999 > 0.01 or clli_err > 0.005
            failed += bad
            print(f"{'FAIL' if bad else 'ok  '} {r['id']} {inf['gain_map']}: codes mean {d.mean():.3f} "
                  f"p99.9 {np.quantile(d, 0.999):.0f} max {d.max()}; stops p99.9 {p999:.4f} max "
                  f"{stops.max() if stops.size else 0:.4f}; cLLI ours {got_clli[0]:.1f}/{got_clli[1]:.1f} "
                  f"oracle {ref_clli[0]:.1f}/{ref_clli[1]:.1f}; libultrahdr variant p99.9 "
                  f"{np.quantile(alt_stops, 0.999) if alt_stops.size else 0:.4f} stops", flush=True)
    print(f"{failed} failed of {len(rows)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
