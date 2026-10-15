#!/usr/bin/env python3
"""Retire corpus ids: they leave every membership manifest and split link, and are
recorded in manifests/retired.tsv. Ids are never reused; the gaps stay.

Usage: python3 scripts/retire_ids.py --reason "..." [--date YYYY-MM-DD] [--dup-of ID] ID [ID ...]

- per-folder <folder>/MANIFEST.tsv: the rows go (line endings preserved)
- CORPUS-MANIFEST.tsv: rebuilt with scripts/build_corpus_manifest.py
- manifests/split_map.tsv, {train,validate,test}.tsv, split_map_family.tsv: rows go
  (the last-digit rule is per id, so filtering equals regenerating)
- splits/<bucket>/...: the id's relative symlink goes
- manifests/retired.tsv: one row per id with path, sha256, bytes, date and reason

The successor family map (split_map_family_v2.tsv) is regenerated separately with
scripts/emit_family_split_v2.py, once membership is final.
"""
import argparse
import csv
import datetime
import glob
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def filter_lines(path, drop, key_col):
    with open(path, "rb") as f:
        data = f.read()
    nl = b"\r\n" if b"\r\n" in data else b"\n"
    lines = data.split(nl)
    head = lines[0].decode().split("\t")
    k = head.index(key_col)
    kept = [lines[0]] + [l for l in lines[1:] if not (l and l.decode().split("\t")[k] in drop)]
    gone = len(lines) - len(kept)
    with open(path, "wb") as f:
        f.write(nl.join(kept))
    return gone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--dup-of", default="")
    a = ap.parse_args()
    drop = set(a.ids)

    rows = {}
    for s in ("train", "validate", "test"):
        with open(os.path.join(REPO, "manifests", f"{s}.tsv"), newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                rows[r["id"]] = r
    missing = drop - set(rows)
    if missing:
        raise SystemExit(f"not in the corpus (already retired or unknown): {sorted(missing)}")

    folders = {rows[i]["path"].split("/")[0] for i in drop}
    for fol in sorted(folders):
        n = filter_lines(os.path.join(REPO, fol, "MANIFEST.tsv"), drop, "number")
        print(f"{fol}/MANIFEST.tsv: {n} rows removed")
    subprocess.run(["python3", "-I", os.path.join(REPO, "scripts", "build_corpus_manifest.py")], check=True)
    for name in ("split_map.tsv", "train.tsv", "validate.tsv", "test.tsv", "split_map_family.tsv"):
        n = filter_lines(os.path.join(REPO, "manifests", name), drop, "id")
        print(f"manifests/{name}: {n} rows removed")
    links = 0
    for i in drop:
        for p in glob.glob(os.path.join(REPO, "splits", "*", "**", f"{i}_*"), recursive=True):
            if os.path.islink(p):
                os.unlink(p)
                links += 1
    print(f"split links removed: {links}")

    out = os.path.join(REPO, "manifests", "retired.tsv")
    new = not os.path.exists(out)
    with open(out, "a", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        if new:
            w.writerow(["id", "path", "sha256", "bytes", "retired_on", "reason", "duplicate_of"])
        for i in sorted(drop):
            r = rows[i]
            w.writerow([i, r["path"], r["sha256"], r["bytes_actual"], a.date, a.reason, a.dup_of])
    print(f"manifests/retired.tsv: {len(drop)} rows added")


if __name__ == "__main__":
    main()
