#!/usr/bin/env python3
"""Gate for the render v4 JPEG XL layers (EXPORT-PLAN.md, "Gates").

    render_v4_jxl_check.py <out-dir> [--jobs 8] [--ids 11044,13005]

Reads <out-dir>/jxl-report.tsv (render-v4 jxl), <out-dir>/report.tsv (the PNG twins) and
<out-dir>/list.tsv (each original's sha256), and checks every JXL with libjxl:

- lossless: render-v4's decode hash equals the PNG twin's (`png-p3` for `jxl-p3`, `png-srgb`
  for `jxl-srgb`); libjxl's `djxl` decodes the file to the same pixels; `jxlinfo` states the
  same colour as the twin (the sRGB or Display P3 enum, or an ICC profile for Adobe RGB, which
  `djxl --icc_out` must return byte for byte as the PNG's `iCCP` holds it);
- JPEG-in-JXL: render-v4's rebuild and libjxl's (`djxl out.jpg`) both give the original's
  sha256;
- JPEG-in-JXL without reconstruction data: `djxl` decodes it (pixels are the JPEG's, by
  libjxl's JPEG decode, so no hash to compare);
- the 16-bit PQ `.hdr.jxl` files (<out-dir>/jxl-hdr-report.tsv, when present): render-v4's
  and libjxl's 16-bit decodes give the `.hdr.png` twin's sample hash (<out-dir>/hdr-report.tsv),
  and `jxlinfo` states P3 primaries with the PQ transfer function.

Writes <out-dir>/jxl-check.tsv and exits 1 on any failure.
"""
import argparse
import csv
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from concurrent.futures import ProcessPoolExecutor

import numpy as np


def pnm(data):
    """Parse djxl's P5/P6/P7 output: (channels, samples); 16-bit PNM comes back big-endian."""
    if data[:2] == b"P7":
        head, _, body = data.partition(b"ENDHDR\n")
        f = dict(line.split(b" ", 1) for line in head.split(b"\n")[1:] if b" " in line)
        w, h, d = int(f[b"WIDTH"]), int(f[b"HEIGHT"]), int(f[b"DEPTH"])
        return d, np.frombuffer(body, np.uint8)[: w * h * d].reshape(h, w, d)
    fields, pos = [], 0
    while len(fields) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end
    pos += 1
    ch = {b"P5": 1, b"P6": 3}[fields[0]]
    w, h, maxval = int(fields[1]), int(fields[2]), int(fields[3])
    dtype = ">u2" if maxval > 255 else np.uint8
    return ch, np.frombuffer(data[pos:], dtype)[: w * h * ch].reshape(h, w, ch)


def rgba_hash(ch, px):
    rgb = np.repeat(px, 3, axis=2) if ch == 1 else px[:, :, :3]
    alpha = px[:, :, 3:4] if ch == 4 else np.full(px.shape[:2] + (1,), 255, np.uint8)
    return hashlib.sha256(np.concatenate([rgb, alpha], axis=2).tobytes()).hexdigest()


def png_iccp(path):
    d = open(path, "rb").read()
    pos = 8
    while pos < len(d):
        n, t = struct.unpack(">I4s", d[pos:pos + 8])
        if t == b"iCCP":
            body = d[pos + 8:pos + 8 + n]
            return zlib.decompress(body[body.index(b"\0") + 2:])
        pos += 12 + n
    return None


