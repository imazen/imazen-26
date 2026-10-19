#!/usr/bin/env python3
"""Third-party read-back gate for the render v4 PNG layers (EXPORT-PLAN.md, "Gates").

    render_v4_readback.py <out-dir> [--jobs 8] [--ids 11044,13005]

Reads <out-dir>/report.tsv (png-sdr) and, when present, <out-dir>/hdr-report.tsv (png-hdr),
and checks every written file:

- chunks: exactly the plan's signalling plus one provenance `tEXt` (keyword `imazen-26`):
  `sRGB` for sRGB files; `iCCP` + `cICP` 12/13/0/1 for Display P3; `iCCP` alone for Adobe
  RGB; `cICP` 12/16/0/1 + `cLLI` (the reported MaxCLL/MaxFALL) for the HDR renders; `PLTE`
  and `tRNS` allowed with a palette; nothing else;
- libpng's `pngfix` finds no error;
- Pillow (its own decoder), ImageMagick (libpng) and netpbm's `pngtopnm` (libpng) decode the
  pixels render-v4 recorded: RGBA8 against `rgba_sha256`, 16-bit RGB against `rgb16_sha256`
  (Pillow reads 16-bit RGB as 8-bit, so it only opens and verifies those).

Writes <out-dir>/readback.tsv and exits 1 on any failure.
"""
import argparse
import csv
import hashlib
import os
import struct
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
from PIL import Image

KEYWORD = b"imazen-26"


def chunk_list(data):
    pos, out = 8, []
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG signature")
    while pos < len(data):
        n, t = struct.unpack(">I4s", data[pos:pos + 8])
        out.append((t.decode("latin-1"), data[pos + 8:pos + 8 + n]))
        pos += 12 + n
    return out


def check_chunks(data, row, hdr):
    chunks = chunk_list(data)
    types = [t for t, _ in chunks]
    if hdr:
        need = {"cICP", "cLLI"}
    elif row["layer"] == "png-srgb" or row["colour"] in ("srgb", "assumed-srgb"):
        need = {"sRGB"}
    elif row["colour"] == "display-p3":
        need = {"iCCP", "cICP"}
    elif row["colour"] == "adobe-rgb":
        need = {"iCCP"}
    else:
        return f"unexpected colour {row['colour']}"
    allowed = need | {"IHDR", "PLTE", "tRNS", "tEXt", "IDAT", "IEND"}
    extra = sorted(set(types) - allowed)
    if extra:
        return f"unexpected chunks {extra}"
    missing = sorted(need - set(types))
    if missing:
        return f"missing chunks {missing}"
    texts = [body for t, body in chunks if t == "tEXt"]
    if len(texts) != 1 or not texts[0].startswith(KEYWORD + b"\0"):
        return "provenance tEXt missing or not alone"
    if types[0] != "IHDR" or types[-1] != "IEND":
        return "IHDR/IEND misplaced"
    cicp = next((body for t, body in chunks if t == "cICP"), None)
    if cicp is not None and cicp != (bytes([12, 16, 0, 1]) if hdr else bytes([12, 13, 0, 1])):
        return f"cICP {list(cicp)}"
    if hdr:
        clli = next(body for t, body in chunks if t == "cLLI")
        got = struct.unpack(">II", clli)
        want = (round(float(row["max_cll"]) * 10000), round(float(row["max_fall"]) * 10000))
        if any(abs(a - b) > 1 for a, b in zip(got, want)):
            return f"cLLI {got} vs report {want}"
    return ""


def pnm(data):
    """Parse netpbm P4/P5/P6 output: (channels, maxval, samples). P4 (1-bit PBM, 1 = black)
    comes back as 8-bit grey 0/255."""
    fields, pos = [], 0
    while len(fields) < (3 if data[:2] == b"P4" else 4):
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos)
            continue
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end
    pos += 1
    if fields[0] == b"P4":
        w, h = int(fields[1]), int(fields[2])
        row = (w + 7) // 8
        bits = np.unpackbits(np.frombuffer(data[pos:pos + row * h], np.uint8).reshape(h, row), axis=1)[:, :w]
        return 1, 255, ((1 - bits) * 255).astype(np.uint8).reshape(h, w, 1)
    magic, w, h, maxval = fields[0], int(fields[1]), int(fields[2]), int(fields[3])
    ch = {b"P5": 1, b"P6": 3}[magic]
    dtype = ">u2" if maxval > 255 else "u1"
    return ch, maxval, np.frombuffer(data[pos:], dtype)[: w * h * ch].reshape(h, w, ch)


