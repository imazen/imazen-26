#!/usr/bin/env python3
"""Check whitelist-v2 outputs against their oldest copies with third-party readers.

Independent of the zen code that wrote and first checked the files:

- exiftool: every tag the output keeps must have the same value in the source (read by
  exiftool's own parsers), the output must carry no tag the source lacks, and
  `-validate` must not report a warning the source doesn't have;
- libjpeg-turbo `djpeg`: JPEG primary images decode to identical pixels;
- libheif `heif-dec --with-aux`: HEIC primary and auxiliary images (gain maps, depth,
  mattes) decode to identical pixels; `heif-info` reports the same structure;
- exiftool `-b`: UltraHDR gain-map images (MPImage2) and Samsung motion-photo video
  extract byte-identically.

Usage: oracle_check.py <sources.tsv> <v2-dir> <out.tsv>
  sources.tsv: id, ext, source_generation, source, canonical (as whitelist_v2.py takes)
Writes one row per file and prints a summary. Needs exiftool, djpeg, heif-dec, heif-info.
"""
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SKIP_GROUPS = ("File", "System", "ExifTool", "Composite", "SourceFile")
# Values that legitimately change when segments move or are rebuilt.
VOLATILE = re.compile(r"^(MPImage\d+:MPImage(Start|Length)|MPF\d*:.*Offset"
                      r"|.*:ThumbnailOffset|.*:ThumbnailLength|QuickTime:.*|Meta:.*Length)")


def prune_empty(v):
    """Drop empty strings and empty structs, so an empty XMP placeholder compares equal."""
    if isinstance(v, dict):
        v = {k: prune_empty(x) for k, x in v.items()}
        return {k: x for k, x in v.items() if x not in ("", {}, [])}
    if isinstance(v, list):
        return [prune_empty(x) for x in v]
    return v


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


def exif_tags(paths):
    """path -> {group:tag -> value} via one exiftool batch (-a keeps duplicates as lists)."""
    out = {}
    res = run(["exiftool", "-j", "-a", "-G1", "-s", "-n", "-struct", "-q", "-q"] + paths)
    for e in json.loads(res.stdout or b"[]"):
        out[e["SourceFile"]] = {k: prune_empty(v) for k, v in e.items()
                                if k != "SourceFile" and not k.startswith(SKIP_GROUPS)
                                and not VOLATILE.match(k)}
    return out


def validate(path):
    res = run(["exiftool", "-validate", "-warning", "-error", "-a", "-G1", "-s", path], text=True)
    return [l.split(":", 1)[1].strip() for l in res.stdout.splitlines()
            if ("Warning" in l or "Error" in l) and "Validate" not in l]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def djpeg_hash(path):
    r = run(["djpeg", "-ppm", path])
    return sha(r.stdout) if r.returncode == 0 and r.stdout else f"djpeg failed: {r.stderr[:80]!r}"


def heif_hashes(path, tmp):
    """Hashes of every image heif-dec writes (primary + auxiliary), keyed by suffix."""
    d = tempfile.mkdtemp(dir=tmp)
    try:
        r = run(["heif-dec", "--quiet", "--with-aux", "--no-colons", path, os.path.join(d, "o.y4m")])
        if r.returncode != 0:
            return {"error": r.stderr.decode(errors="replace")[:80]}
        out = {}
        for f in sorted(glob.glob(os.path.join(d, "*"))):
            out[os.path.basename(f)] = sha(open(f, "rb").read())
        return out
    finally:
        shutil.rmtree(d, ignore_errors=True)


def heif_info(path):
    r = run(["heif-info", path], text=True)
    # The Exif item shrinks by design; everything else must match.
    return "\n".join(l for l in r.stdout.splitlines()
                     if not l.startswith(("MIME type", "main brand", "compatible"))
                     and not re.match(r"\s*Exif: \d+ bytes", l))


def extract(path, tag):
    r = run(["exiftool", "-b", f"-{tag}", path])
    return sha(r.stdout) if r.stdout else "-"


def main():
    src_tsv, v2dir, out_tsv = sys.argv[1:4]
    man = {r["id"]: r for r in csv.DictReader(open(os.path.join(v2dir, "manifest.tsv")), delimiter="\t")}
    rows = [r for r in csv.DictReader(open(src_tsv), delimiter="\t")
            if r["ext"] != ".dng" and r["id"] in man and man[r["id"]]["status"] == "ok"]
    pairs = [(r["id"], r["ext"], r["source"], os.path.join(v2dir, man[r["id"]]["output"])) for r in rows]
    tags = exif_tags([p for _, _, s, v in pairs for p in (s, v)])
    tmp = os.path.expanduser("~/tmp/oracle-scratch")
    os.makedirs(tmp, exist_ok=True)
    w = csv.writer(open(out_tsv, "w"), delimiter="\t", lineterminator="\n")
    w.writerow(["id", "ext", "tags_kept", "tag_value_mismatches", "tags_added", "new_warnings",
                "pixels", "structure", "gainmap_or_video", "detail"])
    bad = 0
    for i, ext, s, v in pairs:
        ts, tv = tags.get(s, {}), tags.get(v, {})
        mism = [k for k in tv if k in ts and ts[k] != tv[k]]
        added = [k for k in tv if k not in ts]
        vs, vv = validate(s), validate(v)
        new_warn = [m for m in vv if m not in vs]
        detail = []
        if ext == ".jpg":
            px = "same" if djpeg_hash(s) == djpeg_hash(v) else "DIFFER"
            struct_ = "-"
            gm_s = extract(s, "MPImage2")
            gm_s = gm_s if gm_s != "-" else extract(s, "PreviewImage")
            gm_v = extract(v, "MPImage2")
            gm_v = gm_v if gm_v != "-" else extract(v, "PreviewImage")
            thumbs = "GoPro" in ts.get("IFD0:Make", "")
            gm = "same" if gm_s == gm_v else ("dropped (thumbnail)" if thumbs and gm_v == "-" else "DIFFER")
            if gm_s == "-" and gm_v == "-":
                gm = "-"
        elif ext == ".heic":
            hs, hv = heif_hashes(s, tmp), heif_hashes(v, tmp)
            px = "same" if hs == hv and "error" not in hs else f"DIFFER {sorted(set(hs) ^ set(hv))[:3]}"
            struct_ = "same" if heif_info(s) == heif_info(v) else "DIFFER"
            mv_s, mv_v = extract(s, "MotionPhotoVideo"), extract(v, "MotionPhotoVideo")
            gm = "-" if mv_s == mv_v == "-" else ("same" if mv_s == mv_v else "DIFFER")
        else:
            px, struct_, gm = "-", "-", "-"
        if mism:
            detail.append("mismatch " + ", ".join(mism[:4]))
        if added:
            detail.append("added " + ", ".join(added[:4]))
        if new_warn:
            detail.append("warn " + "; ".join(new_warn[:2]))
        ok = not mism and not added and not new_warn and "DIFFER" not in (px + struct_ + gm)
        bad += not ok
        w.writerow([i, ext, len(tv), len(mism), len(added), len(new_warn), px, struct_, gm, " | ".join(detail)])
    print(f"{len(pairs)} files checked, {bad} with a finding")


if __name__ == "__main__":
    main()