def check(job):
    out_dir, r, twin, original_sha = job
    path = os.path.join(out_dir, r["path"])
    res = {"id": r["id"], "layer": r["layer"], "kind": r["kind"], "path": r["path"]}
    try:
        info = subprocess.run(["jxlinfo", path], capture_output=True, text=True, check=True).stdout
        colour_line = next((l for l in info.splitlines() if l.startswith("Color space:")), "")
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/tmp")) as tmp:
            if r["kind"] == "lossless":
                if twin is None:
                    raise ValueError("no PNG twin row")
                if r["pixels_sha256"] != twin["rgba_sha256"]:
                    raise ValueError("render-v4 decode hash differs from the PNG twin")
                ext = {"gray8": "pgm", "rgb8": "ppm", "rgba8": "pam"}[twin["layout"]]
                out = os.path.join(tmp, "d." + ext)
                icc = os.path.join(tmp, "d.icc")
                subprocess.run(["djxl", path, out, f"--icc_out={icc}", "--quiet"], capture_output=True, check=True)
                ch, px = pnm(open(out, "rb").read())
                if rgba_hash(ch, px) != twin["rgba_sha256"]:
                    raise ValueError("libjxl decodes different pixels")
                srgb_layer = r["layer"] == "jxl-srgb" or twin["colour"] in ("srgb", "assumed-srgb")
                if srgb_layer:
                    ok = "sRGB primaries, sRGB transfer function" in colour_line or (
                        "Grayscale" in colour_line and "sRGB transfer function" in colour_line)
                elif twin["colour"] == "display-p3":
                    ok = "P3 primaries, sRGB transfer function" in colour_line
                else:
                    ok = "ICC profile" in colour_line and open(icc, "rb").read() == png_iccp(
                        os.path.join(out_dir, twin["path"]))
                if not ok:
                    raise ValueError(f"colour statement differs from the twin: {colour_line}")
                res["result"] = "ok"
            elif r["kind"] == "jpeg-in-jxl":
                if r["jpeg_sha256"] != original_sha:
                    raise ValueError("render-v4's rebuild is not the original")
                out = os.path.join(tmp, "r.jpg")
                subprocess.run(["djxl", path, out, "--quiet"], capture_output=True, check=True)
                if hashlib.sha256(open(out, "rb").read()).hexdigest() != original_sha:
                    raise ValueError("libjxl's rebuild is not the original")
                res["result"] = "ok"
            elif r["kind"] == "lossless-pq":
                if twin is None:
                    raise ValueError("no .hdr.png twin row")
                if r["pixels_sha256"] != twin["rgb16_sha256"]:
                    raise ValueError("render-v4 decode hash differs from the .hdr.png twin")
                out = os.path.join(tmp, "d.ppm")
                subprocess.run(["djxl", path, out, "--bits_per_sample=16", "--quiet"], capture_output=True, check=True)
                ch, px = pnm(open(out, "rb").read())
                if ch != 3 or hashlib.sha256(px.astype("<u2").tobytes()).hexdigest() != twin["rgb16_sha256"]:
                    raise ValueError("libjxl decodes different 16-bit samples")
                if "P3 primaries, PQ transfer function" not in colour_line:
                    raise ValueError(f"colour statement: {colour_line}")
                res["result"] = "ok"
            elif r["kind"] == "jpeg-in-jxl-codestream":
                subprocess.run(["djxl", path, os.path.join(tmp, "d.ppm"), "--quiet"], capture_output=True, check=True)
                res["result"] = "ok (decodes; no rebuild data by design)"
            else:
                raise ValueError(f"unknown kind {r['kind']}")
        res["colour"] = colour_line.removeprefix("Color space: ")
        res["error"] = ""
    except Exception as e:  # recorded: the row fails
        res["result"] = "FAIL"
        res["error"] = f"{type(e).__name__}: {e}"[:300]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--ids")
    a = ap.parse_args()
    keep = set(a.ids.split(",")) if a.ids else None
    twins = {(r["id"], r["layer"]): r for r in csv.DictReader(open(os.path.join(a.out_dir, "report.tsv")), delimiter="\t")
             if not r["error"]}
    original = {}
    for line in open(os.path.join(a.out_dir, "list.tsv")):
        f = line.rstrip("\n").split("\t")
        original[f[0]] = json.loads(f[3])["original_sha256"]
    hdr_report = os.path.join(a.out_dir, "hdr-report.tsv")
    if os.path.exists(hdr_report):
        for r in csv.DictReader(open(hdr_report), delimiter="\t"):
            if not r["error"]:
                twins[(r["id"], "png-p3-hdr")] = r
    rows = []
    for name in ("jxl-report.tsv", "jxl-hdr-report.tsv"):
        p = os.path.join(a.out_dir, name)
        if os.path.exists(p):
            rows += list(csv.DictReader(open(p), delimiter="\t"))
    jobs = []
    for r in rows:
        if keep and r["id"] not in keep:
            continue
        if r["error"]:
            jobs.append(None)
            print(f"FAIL {r['id']}: render-v4 error {r['error']}")
            continue
        twin = twins.get((r["id"], r["layer"].replace("jxl-", "png-")))
        jobs.append((a.out_dir, r, twin, original[r["id"]]))
    cols = ["id", "layer", "kind", "path", "result", "colour", "error"]
    failed = sum(1 for j in jobs if j is None)
    with ProcessPoolExecutor(a.jobs) as ex, open(os.path.join(a.out_dir, "jxl-check.tsv"), "w") as out:
        out.write("\t".join(cols) + "\n")
        for res in ex.map(check, [j for j in jobs if j is not None], chunksize=4):
            out.write("\t".join(str(res.get(c, "")) for c in cols) + "\n")
            if res["result"] == "FAIL":
                failed += 1
                print("FAIL", res["id"], res["layer"], res["error"], flush=True)
    print(f"{len(jobs) - failed} of {len(jobs)} JXL files pass; {failed} fail")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
