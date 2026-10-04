#!/usr/bin/env python3
"""icc_identity_check.py — independent functional-identity check for embedded
ICC profiles (round-9 H-3: the old version compared the embedded profile
against our own generated reference — tautological).

Two legs, neither trusting the profile generator:

1. Tag-level (exact, primary gate): parse the embedded profile's
   rXYZ/gXYZ/bXYZ/wtpt/TRC tags directly and compare against values computed
   in numpy from the *published* primaries, white point and transfer —
   Bradford-adapted D65->D50 the way a conforming profile stores them.
   A wrong colorant (the historical bXYZ-typo class) fails here exactly.

2. Functional (lcms2 end-to-end bound): a 17^3 RGB grid through
   embedded->sRGB via littlecms2, compared against the numpy-computed map
   (published TRC + primaries -> XYZ -> Bradford D50 -> sRGB). The sRGB
   reference profile comes from lcms2's own builtin (`createProfile("sRGB")`),
   never our files. Loose-but-real thresholds (8-bit endpoints quantize both
   sides; tag-level leg is the precise one).

Usage:
  icc_identity_check.py <fixture> <srgbv4|p3v4|p3v2|adobe>
  icc_identity_check.py --selftest     # negative test: perturbed bXYZ MUST fail
  icc_identity_check.py --profile <icc-file> <ref>   # check a bare profile

Env: CM_BIN = compat-matrix binary (dump-icc); CM_TMPDIR / ~/tmp for scratch.
"""

import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

CM_BIN = os.environ.get("CM_BIN", "compat-matrix")

# ------------------------------------------------------------ numpy ICC ----

BRAD = np.array(
    [[0.8951, 0.2664, -0.1614],
     [-0.7502, 1.7135, 0.0367],
     [0.0389, -0.0685, 1.0296]]
)
W65 = np.array([0.31271 / 0.32902, 1.0, (1 - 0.31271 - 0.32902) / 0.32902])
W50 = np.array([0.3457 / 0.3585, 1.0, (1 - 0.3457 - 0.3585) / 0.3585])


def adapt(src_wp, dst_wp):
    """Bradford chromatic adaptation matrix src_wp -> dst_wp."""
    v = (BRAD @ dst_wp) / (BRAD @ src_wp)
    return np.linalg.inv(BRAD) @ np.diag(v) @ BRAD


A65_50 = adapt(W65, W50)


def prim_matrix(prims_xy, wp=W65):
    """RGB->XYZ matrix from primaries (cols) + white point."""
    cols = []
    for x, y in prims_xy:
        cols.append(np.array([x / y, 1.0, (1 - x - y) / y]))
    M = np.stack(cols, axis=1)
    S = np.linalg.solve(M, wp)
    return M * S[None, :]


def srgb_eotf(v01):
    c = np.asarray(v01, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def gamma_eotf(g):
    return lambda v: np.asarray(v, dtype=np.float64) ** g


def srgb_oetf(lin):
    c = np.clip(np.asarray(lin, dtype=np.float64), 0, 1)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)


# Published reference definitions (primaries xy, white, transfer).
REFS = {
    "srgbv4": dict(prims=[(0.64, 0.33), (0.30, 0.60), (0.15, 0.06)],
                   eotf=srgb_eotf),
    "p3v4": dict(prims=[(0.680, 0.320), (0.265, 0.690), (0.150, 0.060)],
                 eotf=srgb_eotf),
    "p3v2": dict(prims=[(0.680, 0.320), (0.265, 0.690), (0.150, 0.060)],
                 eotf=srgb_eotf),
    "adobe": dict(prims=[(0.64, 0.33), (0.21, 0.71), (0.15, 0.06)],
                  eotf=gamma_eotf(2.19921875)),
}
# sRGB primaries as D50-adapted XYZ matrix (what the reference transform
# path inverts through).
SRGB_50 = A65_50 @ prim_matrix(REFS["srgbv4"]["prims"])


# ------------------------------------------------------------ ICC parse ----

def parse_tags(data):
    n = int.from_bytes(data[128:132], "big")
    tags = {}
    for i in range(n):
        o = 132 + 12 * i
        sig = data[o:o + 4].decode("latin1")
        off = int.from_bytes(data[o + 4:o + 8], "big")
        ln = int.from_bytes(data[o + 8:o + 12], "big")
        tags[sig] = data[off:off + ln]
    return tags


def s15f16(b):
    v = int.from_bytes(b, "big", signed=True)
    return v / 65536.0


def xyz_tag(t):
    assert t[:4] == b"XYZ ", t[:4]
    return np.array([s15f16(t[8:12]), s15f16(t[12:16]), s15f16(t[16:20])])


