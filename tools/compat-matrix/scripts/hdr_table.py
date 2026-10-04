#!/usr/bin/env python3
"""HDR gain-map table (round-2): per reader × gain-map fixture —

  detects   reader's own info output reports the gain map
            (ultrahdr_app decode metadata, avifdec --info, jxlinfo -v,
            heif-info), or "n/a" with reason
  hdr_out   reader can emit an HDR rendition (vs SDR-only)
  dlog2     mean |Δlog2| linear light vs the zen reconstruction
            (`probe --hdr` PFM, full reconstruction boost)

The zen PFM row is the reference. Readers with no gain-map semantics at
all are recorded once per fixture as n/a with a reason rather than run.

Usage: hdr_table.py <fixtures_dir> <out.tsv> [--image lts|latest]
"""

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

CM_BIN = os.environ.get("CM_BIN", "compat-matrix")
IMG = {"lts": "imazen26-compat:lts", "latest": "imazen26-compat:latest"}


_CTRTMP = []


def _ctrtmp():
    # L-a: disk-backed container /tmp under ~/tmp (no tmpfs). One dir per
    # process; TemporaryDirectory cleanup at exit.
    if not _CTRTMP:
        root = Path(os.environ.get("CM_TMPDIR", os.path.expanduser("~/tmp")))
        root.mkdir(parents=True, exist_ok=True)
        _CTRTMP.append(tempfile.TemporaryDirectory(dir=root, prefix=".ctrtmp-"))
    return _CTRTMP[0].name


def docker(image, cmd, fixtures, work=None, timeout=90, ctrtmp=None):
    # r12 L-6: decode work inside the container runs niced like every
    # other site — /usr/bin/nice is the entrypoint, bash -lc the payload.
    args = [
        "docker", "run", "--rm", "--entrypoint", "/usr/bin/nice",
        "--network", "none", "--read-only",
        "-v", f"{ctrtmp or _ctrtmp()}:/tmp",
        "-e", "HOME=/tmp",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--cpus", "4", "--memory", "8g", "--pids-limit", "1024",
        "-v", f"{fixtures}:/f:ro",
    ]
    if work:
        args += ["-v", f"{work}:/w"]
    args += [image, "-n", "19", "bash", "-lc",
             "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; " + cmd]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def ppm16(path):
    """P6 PPM (<=16-bit, big-endian) -> float64 h×w×3 in 0..1."""
    with open(path, "rb") as f:
        assert f.readline().strip() == b"P6"
        w, h = map(int, f.readline().split())
        maxv = int(f.readline())
        a = np.fromfile(f, dtype=">u2" if maxv > 255 else "u1").reshape(h, w, 3)
    return a.astype(np.float64) / maxv


def pq_to_linear(e_prime):
    """ST 2084 inverse EOTF -> linear light relative to 203-nit SDR white."""
    m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
    ep = np.clip(e_prime, 0.0, 1.0)
    n = np.clip(ep ** (1 / m2) - c1, 0.0, None) / (c2 - c3 * ep ** (1 / m2))
    return n ** (1 / m1) * (10000.0 / 203.0)


def read_pfm(path):
    with open(path, "rb") as f:
        magic = f.readline().strip()
        w, h = map(int, f.readline().split())
        scale = float(f.readline())
        ch = 3 if magic == b"PF" else 1
        a = np.fromfile(f, dtype="<f4").reshape(h, w, ch)
    return a[::-1] if scale < 0 else a


def dlog2_stats(a, b):
    """Return (mean, p95, edge_mean, flat_mean) of |Δlog2| per-channel-or-luma.
    Edge/flat split by gradient magnitude of the zen reference luma — the
    gain-map upsampling disagreement concentrates at edges."""
    eps = 1e-6
    if a.shape != b.shape:
        return (float("inf"),) * 4
    d = np.abs(
        np.log2(np.clip(a[..., :3], eps, None)) - np.log2(np.clip(b[..., :3], eps, None))
    )
    lum = b[..., :3].mean(2)
    gy, gx = np.gradient(lum)
    edge = np.hypot(gy, gx) >= 0.02
    dm = d.mean(2)
    flat_m = float(dm[~edge].mean()) if (~edge).any() else float("nan")
    edge_m = float(dm[edge].mean()) if edge.any() else float("nan")
    return float(d.mean()), float(np.percentile(d, 95)), edge_m, flat_m


