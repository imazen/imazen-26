#!/usr/bin/env python3
"""Canonical train/validate/test split for imazen-26.

THE RULE (one source of truth, identical to zenmetrics scripts/picker/origin_split.py):
the LAST DIGIT of the 4-digit image id decides the bucket —

    {0,2,4,6,8} -> train      {1,3,5} -> validate      {7,9} -> test

Deterministic, no seed, no clustering. Every derivative of an image (resize, crop,
re-encode, feature row) inherits the image's bucket from these manifests; datasets must
never invent their own split.

Reads CORPUS-MANIFEST.tsv (the membership oracle — rows define the corpus), emits:

    manifests/split_map.tsv                  id -> split, one row per image
    manifests/{train,validate,test}.tsv      full provenance rows + sha256 + public URLs
    splits/{train,validate,test}/<path>      relative symlinks into the class folders

The symlink tree gives a browsable folder view of each bucket without duplicating
bytes. Links resolve wherever the class folders hold the images (a checkout synced
from R2, or the operator's working tree). On checkouts without images the links
dangle harmlessly; the TSVs are the authoritative record either way.

Usage:
    python3 imazen-26/scripts/make_canonical_split.py \
        --repo-im26 imazen-26 [--images-root <dir-with-images>] \
        [--no-sha] [--no-materialize] [--check-urls N]
"""

import argparse
import csv
import hashlib
import os
import sys
import urllib.request

R2_BASE = "https://codec-corpus.r2.imazen.org"
RAW_PREFIX = "imazen-26-unprocessed"
PNGV3_PREFIX = "imazen-26-png-v3"

SPLIT_OF = {0: "train", 2: "train", 4: "train", 6: "train", 8: "train",
            1: "validate", 3: "validate", 5: "validate",
            7: "test", 9: "test"}

OUT_COLS = ["id", "split", "content_class", "path", "width", "height", "format",
            "bytes_manifest", "bytes_actual", "sha256", "raw_url", "png_v3_sdr_url",
            "png_v3_hdr_url"]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def head_status(url: str) -> int:
    # the public domain 403s urllib's default user-agent; any browser/curl UA passes
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "codec-corpus-split-check/1.0 curl/8"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0



# The corpus filename embeds a `_WxH` token from the *stored* dimensions, but the
# PNG-v3 render pass applied EXIF rotation and named its output by the *rotated*
# dimensions. So for every original with EXIF Orientation 5/6/7/8 the render is
# `..._3000x4000.sdr.png` while the corpus file is `..._4000x3000.jpg`, and
# deriving the URL by swapping the extension yields a 404. That mistake shipped
# in 196 of 2,160 rows and went unnoticed for months, because a naive swap looks
# right and fails only on rotated originals.
#
# Render names are therefore NOT derived. They are read from
# variant-sets/png-v3-index.tsv, which records what actually exists on R2
# (measured by probing, regenerate with scripts/build_png_v3_index.py). A row
# whose render is absent gets an EMPTY url — a wrong URL is worse than none.
RENDER_INDEX = "variant-sets/png-v3-index.tsv"


