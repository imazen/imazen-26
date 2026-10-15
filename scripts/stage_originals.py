#!/usr/bin/env python3
"""Stage the originals pass (EXPORT-PLAN.md, step 1): every corpus file's final bytes, for review.

Nothing here touches R2. The output tree is what the public prefix and the private
`imazen-26-originals` bucket will hold once the owner approves the diff.

Inputs, each checked by sha256 before use:
  --manifests DIR     manifests/{train,validate,test}.tsv (the current membership)
  --src DIR           the published bytes, downloaded from R2, by manifest path
  --whitelist-v2 DIR  whitelist-v2 outputs and their manifest.tsv (the camera files)
  --camera-1214 FILE  1214's camera original (the manifests already name its sha256)
  --flatten DIR       9869 and 9874 after the white-background flatten
  --corpus-thumbs BIN tools/corpus-thumbs, for 1044's JPEG
  --png-crush BIN     tools/png-crush
  --out DIR           a new staging tree

Per id the base bytes are: the whitelist-v2 output for a camera file (v2's record of the
canonical sha256 must equal the published sha256), 1214's camera original, a q100 JPEG of
1044 (corpus-thumbs --to-jpeg libjpeg100 from its v2 HEIC, dropping the motion-photo clip),
the flattened 9869/9874, or else the published bytes. Then:
  - phone screenshots get the camera-class metadata policy (whitelist_v2.rewrite_png /
    rewrite_jpeg): Software, OffsetTime*, ImageUniqueID and the SEFT trailer go;
  - other JPEGs lose any APP11 (C2PA/JUMBF) segment, nothing else;
  - every PNG is crushed by png-crush at effort 22 (drops caBX, text chunks, sBIT, bKGD,
    tIME and data after IEND; the pixels must match exactly);
  - everything else is hard-linked unchanged.

Writes <out>/<path>, <out>/changes.tsv, <out>/crush.tsv and <out>/SHA256SUMS. In changes.tsv,
`before_sha256` is the manifests' value: the published bytes, except 5314 (corrected below) and
1214 (the manifests already name its camera original).

Usage: stage_originals.py --manifests manifests --src ... --out ... [--jobs 12] [--only 1044,8023]
"""
import argparse
import concurrent.futures as cf
import csv
import errno
import hashlib
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import whitelist_v2 as wl  # noqa: E402

# train.tsv has carried a wrong sha256 for 5314 since the seed commit 20e25c4. The published
# object, the 2026-08-22 attic copy and the folder MANIFEST.tsv all hash to this value.
PUBLISHED_SHA_FIXES = {
    "5314": "7d552aedcfffb6514e9efdabe21ba1960ec608a6140f6a1dc5c33b899cf38c01",
}
# zenfilters examples/ai_corpus_flatten.rs at zenpipe 354b55ae, run on the published bytes;
# the re-run of 2026-10-15 reproduced both files byte for byte.
FLATTENED = {
    "9869": "875c29e6fc312e12",
    "9874": "c246953115610b18",
}
SCREENSHOTS = "8000-lilith-mobile-screenshots"
CRUSH_EFFORT = "22"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_rows(manifests):
    rows = []
    for bucket in ("train", "validate", "test"):
        with open(os.path.join(manifests, f"{bucket}.tsv")) as f:
            rows += list(csv.DictReader(f, delimiter="\t"))
    return rows


def strip_app11(d):
    """The JPEG without its APP11 segments, and their payloads; the image body is unchanged."""
    marks = wl.jpeg_markers(d)
    out, removed, pos = [d[:2]], [], 2
    for m, s, e in marks:
        if m == 0xEB:
            out.append(d[pos:s])
            removed.append(d[s + 4:e])
            pos = e
    out.append(d[pos:])
    new = b"".join(out)
    if wl.image_key(".jpg", new) != wl.image_key(".jpg", d):
        raise wl.Reject("image data changed while removing APP11")
    return new, removed


def has_app11(d):
    return any(m == 0xEB for m, _, _ in wl.jpeg_markers(d))


def write_new(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "xb") as f:
        f.write(data)