def trc_eval(tag, xs):
    """Evaluate a TRC tag (curvType or parametricCurveType) at xs in [0,1]."""
    ty = tag[:4]
    if ty == b"curv":
        n = int.from_bytes(tag[8:12], "big")
        if n == 0:
            return xs.copy()
        if n == 1:
            # count=1 encodes a pure gamma exponent as u8Fixed8
            g = int.from_bytes(tag[12:14], "big") / 256.0
            return xs ** g
        pts = np.array([int.from_bytes(tag[12 + 2 * i:14 + 2 * i], "big") / 65535.0
                        for i in range(n)])
        return np.interp(xs, np.linspace(0, 1, n), pts)
    if ty == b"para":
        ft = int.from_bytes(tag[8:10], "big")
        p = [s15f16(tag[12 + 4 * i:16 + 4 * i]) for i in range(1 + {0: 0, 1: 2, 2: 3, 3: 4, 4: 7}[ft])]
        g = p[0]
        xs = np.asarray(xs, dtype=np.float64)
        if ft == 0:
            return xs ** g
        a, b = p[1], p[2]
        if ft == 1:
            return np.where(xs >= -b / a, (a * xs + b) ** g, np.zeros_like(xs))
        if ft == 2:
            c = p[3]
            return np.where(xs >= -b / a, (a * xs + b) ** g, np.full_like(xs, c))
        if ft == 3:
            c, d = p[3], p[4]
            return np.where(xs >= d, (a * xs + b) ** g, c * xs)
        if ft == 4:
            c, d, e, f = p[3], p[4], p[5], p[6]
            return np.where(xs >= d, (a * xs + b) ** g + e, c * xs + f)
    raise ValueError(f"unsupported TRC tag type {ty}")


# ------------------------------------------------------------ the check ----

def tag_report(data, ref):
    """Compare embedded tags vs numpy-computed published values.
    Returns (ok, detail)."""
    tags = parse_tags(data)
    want = REFS[ref]
    # expected D50-adapted colorants
    m50 = A65_50 @ prim_matrix(want["prims"])
    errs = []
    got = {}
    for sig, col in (("rXYZ", 0), ("gXYZ", 1), ("bXYZ", 2)):
        if sig not in tags:
            errs.append(f"missing {sig}")
            continue
        got[sig] = xyz_tag(tags[sig])
        d = np.abs(got[sig] - m50[:, col]).max()
        if d > 0.001:
            errs.append(f"{sig} {got[sig].round(5)} vs {m50[:, col].round(5)} (d={d:.5f})")
    if "wtpt" in tags:
        wt = xyz_tag(tags["wtpt"])
        d50 = np.array([0.9642, 1.0, 0.8249])
        if np.abs(wt - d50).max() > 0.001:
            errs.append(f"wtpt {wt.round(5)} != D50")
    # TRCs vs published transfer (sampled, linear-light domain)
    xs = np.linspace(0.02, 1.0, 33)
    exp_t = want["eotf"](xs)
    for sig in ("rTRC", "gTRC", "bTRC"):
        if sig not in tags:
            errs.append(f"missing {sig}")
            continue
        try:
            tv = trc_eval(tags[sig], xs)
        except ValueError as e:
            errs.append(str(e))
            continue
        d = np.abs(tv - exp_t).max()
        if d > 0.01:
            errs.append(f"{sig} max TRC diff {d:.4f}")
    detail = "; ".join(errs) if errs else "tags=ok"
    return (not errs), detail


def xyz_to_lab(xyz, wp=W50):
    """CIE Lab (float, D50 illuminant)."""
    d = np.asarray(xyz, dtype=np.float64) / wp[None, :]
    f = np.where(d > 0.008856, np.cbrt(d), 7.787 * d + 16.0 / 116.0)
    L = 116 * f[:, 1] - 16
    return np.stack([L, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], -1)