def render_index(repo_root):
    """id -> (sdr_url, hdr_url). Empty string means no such object on R2."""
    path = os.path.join(repo_root, RENDER_INDEX)
    if not os.path.isfile(path):
        raise SystemExit(
            f"{RENDER_INDEX} not found. It is the source of truth for render URLs; "
            "do not fall back to deriving them from the corpus stem."
        )
    out = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            sdr = row["sdr_url"] if row["sdr_present"] == "1" else ""
            out[row["id"]] = (sdr, row["hdr_url"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-im26", default=".",
                    help="the imazen-26 dir to write manifests/ and splits/ into")
    ap.add_argument("--images-root", default=None,
                    help="dir holding the class folders with actual image bytes "
                         "(defaults to --repo-im26)")
    ap.add_argument("--no-sha", action="store_true", help="skip sha256/bytes_actual")
    ap.add_argument("--no-materialize", action="store_true", help="skip symlink tree")
    ap.add_argument("--check-urls", type=int, default=0,
                    help="HEAD-probe N sampled rows' raw + png-v3 URLs")
    args = ap.parse_args()

    im26 = args.repo_im26.rstrip("/")
    images_root = (args.images_root or im26).rstrip("/")
    manifest = os.path.join(im26, "CORPUS-MANIFEST.tsv")

    with open(manifest, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if not rows:
        print(f"ERROR: no rows in {manifest}", file=sys.stderr)
        return 2

    ids = [r["number"] for r in rows]
    if len(set(ids)) != len(ids):
        print("ERROR: duplicate ids in manifest", file=sys.stderr)
        return 2
    bad = [i for i in ids if not (i.isdigit() and len(i) == 4)]
    if bad:
        print(f"ERROR: non-4-digit ids: {bad[:5]}", file=sys.stderr)
        return 2

    render_urls = render_index(im26)

    out_rows = []
    missing = []
    for r in rows:
        rid = r["number"]
        split = SPLIT_OF[int(rid) % 10]
        path = r["path"]
        stem, _ext = os.path.splitext(path)
        disk = os.path.join(images_root, path)
        bytes_actual = ""
        digest = ""
        if not args.no_sha:
            if os.path.isfile(disk):
                bytes_actual = str(os.path.getsize(disk))
                digest = sha256_file(disk)
            else:
                missing.append(path)
        out_rows.append({
            "id": rid, "split": split, "content_class": r["folder"], "path": path,
            "width": r["width"], "height": r["height"], "format": r["format"],
            "bytes_manifest": r["bytes"], "bytes_actual": bytes_actual,
            "sha256": digest,
            "raw_url": f"{R2_BASE}/{RAW_PREFIX}/{path}",
            # NOT f"{stem}.sdr.png" — see render_index() above.
            "png_v3_sdr_url": render_urls.get(rid, ("", ""))[0],
            "png_v3_hdr_url": render_urls.get(rid, ("", ""))[1],
        })

    if missing:
        print(f"ERROR: {len(missing)} manifest rows have no file under "
              f"{images_root} (first: {missing[:3]}) — pass the right --images-root "
              f"or --no-sha", file=sys.stderr)
        return 3

    mdir = os.path.join(im26, "manifests")
    os.makedirs(mdir, exist_ok=True)

    def write_tsv(path, cols, rws):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter="\t",
                               lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            for r in rws:
                w.writerow(r)

    write_tsv(os.path.join(mdir, "split_map.tsv"),
              ["id", "split", "content_class", "path"], out_rows)
    counts = {}
    for s in ("train", "validate", "test"):
        srows = [r for r in out_rows if r["split"] == s]
        counts[s] = len(srows)
        write_tsv(os.path.join(mdir, f"{s}.tsv"), OUT_COLS, srows)

    if not args.no_materialize:
        sdir = os.path.join(im26, "splits")
        for r in out_rows:
            link = os.path.join(sdir, r["split"], r["path"])
            os.makedirs(os.path.dirname(link), exist_ok=True)
            target = os.path.relpath(os.path.join(im26, r["path"]),
                                     os.path.dirname(link))
            if os.path.islink(link) or os.path.exists(link):
                os.remove(link)
            os.symlink(target, link)

    total = sum(counts.values())
    print(f"split_map: {total} images -> train {counts['train']} / "
          f"validate {counts['validate']} / test {counts['test']}")
    assert total == len(rows)

    if args.check_urls:
        step = max(1, len(out_rows) // args.check_urls)
        sample = out_rows[::step][:args.check_urls]
        bad_urls = 0
        for r in sample:
            a = head_status(r["raw_url"])
            # A blank render url is a recorded absence, not a failure.
            b = head_status(r["png_v3_sdr_url"]) if r["png_v3_sdr_url"] else 200
            c = head_status(r["png_v3_hdr_url"]) if r["png_v3_hdr_url"] else 200
            ok = (a == 200 and b == 200 and c == 200)
            if not ok:
                bad_urls += 1
            print(f"  url-probe id={r['id']} raw={a} sdr={b} hdr={c}"
                  f"{'' if ok else '   <-- CHECK'}")
        print(f"url probe: {len(sample) - bad_urls}/{len(sample)} fully live")
        if bad_urls:
            # This used to print and pass. It printed for months while 196 rows
            # carried 404s, so it now fails the run.
            print(f"ERROR: {bad_urls} sampled rows have a dead url — regenerate "
                  f"{RENDER_INDEX} (scripts/build_png_v3_index.py) before shipping "
                  "these manifests", file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