def check_file(job):
    out_dir, row, hdr = job
    path = os.path.join(out_dir, row["path"])
    res = {"id": row["id"], "layer": row["layer"], "path": row["path"]}
    try:
        data = open(path, "rb").read()
        res["chunks"] = check_chunks(data, row, hdr) or "ok"
        fix = subprocess.run(["pngfix", "--quiet", path], capture_output=True)
        res["pngfix"] = "ok" if fix.returncode == 0 else f"rc {fix.returncode} {fix.stderr[:120]!r}"
        want = row["rgb16_sha256"] if hdr else row["rgba_sha256"]
        with Image.open(path) as im:
            if hdr:
                im.verify()
                res["pillow"] = "opened (16-bit RGB not compared)"
            else:
                res["pillow"] = "ok" if hashlib.sha256(im.convert("RGBA").tobytes()).hexdigest() == want \
                    else "PIXELS DIFFER"
        if hdr:
            raw = subprocess.run(["magick", path, "-depth", "16", "-endian", "LSB", "rgb:-"], capture_output=True,
                                 check=True).stdout
        else:
            raw = subprocess.run(["magick", path, "-depth", "8", "rgba:-"], capture_output=True, check=True).stdout
        res["magick"] = "ok" if hashlib.sha256(raw).hexdigest() == want else "PIXELS DIFFER"
        ch, maxval, px = pnm(subprocess.run(["pngtopnm", path], capture_output=True, check=True).stdout)
        if hdr:
            if ch != 3 or maxval != 65535:
                res["pngtopnm"] = f"format {ch}ch maxval {maxval}"
            else:
                got = hashlib.sha256(px.astype("<u2").tobytes()).hexdigest()
                res["pngtopnm"] = "ok" if got == want else "PIXELS DIFFER"
        else:
            if maxval != 255:
                px = (px.astype(np.float64) * 255 / maxval).round().astype(np.uint8)
            rgb = np.repeat(px, 3, axis=2) if ch == 1 else px
            alpha = np.full(rgb.shape[:2] + (1,), 255, np.uint8)
            if row["layout"] == "rgba8":
                _, _, a = pnm(subprocess.run(["pngtopnm", "-alpha", path], capture_output=True, check=True).stdout)
                alpha = a.astype(np.uint8)
            got = hashlib.sha256(np.concatenate([rgb.astype(np.uint8), alpha], axis=2).tobytes()).hexdigest()
            res["pngtopnm"] = "ok" if got == want else "PIXELS DIFFER"
        res["error"] = ""
    except Exception as e:  # recorded, never swallowed: the row fails
        res["error"] = f"{type(e).__name__}: {e}"[:300]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--ids")
    ap.add_argument("--resume", action="store_true", help="reuse successful rows after checking each source hash")
    a = ap.parse_args()
    keep = set(a.ids.split(",")) if a.ids else None
    jobs = []
    for name, hdr in (("report.tsv", False), ("hdr-report.tsv", True)):
        p = os.path.join(a.out_dir, name)
        if not os.path.exists(p):
            if not hdr:
                raise SystemExit(f"no {p}")
            continue
        for r in csv.DictReader(open(p), delimiter="\t"):
            if r["error"] or (keep and r["id"] not in keep):
                continue
            jobs.append((a.out_dir, r, hdr))
    cols = ["id", "layer", "path", "chunks", "pngfix", "pillow", "magick", "pngtopnm", "error"]
    destination = os.path.join(a.out_dir, "readback.tsv")
    prior = {}
    if a.resume:
        with open(destination) as previous:
            for row in csv.DictReader(previous, delimiter="\t"):
                key = (row["id"], row["layer"], row["path"])
                if key in prior:
                    raise SystemExit("duplicate previous readback row")
                if not row["error"] and all(row[c].startswith(("ok", "opened")) for c in cols[3:8]):
                    prior[key] = row
        backup = destination + ".before-resume"
        if os.path.exists(backup):
            raise SystemExit(f"refusing to overwrite {backup}")
        os.rename(destination, backup)
    pending, reused = [], []
    for job in jobs:
        _, row, _ = job
        key = (row["id"], row["layer"], row["path"])
        if key in prior:
            with open(os.path.join(a.out_dir, row["path"]), "rb") as source:
                if hashlib.sha256(source.read()).hexdigest() != row["sha256"]:
                    raise SystemExit("source hash changed before readback reuse")
            reused.append(prior[key])
        else:
            pending.append(job)
    failed = 0
    with ProcessPoolExecutor(a.jobs) as ex, open(destination, "x") as out:
        out.write("\t".join(cols) + "\n")
        for res in reused:
            out.write("\t".join(str(res.get(c, "")) for c in cols) + "\n")
        out.flush()
        print(f"readback: {len(reused)}/{len(jobs)} reused after source hash checks", flush=True)
        futures = [ex.submit(check_file, job) for job in pending]
        for index, future in enumerate(as_completed(futures), 1):
            res = future.result()
            bad = res["error"] or any(not res.get(c, "").startswith(("ok", "opened")) for c in cols[3:8])
            failed += bool(bad)
            out.write("\t".join(str(res.get(c, "")) for c in cols) + "\n")
            out.flush()
            if index % 25 == 0 or index == len(pending):
                print(f"readback: {index + len(reused)}/{len(jobs)} complete; {failed} failures", flush=True)
            if bad:
                print("FAIL", "\t".join(str(res.get(c, "")) for c in cols), flush=True)
    print(f"{len(jobs) - failed} of {len(jobs)} files pass; {failed} fail")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
