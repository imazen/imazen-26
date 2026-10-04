#!/usr/bin/env python3
"""diff_runs.py <run_a> <run_b> — mechanical LTS-vs-latest (or any two-run)
matrix diff (r13 L-3): every count the doc quotes comes from this output,
never a hand tally.

Reads <run>/matrix.tsv in both dirs, joins on (adapter, fixture), and emits
on stdout:
  - a summary block: row counts, identical rows, differing rows, and the
    status/verdict move tallies (error->ok, ok->ok verdict flips, etc.)
  - a move table: one line per (adapter, fixture) pair whose status or
    verdict differs: adapter, fixture, a_status->b_status,
    a_verdict->b_verdict (tagged columns diffed as verdict_tagged too).
`flaky` cells are listed but kept out of the move tallies — a flaky cell is
infrastructure noise, not a decoder change (L-3).
"""
import csv
import sys
from collections import Counter
from pathlib import Path

def load(run):
    p = Path(run) / "matrix.tsv"
    rows = {}
    with open(p, newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows[(r["adapter"], r["fixture"])] = r
    return rows

def main():
    if len(sys.argv) != 3:
        sys.exit("usage: diff_runs.py <run_a> <run_b>")
    a, b = load(sys.argv[1]), load(sys.argv[2])
    keys = sorted(set(a) | set(b))
    moves = []
    tally = Counter()
    flaky = 0
    only_a = only_b = 0
    for k in keys:
        ra, rb = a.get(k), b.get(k)
        if ra is None:
            only_b += 1
            continue
        if rb is None:
            only_a += 1
            continue
        if ra == rb:
            continue
        sa, sb = ra["status"], rb["status"]
        va, vb = ra["verdict"], rb["verdict"]
        ta, tb = ra.get("verdict_tagged", ""), rb.get("verdict_tagged", "")
        if sa == sb and va == vb and ta == tb:
            continue  # numeric drift only
        if "flaky" in (sa, sb, va, vb):
            flaky += 1
            continue
        moves.append((k, f"{sa}->{sb}", f"{va}->{vb}", f"{ta}->{tb}"))
        tally[f"{sa}->{sb}"] += 1
        if sa == sb == "ok" and va != vb:
            tally["ok verdict flips"] += 1
    print(f"# diff_runs {sys.argv[1]} vs {sys.argv[2]}")
    print(f"# rows a={len(a)} b={len(b)} only_a={only_a} only_b={only_b} "
          f"differing={len(moves)} flaky-excluded={flaky}")
    for m, n in sorted(tally.items()):
        print(f"# {m}\t{n}")
    print("adapter\tfixture\tstatus\tverdict\tverdict_tagged")
    for (adp, fix), sm, vm, tm in moves:
        print(f"{adp}\t{fix}\t{sm}\t{vm}\t{tm}")

if __name__ == "__main__":
    main()
