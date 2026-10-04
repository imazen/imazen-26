#!/usr/bin/env python3
"""Build the corpus-representatives fixture dir and its hypotheses.

Reads corpus_reps.tsv (origin/id/label/class_size/bytes/path), copies each
file into <reps_dir>/files/, probes it for dims + signalled orientation, and
emits fixtures.tsv + hypotheses.tsv in the standard manifest shape so
run_matrix.sh and managed_hyps.py work unchanged.

Hypotheses per rep (round-2: real-world answer for the tiers):
  stored       — raw stored code values (probe --raw)
  orient-only  — stored + signalled orientation            [when orient != 1]
  colour-only  — stored + lcms2(declared profile -> sRGB)  [when non-sRGB]
  correct      — stored + orientation + colour (as-signalled)

Declared colour: the file's embedded ICC wins (incl. HEIC colr 'prof' on
primary or tiles, via dump-icc); else the label's declared space
(DisplayP3 -> display-p3-v4, AdobeRgb -> adobe-rgb). Bt709/noicc/exifcs*
map to sRGB (identity).

Paths in the tsv are corpus-relative — resolved via env per `origin`:
  corpus          -> $CM_CORPUS_ROOT/<path>
  whitelist-v2    -> $CM_VARIANTS_ROOT/whitelist-v2-2026-09-26/<path>
  camera-original -> $CM_VARIANTS_ROOT/whitelist-v2-2026-09-26/<path>

Usage: CM_CORPUS_ROOT=.. CM_VARIANTS_ROOT=.. corpus_reps.py <reps.tsv> <reps_dir>
Then: managed_hyps.py <reps_dir>; run_matrix.sh <reps_dir> <out>
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CM_BIN = os.environ.get("CM_BIN", "compat-matrix")


def bin_stamp():
    """sha of the probe binary — caches keyed by (file sha, bin sha) can't
    serve results a different binary wrote (round-8 §2#3 stale caches)."""
    p = shutil.which(CM_BIN) or CM_BIN
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:10]
    except OSError:
        return "path"

EXT_CLASS = {
    ".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp",
    ".avif": "avif", ".heic": "heic", ".heif": "heic", ".jxl": "jxl",
    ".dng": "dng", ".tif": "tiff", ".tiff": "tiff",
}


def load_reps(tsv):
    rows = []
    with open(tsv) as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            line = line.rstrip("\n")
            if line:
                rows.append(dict(zip(header, line.split("\t"))))
    return rows


def probe_json(cm, path, out_png, out_json):
    r = subprocess.run(
        [cm, "probe", str(path), str(out_png), "--raw", "--json", str(out_json)],
        capture_output=True, check=False,
    )
    # Loud, not {}: a failed probe that silently becomes w=0/h=0 corrupts the
    # manifest and every downstream rep classification (round-8 §2#18).
    if r.returncode != 0 or not out_json.exists():
        raise RuntimeError(
            f"probe failed for {path}: rc={r.returncode} "
            f"{r.stderr.decode(errors='replace')[:200]}")
    return json.loads(out_json.read_text())


def icc_class(icc_bytes):
    """Classify an embedded ICC by its description tag.

    HDR-ish profile descriptions (PQ/HLG/gain-map previews — the iPhone
    `ip16/17` reps) must fall through to 'embedded': their primaries say
    "p3" but the transfer is PQ, so rendering them through the plain P3
    reference profile would make "apply the wrong profile" the `correct`
    hypothesis. 'embedded' applies the file's actual profile instead.
    """
    if not icc_bytes:
        return None
    import io
    from PIL import ImageCms
    try:
        p = ImageCms.getOpenProfile(io.BytesIO(icc_bytes))
        d = (ImageCms.getProfileDescription(p) or "").lower().replace(" ", "")
    except Exception:
        return "embedded"
    if re.search(r"pq|hlg|2084|gainmap|hdr", d):
        return "embedded"
    if "p3" in d:
        return "p3"
    if "adobe" in d:
        return "adobe"
    if "srgb" in d:
        return "srgb"
    return "embedded"  # non-sRGB, unrecognized — apply embedded anyway


def declared_colour(label, embedded_icc_bytes=None):
    """Declared colour space: the file's embedded ICC wins (incl. HEIC
    colr 'prof' on primary or tiles), else the label's declared space."""
    if embedded_icc_bytes:
        return icc_class(embedded_icc_bytes) or "srgb"
    if "DisplayP3" in label:
        return "p3"
    if "AdobeRgb" in label:
        return "adobe"
    return "srgb"  # Bt709, exifcs1, exifcs65535, noicc -> sRGB-ish


def cls_of(label):
    if "gainmap" in label or "ultrahdr" in label or "tmap" in label:
        return "gainmap"
    if "orient6" in label or "orient3" in label:
        return "orientation"
    if "DisplayP3" in label or "AdobeRgb" in label or "colr" in label:
        return "colour"
    return "other"


