#!/usr/bin/env python3
"""Point the manifests at a staged originals pass (scripts/stage_originals.py output).

For every row of <staging>/changes.tsv, the folder MANIFEST.tsv (the source of truth) gets
the new file name, format, byte count and, where the folder records one, sha256.
CORPUS-MANIFEST.tsv gets the same path, format and bytes. Then make_canonical_split.py
recomputes split_map.tsv, {train,validate,test}.tsv and the splits/ links from the staged
bytes, a renamed file's old split link is removed, the v1 family map follows renames, and
emit_family_split_v2.py recomputes the successor family map.

Every staged file is checked against changes.tsv first; nothing is written if one differs.

Usage: python3 scripts/apply_originals_pass.py <staging-dir>
"""
import hashlib
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


NEWLINE = {}


def read_tsv(path):
    """Plain tab-split rows (no quoting rules) in the file's own line ending (the folder
    manifests use CRLF), so untouched fields are rewritten byte for byte."""
    with open(path, newline="") as f:
        text = f.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    NEWLINE[path] = nl
    lines = text.split(nl)
    if lines[-1] == "":
        lines.pop()
    cols = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        vals = line.split("\t")
        if len(vals) != len(cols):
            raise SystemExit(f"{path}: a row has {len(vals)} fields, the header {len(cols)}")
        rows.append(dict(zip(cols, vals)))
    return cols, rows


def write_tsv(path, cols, rows):
    nl = NEWLINE[path]
    with open(path, "w", newline="") as f:
        f.write("\t".join(cols) + nl)
        f.writelines("\t".join(r[k] for k in cols) + nl for r in rows)


def main():
    staging = sys.argv[1]
    _, changes = read_tsv(os.path.join(staging, "changes.tsv"))
    for c in changes:
        p = os.path.join(staging, c["new_path"])
        if os.path.getsize(p) != int(c["new_bytes"]) or sha(p) != c["new_sha256"]:
            raise SystemExit(f"staged file differs from changes.tsv: {c['new_path']}")
    by_id = {c["id"]: c for c in changes}

    cm_path = os.path.join(REPO, "CORPUS-MANIFEST.tsv")
    cm_cols, cm = read_tsv(cm_path)
    if {r["number"] for r in cm} != set(by_id):
        raise SystemExit("changes.tsv does not cover exactly the CORPUS-MANIFEST ids")
    renamed = []
    for r in cm:
        c = by_id[r["number"]]
        if r["path"] != c["path"]:
            raise SystemExit(f"{r['number']}: CORPUS-MANIFEST path differs from changes.tsv")
        if c["new_path"] != c["path"]:
            renamed.append((r["number"], c["path"], c["new_path"]))
        r["path"] = c["new_path"]
        r["format"] = os.path.splitext(c["new_path"])[1][1:].lower()
        r["bytes"] = c["new_bytes"]

    folders = sorted({r["folder"] for r in cm})
    for folder in folders:
        mf = os.path.join(REPO, folder, "MANIFEST.tsv")
        cols, rows = read_tsv(mf)
        for r in rows:
            c = by_id.get(r["number"])
            if c is None:
                continue
            if os.path.join(folder, r["filename"]) != c["path"]:
                raise SystemExit(f"{r['number']}: {mf} filename differs from changes.tsv")
            r["filename"] = os.path.relpath(c["new_path"], folder)
            r["format"] = os.path.splitext(c["new_path"])[1][1:].lower()
            r["bytes"] = c["new_bytes"]
            if "sha256" in r:
                r["sha256"] = c["new_sha256"]
        write_tsv(mf, cols, rows)
    write_tsv(cm_path, cm_cols, cm)
    for r in cm:
        _, rows = read_tsv(os.path.join(REPO, r["folder"], "MANIFEST.tsv"))
        f = next(x for x in rows if x["number"] == r["number"])
        if (os.path.join(r["folder"], f["filename"]), f["format"], f["bytes"]) != \
                (r["path"], r["format"], r["bytes"]):
            raise SystemExit(f"{r['number']}: CORPUS-MANIFEST disagrees with its folder manifest")

    subprocess.run([sys.executable, os.path.join(REPO, "scripts", "make_canonical_split.py"),
                    "--repo-im26", REPO, "--images-root", staging], check=True)
    for rid, old, new in renamed:
        bucket = {0: "train", 2: "train", 4: "train", 6: "train", 8: "train", 1: "validate",
                  3: "validate", 5: "validate", 7: "test", 9: "test"}[int(rid) % 10]
        link = os.path.join(REPO, "splits", bucket, old)
        if os.path.islink(link):
            os.remove(link)
    v1 = os.path.join(REPO, "manifests", "split_map_family.tsv")
    cols, rows = read_tsv(v1)
    for r in rows:
        c = by_id.get(r["id"])
        if c is not None and r["path"] == c["path"]:
            r["path"] = c["new_path"]
    write_tsv(v1, cols, rows)
    subprocess.run([sys.executable, os.path.join(REPO, "scripts", "emit_family_split_v2.py")],
                   check=True)
    print(f"{len(changes)} rows applied; renamed: {[r[0] for r in renamed]}")


if __name__ == "__main__":
    main()
