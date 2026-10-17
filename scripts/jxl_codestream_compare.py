#!/usr/bin/env python3
"""Compare two trees of JPEG XL files codestream by codestream.

    jxl_codestream_compare.py <old-dir> <new-dir> [--jobs 8] > compare.tsv

For every .jxl under <new-dir>, reads the file at the same relative path under <old-dir> and
writes one row: the sha256 of each file's codestream (a bare codestream, or the jxlc / jxlp
payloads joined in file order), whether the two are the same, each file's top-level boxes,
and whether the new file is in libjxl's box order (render_v4_jxl_check.box_order_error).
Prints a summary on stderr and exits 1 when a codestream differs or a file is missing.
Written for the 2026-10-17 re-render that moved the metadata boxes into libjxl's order.
"""
import argparse
import hashlib
import os
import struct
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_v4_jxl_check import box_order_error  # noqa: E402


def codestream(path):
    """(sha256 of the codestream, the box list as text)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] == b"\xff\x0a":
        h.update(data)
        return h.hexdigest(), "bare"
    pos, boxes = 0, []
    while pos < len(data):
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        head = 8
        if size == 1:
            size, head = struct.unpack(">Q", data[pos + 8:pos + 16])[0], 16
        elif size == 0:
            size = len(data) - pos
        name = kind.decode("latin1")
        if kind == b"jxlc":
            h.update(data[pos + head:pos + size])
        elif kind == b"jxlp":
            index = struct.unpack(">I", data[pos + head:pos + head + 4])[0]
            name += f"{index & 0x7fffffff}{'L' if index >> 31 else ''}"
            h.update(data[pos + head + 4:pos + size])
        elif kind == b"brob":
            name += "(" + data[pos + head:pos + head + 4].decode("latin1") + ")"
        boxes.append(name)
        pos += size
    return h.hexdigest(), " ".join(boxes)


def compare(job):
    old_root, new_root, rel = job
    new = os.path.join(new_root, rel)
    old = os.path.join(old_root, rel)
    new_sha, new_boxes = codestream(new)
    order = box_order_error(new) or ""
    if not os.path.exists(old):
        return [rel, "", new_sha, "missing", "", new_boxes, order]
    old_sha, old_boxes = codestream(old)
    return [rel, old_sha, new_sha, "same" if old_sha == new_sha else "DIFFERENT", old_boxes, new_boxes, order]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old_dir")
    ap.add_argument("new_dir")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    rels = sorted(
        os.path.relpath(os.path.join(d, n), a.new_dir)
        for d, _, names in os.walk(a.new_dir)
        for n in names
        if n.endswith(".jxl")
    )
    print("path\told_codestream_sha256\tnew_codestream_sha256\tcodestream\told_boxes\tnew_boxes\tnew_box_order_error")
    counts = {}
    bad_order = 0
    with ProcessPoolExecutor(a.jobs) as ex:
        for row in ex.map(compare, [(a.old_dir, a.new_dir, r) for r in rels], chunksize=8):
            print("\t".join(row))
            counts[row[3]] = counts.get(row[3], 0) + 1
            bad_order += bool(row[6])
    print(f"{len(rels)} files: {counts}; {bad_order} not in libjxl's box order", file=sys.stderr)
    sys.exit(1 if counts.get("DIFFERENT") or counts.get("missing") or bad_order else 0)


if __name__ == "__main__":
    main()