def main():
    reps_tsv, reps_dir = sys.argv[1], Path(sys.argv[2])
    files_dir = reps_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = reps_dir / "probe"
    probe_dir.mkdir(exist_ok=True)

    rows = load_reps(reps_tsv)
    fx_lines = ["fixture\tclass\tfile\tw\th\texpect_orient\tcolour\tgainmap\tsha256\tsignal_desc"]
    hy_lines = ["fixture\thypothesis\tspec\tcorrect"]

    stamp = bin_stamp()

    seen_dst = {}
    corpus_root = os.environ.get("CM_CORPUS_ROOT", "")
    variants_root = os.environ.get("CM_VARIANTS_ROOT", "")
    for r in rows:
        # tsv `path` is corpus-relative, resolved by `origin`.
        p = r["path"]
        if os.path.isabs(p):
            raise SystemExit(f"{r.get('label')}: absolute path in tsv ({p}) — "
                             "store corpus-relative and export CM_CORPUS_ROOT")
        if r["origin"] == "corpus":
            src = Path(corpus_root) / p
        else:
            src = Path(variants_root) / "whitelist-v2-2026-09-26" / p
        if not src.exists():
            raise SystemExit(f"{r.get('label')}: {src} missing — check "
                             "CM_CORPUS_ROOT / CM_VARIANTS_ROOT")
        label = r["label"]
        # Destination is keyed by the rep LABEL, never the origin basename:
        # the corpus and whitelist-v2 twins share filenames (e.g. 1497) with
        # different bytes — basenames silently aliased the second rep onto
        # the first. Copies (not links) so edits to the origin can't shift
        # the rep under us either.
        dst = files_dir / f"{label}{src.suffix.lower()}"
        if dst.exists():
            src_sha = hashlib.sha256(src.read_bytes()).hexdigest()
            dst_sha = hashlib.sha256(dst.read_bytes()).hexdigest()
            assert src_sha == dst_sha, (
                f"{label}: staged file {dst} does not match origin {src} "
                f"({dst_sha[:12]} != {src_sha[:12]}) — rebuild the reps dir")
        else:
            shutil.copy2(src, dst)
        seen_dst[dst.name] = label
        # corpus_reps.tsv `bytes` is the origin file size — must match.
        want = int(r.get("bytes", "0") or 0)
        if want and dst.stat().st_size != want:
            raise SystemExit(
                f"{label}: size mismatch {dst.stat().st_size} != {want} "
                f"for {src}")
        sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        orient = int(re.search(r"orient(\d)", label).group(1)) if re.search(r"orient(\d)", label) else 1
        ext = src.suffix.lower()
        cls = cls_of(label)
        gainmap = "ultrahdr" if "ultrahdr" in label else ("gainmap" if "gainmap" in label or "tmap" in label else "none")

        # probe/icc caches keyed by (file sha, binary sha): anything older is
        # a stale artifact of different bytes or a different probe build and
        # must not feed the manifest.
        cache_key = f"{label}.{sha[:12]}.{stamp}"
        pjson = probe_dir / f"{cache_key}.json"
        if not pjson.exists():
            for stale in probe_dir.glob(f"{label}.*"):
                stale.unlink()
            pj = probe_json(CM_BIN, dst, probe_dir / f"{cache_key}.png", pjson)
        else:
            pj = json.loads(pjson.read_text())
        w, h = pj.get("w", 0), pj.get("h", 0)
        # File's signalled orientation (EXIF / heic irot) is ground truth;
        # the label's orientN only documents the rep's selection reason.
        orient = int(pj.get("orientation_reported", orient) or orient)

        # embedded ICC (primary colr, else tile colr for HEIC) -> declared colour
        icc_out = reps_dir / "icc" / f"{cache_key}.icc"
        icc_out.parent.mkdir(exist_ok=True)
        if not icc_out.exists():
            for stale in icc_out.parent.glob(f"{label}.*"):
                stale.unlink()
            dr = subprocess.run([CM_BIN, "dump-icc", str(dst), str(icc_out)],
                                capture_output=True, check=False)
            if dr.returncode != 0:
                raise RuntimeError(f"dump-icc failed for {dst}: "
                                   f"{dr.stderr.decode(errors='replace')[:200]}")
        icc_bytes = icc_out.read_bytes() if icc_out.exists() else b""
        colour = declared_colour(label, icc_bytes or None)

        fx_lines.append(f"{label}\t{cls}\tfiles/{dst.name}\t{w}\t{h}\t{orient}\t{colour}\t{gainmap}\t{sha}\t{r['label']}")
        hy_lines.append(f"{label}\tstored\tcorpus:stored\t0")
        if orient != 1:
            hy_lines.append(f"{label}\torient-only\tcorpus:orient={orient}\t0")
        if colour in ("p3", "adobe", "embedded"):
            hy_lines.append(f"{label}\tcolour-only\tcorpus:color={colour}\t0")
        hy_lines.append(f"{label}\tcorrect\tcorpus:as-signalled\t1")
        print(f"{label}: {ext} {w}x{h} orient={orient} colour={colour} probe-status={pj.get('status','?')}")

    (reps_dir / "fixtures.tsv").write_text("\n".join(fx_lines) + "\n")
    (reps_dir / "hypotheses.tsv").write_text("\n".join(hy_lines) + "\n")
    print(f"wrote {len(rows)} reps -> {reps_dir}")


if __name__ == "__main__":
    main()