def link(src, dst):
    """Hard-link unchanged bytes; copy when the staging tree is on another filesystem."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)
    except OSError as ex:
        if ex.errno != errno.EXDEV:
            raise
        write_new(dst, open(src, "rb").read())


def crush_shards(bin_, items, out, jobs):
    """Run png-crush over (id, input, out-rel) items in `jobs` parallel processes."""
    items = sorted(items, key=lambda x: -os.path.getsize(x[1]))
    shards = [items[k::jobs] for k in range(jobs)]
    lists = []
    for k, shard in enumerate(shards):
        if not shard:
            continue
        p = os.path.join(out, f"_crush_list_{k:02}.tsv")
        with open(p, "w") as f:
            f.writelines(f"{i}\t{a}\t{b}\n" for i, a, b in shard)
        lists.append(p)
    env = dict(os.environ, RAYON_NUM_THREADS="2")

    def run(p):
        r = subprocess.run([bin_, CRUSH_EFFORT, p, out], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise SystemExit(f"png-crush failed on {p}: {r.stderr[-2000:]}")
        return r.stdout.splitlines()[1:]

    report = []
    with cf.ThreadPoolExecutor(len(lists)) as ex:
        for lines in ex.map(run, lists):
            report += lines
    for p in lists:
        os.remove(p)
    return report


def main():
    ap = argparse.ArgumentParser()
    for a in ("manifests", "src", "whitelist-v2", "camera-1214", "flatten", "corpus-thumbs",
              "png-crush", "out"):
        ap.add_argument("--" + a, required=True)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    out = args.out
    if os.path.exists(out):
        raise SystemExit(f"refusing: {out} exists")
    os.makedirs(out)
    pre = os.path.join(out, "_pre")

    rows = read_rows(args.manifests)
    if args.only:
        keep = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in keep]
    wl2 = {}
    with open(os.path.join(args.whitelist_v2, "manifest.tsv")) as f:
        for r in csv.DictReader(f, delimiter="\t"):
            wl2[r["id"]] = r

    changes, crush_items, failures = [], [], []
    for r in rows:
        rid, path = r["id"], r["path"]
        published = PUBLISHED_SHA_FIXES.get(rid, r["sha256"])
        ext = os.path.splitext(path)[1].lower()
        new_path, steps = path, []
        try:
            if rid == "1044":
                v2 = wl2[rid]
                if v2["canonical_sha256"] != published:
                    raise wl.Reject("whitelist-v2 row does not match the published file")
                heic = os.path.join(args.whitelist_v2, v2["output"])
                new_path = os.path.splitext(path)[0] + ".jpg"
                dst = os.path.join(out, new_path)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                res = subprocess.run([args.corpus_thumbs, "--to-jpeg", "libjpeg100", heic, dst],
                                     capture_output=True, text=True)
                if res.returncode != 0:
                    raise wl.Reject(f"to-jpeg: {res.stderr.strip()}")
                steps.append(f"whitelist-v2 HEIC to q100 JPEG ({res.stdout.strip()})")
                base, ext = None, ".jpg"
            elif rid == "1214":
                base = args.camera_1214
                if sha(base) != r["sha256"]:
                    raise wl.Reject("1214 camera original does not match the manifest")
                steps.append("camera original")
            elif rid in wl2:
                v2 = wl2[rid]
                if v2["status"] != "ok" or v2["canonical_sha256"] != published:
                    raise wl.Reject("whitelist-v2 row does not match the published file")
                base = os.path.join(args.whitelist_v2, v2["output"])
                if sha(base) != v2["output_sha256"]:
                    raise wl.Reject("whitelist-v2 output changed since its manifest")
                steps.append("whitelist-v2")
            elif rid in FLATTENED:
                src = os.path.join(args.src, path)
                if sha(src) != published:
                    raise wl.Reject("published bytes do not match the manifest")
                base = os.path.join(args.flatten, os.path.basename(path))
                if not sha(base).startswith(FLATTENED[rid]):
                    raise wl.Reject("flattened file changed")
                steps.append("white-background flatten")
            else:
                base = os.path.join(args.src, path)
                if sha(base) != published:
                    raise wl.Reject("published bytes do not match the manifest")

            dst = os.path.join(out, new_path)
            if base is not None and path.startswith(SCREENSHOTS + "/"):
                d = open(base, "rb").read()
                if ext == ".png":
                    new, removed, kept, notes = wl.rewrite_png(d)
                else:
                    new, removed, kept, notes = wl.rewrite_jpeg(d)
                wl.verify(ext, d, new, removed, kept, notes)
                steps.append("camera-class metadata policy")
                if ext == ".png":
                    base = os.path.join(pre, path)
                    write_new(base, new)
                else:
                    write_new(dst, new)
                    base = None
            elif base is not None and ext == ".jpg" and rid not in wl2 and has_app11(open(base, "rb").read()):
                new, removed = strip_app11(open(base, "rb").read())
                write_new(dst, new)
                steps.append(f"APP11 removed ({sum(len(x) for x in removed)} bytes)")
                base = None
            if base is not None and ext == ".png":
                crush_items.append((rid, base, new_path))
                steps.append(f"png-crush e{CRUSH_EFFORT}")
                base = None
            if base is not None:
                link(base, dst)
        except (wl.Reject, KeyError, OSError) as ex:
            failures.append((rid, f"{type(ex).__name__}: {ex}"))
            continue
        changes.append({"id": rid, "path": path, "new_path": new_path, "before_sha256": published,
                        "before_bytes": r["bytes_actual"], "steps": "; ".join(steps)})

    crush = crush_shards(args.png_crush, crush_items, out, args.jobs) if crush_items else []
    with open(os.path.join(out, "crush.tsv"), "w") as f:
        f.write("id\tin_bytes\tout_bytes\tms\tin_layout\tout_layout\tdropped\terror\n")
        f.writelines(line + "\n" for line in crush)
    for line in crush:
        f_ = line.split("\t")
        if f_[7]:
            failures.append((f_[0], "png-crush: " + f_[7]))

    sums = []
    with open(os.path.join(out, "changes.tsv"), "w") as f:
        cols = ["id", "path", "new_path", "steps", "before_sha256", "new_sha256",
                "before_bytes", "new_bytes"]
        f.write("\t".join(cols) + "\n")
        for c in changes:
            p = os.path.join(out, c["new_path"])
            if not os.path.exists(p):
                continue
            c["new_sha256"], c["new_bytes"] = sha(p), str(os.path.getsize(p))
            sums.append(f"{c['new_sha256']}  {c['new_path']}\n")
            f.write("\t".join(c[k] for k in cols) + "\n")
    with open(os.path.join(out, "SHA256SUMS"), "w") as f:
        f.writelines(sorted(sums, key=lambda s: s[66:]))
    if os.path.isdir(pre):
        for root, _, files in os.walk(pre, topdown=False):
            for x in files:
                os.remove(os.path.join(root, x))
            os.rmdir(root)
    changed = sum(1 for c in changes if c["steps"])
    print(f"{len(rows)} rows, {len(sums)} files staged, {changed} changed, {len(failures)} failures")
    for rid, msg in failures:
        print(f"FAILED {rid}: {msg}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