def fixtures_with_gainmap(fixtures_dir):
    out = []
    with open(Path(fixtures_dir) / "fixtures.tsv") as f:
        hdr = f.readline().rstrip("\n").split("\t")
        for line in f:
            r = dict(zip(hdr, line.rstrip("\n").split("\t")))
            if r.get("gainmap") not in ("", "none", None):
                out.append(r)
    return out


def zen_pfm(fixtures_dir, row, tmp):
    src = Path(fixtures_dir) / row["file"]
    pfm = Path(tmp) / f"{row['fixture']}.pfm"
    r = subprocess.run(
        [CM_BIN, "probe", str(src), "/dev/null", "--raw", "--hdr", str(pfm)],
        capture_output=True, text=True,
    )
    return pfm if pfm.exists() else None


def detect_row(fixture, reader, detects, hdr_out, d2, note):
    return f"{fixture}\t{reader}\t{detects}\t{hdr_out}\t{d2}\t{note}"


def main():
    fixtures_dir = Path(sys.argv[1])
    out_tsv = Path(sys.argv[2])
    image = IMG["latest" if "--image" in sys.argv and sys.argv[sys.argv.index("--image") + 1] == "latest" else "lts"]

    rows = []
    # Per-run scratch lives under ~/tmp (fresh TemporaryDirectory per
    # invocation — nothing stale can be picked up). CM_TMPDIR overrides.
    work_root = Path(os.environ.get("CM_TMPDIR", os.path.expanduser("~/tmp")))
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_root, prefix=".hdr-") as tmp:
        for r in fixtures_with_gainmap(fixtures_dir):
            fx, fpath = r["fixture"], r["file"]
            base = Path(fpath).name
            ext = Path(fpath).suffix.lower()
            pfm = zen_pfm(fixtures_dir, r, tmp)
            zen_ref = read_pfm(pfm) if pfm else None

            rows.append(detect_row(
                fx, "zen-reader",
                "yes" if pfm else "no",
                "yes" if pfm else "n/a",
                "0.000" if pfm else "n/a",
                f"reference reconstruction{'' if pfm else ' (unavailable)'}"))

            # ---- ultrahdr_app (JPEG only)
            if ext in (".jpg", ".jpeg"):
                # per-fixture dir: reusing uhd/ would let a failed decode
                # leave the PREVIOUS fixture's out.raw/meta.cfg behind and
                # silently score the wrong file (round-7 finding).
                w = Path(tmp) / f"uhd-{fx}"
                w.mkdir(exist_ok=True)
                rc, out = docker(
                    image,
                    f"ultrahdr_app -m 1 -j /f/{fpath} -o 0 -O 4 -z /w/uhd-{fx}/out.raw -f /w/uhd-{fx}/meta.cfg",
                    fixtures_dir, tmp)
                raw = w / "out.raw"
                meta = w / "meta.cfg"
                # Detection = the cfg contains serialized gain-map params
                # (ContentBoost fields), not merely that a file exists.
                det = ("yes" if meta.exists()
                       and b"ContentBoost" in meta.read_bytes() else "no")
                # stored dims come from fixtures.tsv; both sides are stored
                # orientation + base gamut now. Refuse to reshape on a size
                # mismatch — a silent reshape scrambles pixels and was the
                # source of the bogus 2.289 on the rotated rep.
                fw, fh = int(r["w"]), int(r["h"])
                expect = fw * fh * 4 * 2  # rgba f16
                if raw.exists() and raw.stat().st_size != expect:
                    rows.append(detect_row(fx, "ultrahdr_app", det, "yes(linear f16)",
                                           "n/a", f"raw size {raw.stat().st_size} != {expect} ({fw}x{fh})"))
                elif raw.exists() and zen_ref is not None:
                    if zen_ref.shape[:2] != (fh, fw):
                        rows.append(detect_row(fx, "ultrahdr_app", det, "yes(linear f16)",
                                               "n/a", f"zen dims {zen_ref.shape[:2]} != stored {fh}x{fw}"))
                    else:
                        a = np.fromfile(raw, dtype="<f2").reshape(fh, fw, 4)[..., :3].astype(np.float32)
                        m, p95, em, fm = dlog2_stats(a, zen_ref)
                        rows.append(detect_row(fx, "ultrahdr_app", det, "yes(linear f16)",
                                               f"{m:.3f}", f"p95 {p95:.3f}; edge {em:.3f} flat {fm:.3f}; linear f16 via -o 0 -O 4"))
                elif raw.exists():
                    rows.append(detect_row(fx, "ultrahdr_app", det, "yes(linear f16)", "n/a", "no zen ref"))
                else:
                    err = out.strip().splitlines()[-1][:80] if out.strip() else f"rc={rc}"
                    rows.append(detect_row(fx, "ultrahdr_app", det, "no", "n/a", err))
            else:
                rows.append(detect_row(fx, "ultrahdr_app", "n/a", "n/a", "n/a", "JPEG-only tool"))

            # ---- avifdec --info (AVIF)
            if ext == ".avif":
                rc, out = docker(image, f"avifdec --info /f/{fpath}", fixtures_dir)
                m = re.search(r"Gain map\s*:\s*(\w+)", out)
                det = m.group(1).lower() if m else "field-absent"
                rows.append(detect_row(fx, "avifdec", det, "no", "n/a", "info output; SDR-only decode"))
                # avifgainmaputil printmetadata = detection oracle
                rc, out = docker(image, f"command -v avifgainmaputil >/dev/null && avifgainmaputil printmetadata /f/{fpath} 2>&1 | head -12 || echo NOT_INSTALLED", fixtures_dir)
                low = out.lower()
                gmutil = None
                if "not_installed" in low:
                    rows.append(detect_row(fx, "avifgainmaputil", "n/a", "n/a", "n/a", "not installed"))
                elif "does not contain a gain map" in low or "no gain" in low:
                    rows.append(detect_row(fx, "avifgainmaputil", "no", "no", "n/a", "printmetadata: gain map not recognized"))
                elif "gain" in low:
                    gmutil = "yes"
                    rows.append(detect_row(fx, "avifgainmaputil", "yes", "no", "n/a", "printmetadata; no HDR apply"))
                else:
                    rows.append(detect_row(fx, "avifgainmaputil", "n/a", "n/a", "n/a", out.strip()[:80]))

                # avifgainmaputil tonemap = HDR rendition vs zen. Route via a
                # 10-bit PQ AVIF intermediate (its PNG writer is 8-bit) ->
                # avifdec -> 16-bit PNG -> pngtopam -> P6 PPM; invert ST2084
                # relative to 203-nit SDR white. Stored orientation + base
                # primaries, same convention as zen's --hdr PFM.
                if gmutil:
                    hm = re.search(r"Alternate headroom:\s*([0-9.eE+-]+)", out)
                    w = Path(tmp) / f"gm-{fx}"
                    w.mkdir(exist_ok=True)
                    if not hm:
                        rows.append(detect_row(fx, "avifgainmaputil-tonemap", gmutil, "no",
                                               "n/a", "no alternate headroom parsed"))
                    else:
                        alt = hm.group(1)
                        docker(image, f"avifgainmaputil tonemap /f/{fpath} /w/gm-{fx}/tm.avif --headroom {alt} -d 10 && "
                                      f"avifdec /w/gm-{fx}/tm.avif /w/gm-{fx}/tm.png && "
                                      f"pngtopam /w/gm-{fx}/tm.png > /w/gm-{fx}/tm.ppm",
                               fixtures_dir, Path(tmp), timeout=180)
                        ppm = w / "tm.ppm"
                        if not ppm.exists():
                            rows.append(detect_row(fx, "avifgainmaputil-tonemap", gmutil, "no",
                                                   "n/a", "tonemap/convert chain failed"))
                        elif zen_ref is None:
                            rows.append(detect_row(fx, "avifgainmaputil-tonemap", gmutil,
                                                   "yes(10b PQ)", "n/a", "no zen ref"))
                        else:
                            a = pq_to_linear(ppm16(ppm))
                            if a.shape != zen_ref.shape:
                                rows.append(detect_row(fx, "avifgainmaputil-tonemap", gmutil,
                                                       "yes(10b PQ)", "n/a",
                                                       f"dims {a.shape[:2]} != zen {zen_ref.shape[:2]}"))
                            else:
                                m, p95, em, fm = dlog2_stats(a, zen_ref)
                                rows.append(detect_row(fx, "avifgainmaputil-tonemap", gmutil,
                                                       "yes(10b PQ)", f"{m:.3f}",
                                                       f"p95 {p95:.3f}; edge {em:.3f} flat {fm:.3f}; tonemap --headroom {alt} -> PQ/203"))
            else:
                rows.append(detect_row(fx, "avifdec", "n/a", "n/a", "n/a", "AVIF-only tool"))

            # ---- jxlinfo / djxl (JXL)
            if ext == ".jxl":
                rc, out = docker(image, f"jxlinfo -v /f/{fpath} 2>&1 | grep -iA1 jhgm", fixtures_dir)
                det = "yes" if "jhgm" in out.lower() else "no"
                lvl = "parsed" if "gain map" in out.lower() else "box-only"
                rows.append(detect_row(fx, "jxlinfo", f"{det} ({lvl})", "n/a", "n/a", "info only"))
                rc, out = docker(image, f"djxl /f/{fpath} /w/j-{fx}.ppm 2>&1 | tail -2", fixtures_dir, Path(tmp))
                ppm_ok = (Path(tmp) / f"j-{fx}.ppm").exists()
                rows.append(detect_row(
                    fx, "djxl", "n/a", "no" if ppm_ok else "fail", "n/a",
                    "decodes base; no gain-map apply"
                    if ppm_ok else "decode failed: " + out.strip()[-120:]))
            else:
                rows.append(detect_row(fx, "jxlinfo", "n/a", "n/a", "n/a", "JXL-only tool"))

            # ---- heif-info (HEIC corpus reps carry tmap items)
            if ext in (".heic", ".heif"):
                rc, out = docker(image, f"heif-info /f/{fpath} 2>&1 | grep -icE 'tmap|gain ?map|aux.*hdr'", fixtures_dir)
                det = "yes" if out.strip() not in ("0", "") else "no"
                rows.append(detect_row(fx, "heif-info", det, "no", "n/a", "info output"))
                rc, out = docker(image, f"heif-convert /f/{fpath} /w/h-{fx}.png >/dev/null 2>&1", fixtures_dir, Path(tmp))
                ppm_ok = (Path(tmp) / f"h-{fx}.png").exists()
                rows.append(detect_row(
                    fx, "heif-dec", "n/a", "no" if ppm_ok else "fail", "n/a",
                    "SDR-only decode" if ppm_ok
                    else "decode failed — no SDR rendition to judge"))
            else:
                rows.append(detect_row(fx, "heif-info", "n/a", "n/a", "n/a", "HEIC-only tool"))

            # ---- readers with no gain-map semantics
            for rdr, reason in [
                ("djpeg", "JPEG base only"),
                ("ffmpeg", "may expose MPF secondary as stream; no gain-map apply"),
                ("vips", "SDR decode"),
                ("imagemagick", "SDR decode"),
                ("pillow", "SDR decode"),
                ("chromium", "HDR apply is display-dependent; SDR headless readback"),
                ("firefox", "SDR readback"),
                ("webkit", "SDR readback"),
            ]:
                rows.append(detect_row(fx, rdr, "n/a", "no", "n/a", reason))

    with open(out_tsv, "w") as f:
        f.write("fixture\treader\tdetects_gainmap\thdr_output\tmean_abs_dlog2_vs_zen\tnote\n")
        f.write("\n".join(rows) + "\n")
    print(f"{len(rows)} rows -> {out_tsv}")


if __name__ == "__main__":
    main()
