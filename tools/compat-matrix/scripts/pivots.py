#!/usr/bin/env python3
"""pivots.py <matrix_dir> — turn matrix.tsv + decode.tsv into markdown pivots.

Reads matrix.tsv (adapter,fixture,class,status,verdict,correct,d1,d2,w,h,ms,
error) and emits markdown tables to stdout:
  - status counts per adapter x class
  - orientation grid (fixture x adapter -> verdict)
  - colour grid
  - HDR/gainmap table
  - metadata/conflict table
  - failure taxonomy
"""
import csv, sys, collections

d = sys.argv[1]
rows = list(csv.DictReader(open(f"{d}/matrix.tsv"), delimiter="\t"))

adapters = sorted({r["adapter"] for r in rows})
classes = ["orientation", "colour", "gainmap", "metadata", "other"]

def cls(r):
    c = r["class"]
    if r["fixture"].endswith("mpf-corrupt") or r["fixture"].endswith("-corrupt"):
        return "other"
    return c if c in classes else "other"

print("## Status counts (adapter x class)\n")
print("| adapter | " + " | ".join(classes) + " |")
print("|" + "---|" * (len(classes) + 1))
for a in adapters:
    cells = []
    for c in classes:
        sel = [r for r in rows if r["adapter"] == a and cls(r) == c]
        ok = sum(1 for r in sel if r["status"] == "ok")
        correct = sum(1 for r in sel if r["correct"] == "true")
        cells.append(f"{correct}/{ok}/{len(sel)}" if sel else "-")
    print(f"| {a} | " + " | ".join(cells) + " |")
print("\n(cells: correct-verdict / decoded-ok / fixtures-in-class)\n")

def grid(want_cls, title):
    fs = [r["fixture"] for r in rows if cls(r) == want_cls]
    fs = sorted(set(fs))
    if not fs:
        return
    print(f"## {title}\n")
    print("| fixture | " + " | ".join(adapters) + " |")
    print("|" + "---|" * (len(adapters) + 1))
    for f in fs:
        cells = []
        for a in adapters:
            r = next((x for x in rows if x["adapter"] == a and x["fixture"] == f), None)
            if r is None:
                cells.append("·")
            elif r["status"] != "ok":
                cells.append("ERR")
            elif r["correct"] == "true":
                cells.append("✓")
            elif r["verdict"] == "other":
                cells.append("?")
            elif r["verdict"] == "n/a":
                cells.append("·")
            else:
                cells.append(r["verdict"][:12])
        print(f"| {f} | " + " | ".join(cells) + " |")
    print("\n✓ accepted-correct · ? ambiguous/other · ERR decode error · · n/a\n")

grid("orientation", "Orientation verdicts")
grid("colour", "Colour verdicts")
grid("gainmap", "HDR / gain-map")
grid("metadata", "Metadata / conflicts")
grid("other", "Other / robustness")

print("## Failure taxonomy\n")
byerr = collections.Counter()
for r in rows:
    if r["status"] != "ok":
        head = r["error"][:80] or r["status"]
        byerr[(r["adapter"], head)] += 1
for (a, e), n in byerr.most_common(30):
    print(f"- {a} ×{n}: {e}")
