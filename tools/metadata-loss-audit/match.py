#!/usr/bin/env python3
"""Pair each canonical file with its earlier copies.
Content match: same key from keys.py (image data unchanged, metadata may differ).
Name fallback, only for ids with no content match: the same basename, or the camera
date-time token (canonical `YYYYMMDD-HHMMSS` = earlier `YYYYMMDD_HHMMSS`).
Usage: match.py canonical_keys.tsv candidate_keys.tsv > matches.tsv"""
import sys, re, csv, collections, os

def rows(p):
    for line in open(p):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 3: yield f[0], f[1], f[2]

canon = list(rows(sys.argv[1]))
by_key = collections.defaultdict(list); by_name = collections.defaultdict(list)
for path, kind, key in rows(sys.argv[2]):
    by_key[key].append(path)
    b = os.path.basename(path); by_name[b.lower()].append(path)
    m = re.search(r"(\d{8})_(\d{6})", b)
    if m: by_name[f"{m[1]}-{m[2]}"].append(path)
w = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
w.writerow(["id", "class", "match", "canonical", "candidate", "same_bytes"])
for path, kind, key in canon:
    base = os.path.basename(path); cid = base.split("_", 1)[0]; cls = path.split("/")[-2]
    hits = [(c, "content") for c in by_key.get(key, [])]
    if not hits:
        names = by_name.get(base.lower(), [])
        m = re.search(r"_(\d{8}-\d{6})_", base)
        if m: names = names + by_name.get(m[1], [])
        hits = [(c, "name") for c in dict.fromkeys(names)]
    if not hits: w.writerow([cid, cls, "none", path, "", ""]); continue
    size = os.path.getsize(path)
    for c, how in hits:
        same = int(os.path.getsize(c) == size and open(c, "rb").read() == open(path, "rb").read())
        w.writerow([cid, cls, how, path, c, same])