def functional_report(icc_bytes, ref):
    """grid -> embedded -> lcms2 output vs numpy published map.

    sRGB: identity into lcms2's builtin sRGB (the review's own method).
    P3/Adobe: grid -> published TRC+primaries -> Bradford D50 -> sRGB
    endpoints (8-bit) AND CIE Lab (D50). RGB thresholds are the review's
    MAD<0.05 / max<=1; Lab8 quantization has a ~0.29 MAD / 1-unit floor
    (a,b are int8) so its thresholds are MAD<0.6 / max<=2 — still caught
    by the negative test which moves bXYZ by +0.05."""
    n = 17
    r, g, b = np.meshgrid(*[np.linspace(0, 255, n, dtype=np.uint8)] * 3,
                          indexing="ij")
    grid = np.stack([r, g, b], -1).reshape(-1, 3).astype(np.uint8)
    im = Image.fromarray(grid.reshape(n, n * n, 3).copy(), "RGB")
    want = REFS[ref]
    src = ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))
    m50 = A65_50 @ prim_matrix(want["prims"])
    lin = want["eotf"](grid.astype(np.float64) / 255.0)
    xyz50 = lin @ m50.T

    # --- RGB endpoint leg (strict: MAD<0.05, max<=1) ---
    if ref.startswith("srgb"):
        exp8 = grid.astype(int)
    else:
        srgb_lin = xyz50 @ np.linalg.inv(SRGB_50).T
        exp8 = np.clip(np.round(srgb_oetf(srgb_lin) * 255), 0, 255).astype(int)
    t = ImageCms.buildTransformFromOpenProfiles(
        src, ImageCms.createProfile("sRGB"), "RGB", "RGB",
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
    out = np.asarray(ImageCms.applyTransform(im, t)).astype(int).reshape(-1, 3)
    d = np.abs(out - exp8)
    mad8, mx8 = float(d.mean()), int(d.max())
    rgb_ok = mad8 < 0.05 and mx8 <= 1

    # --- Lab leg (lcms2 Lab8 vs numpy Lab, quantization-aware) ---
    # PIL LAB mode: L in 0..255 (L*100 -> *255), a/b as SIGNED int8.
    lab_t = ImageCms.buildTransformFromOpenProfiles(
        src, ImageCms.createProfile("LAB"), "RGB", "LAB",
        renderingIntent=ImageCms.Intent.ABSOLUTE_COLORIMETRIC)
    lab8 = np.asarray(ImageCms.applyTransform(im, lab_t)).astype(int).reshape(-1, 3)
    ab = lab8[:, 1:].copy()
    ab[ab >= 128] -= 256
    exp_lab = xyz_to_lab(xyz50)
    exp8lab = np.stack([np.clip(np.round(exp_lab[:, 0] * 255 / 100), 0, 255),
                        np.clip(np.round(exp_lab[:, 1]), -128, 127),
                        np.clip(np.round(exp_lab[:, 2]), -128, 127)], -1)
    got8 = np.stack([lab8[:, 0], ab[:, 0], ab[:, 1]], -1)
    dl = np.abs(got8 - exp8lab)
    madL, mxL = float(dl.mean()), int(dl.max())
    lab_ok = madL < 0.6 and mxL <= 2

    ok = rgb_ok and lab_ok
    return ok, (f"rgb8[mad={mad8:.4f} max={mx8} t:0.05/1] "
                f"lab[mad={madL:.4f} max={mxL} t:0.6/2]")


def check_profile(icc_bytes, ref):
    tag_ok, tag_d = tag_report(icc_bytes, ref)
    fn_ok, fn_d = functional_report(icc_bytes, ref)
    return tag_ok and fn_ok, f"tags[{tag_d}] func[{fn_d}]"


def embedded_icc(fixture):
    tmpbase = Path(os.environ.get("CM_TMPDIR") or (Path.home() / "tmp"))
    tmpbase.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cm-icc-", dir=tmpbase) as td:
        out = Path(td) / "e.icc"
        r = subprocess.run([CM_BIN, "dump-icc", str(fixture), str(out)],
                           capture_output=True)
        if r.returncode != 0 or not out.exists():
            raise SystemExit(f"dump-icc failed on {fixture}")
        return out.read_bytes()


def perturb_bxyz(icc_bytes, delta=0.05):
    """Bump bXYZ X by `delta` — the negative-test corruption."""
    d = bytearray(icc_bytes)
    n = int.from_bytes(d[128:132], "big")
    for i in range(n):
        o = 132 + 12 * i
        if d[o:o + 4] == b"bXYZ":
            off = int.from_bytes(d[o + 4:o + 8], "big")
            x = int.from_bytes(d[off + 8:off + 12], "big", signed=True)
            x += int(delta * 65536)
            d[off + 8:off + 12] = x.to_bytes(4, "big", signed=True)
            return bytes(d)
    raise ValueError("no bXYZ tag")


def selftest():
    """The check must PASS on lcms2's own sRGB and FAIL on a perturbed copy."""
    builtin = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    ok, detail = check_profile(builtin, "srgbv4")
    print(f"selftest positive (lcms2 builtin sRGB): {'PASS' if ok else 'FAIL'} [{detail}]")
    if not ok:
        return 1
    bad = perturb_bxyz(builtin)
    ok2, detail2 = check_profile(bad, "srgbv4")
    print(f"selftest negative (bXYZ+0.05): {'FAIL' if not ok2 else 'PASS(!!)'} [{detail2}]")
    if ok2:
        print("selftest FAIL: perturbed profile accepted", file=sys.stderr)
        return 1
    return 0


def main():
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        sys.exit(selftest())
    if args and args[0] == "--profile":
        icc = Path(args[1]).read_bytes()
        ok, detail = check_profile(icc, args[2])
        print(f"{args[1]} vs {args[2]}: {'PASS' if ok else 'FAIL'} [{detail}]")
        sys.exit(0 if ok else 1)
    fixture, ref = args[0], args[1]
    icc = embedded_icc(fixture)
    if not icc:
        print(f"{Path(fixture).name}: FAIL [no extractable ICC profile]",
              file=sys.stderr)
        sys.exit(1)
    ok, detail = check_profile(icc, ref)
    print(f"{Path(fixture).name} icc vs {ref}: {'PASS' if ok else 'FAIL'} [{detail}]")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
