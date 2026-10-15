#!/usr/bin/env python3
"""Successor of the family-aware split map: manifests/split_map_family_v2.tsv.

The registered rule is unchanged: every id takes the last-digit bucket of its family's
lowest id. What changes is which images count as one family. These keys are unioned:

  patent-page  patent + patent_page from the 6000 MANIFEST.tsv, so a page's 1-bit
               original and both rescans are one family. The v1 map missed the 1-bit
               pages, whose names say "1bit" rather than "original", and us3807657's
               rescans are its odd pages (patent_page, not the scan's page number).
  plots-run    the v1 key: kind variants of one generator run share content.
  chart        real-charts theme variants: chart-<kind>-<NN>-<theme> files of one kind
               draw the same data in different palettes (the five pie charts).
  screen-page  the v1 key (site slug + page) and, from the 8100 manifest, url + page,
               which also joins one URL captured under two slugs. The placeholder url
               "local-capture" is skipped: five unrelated terminal screenshots share it.
  sha256       byte-identical files (none left after the 2026-10-15 retirements).
  burst        photo bursts (filename timestamps <= 120 s apart) and the near-duplicate
               pairs seen by eye, from variant-sets/squintly-candidates@2026-09-22.

Only ids in CORPUS-MANIFEST.tsv count, so retired ids neither join nor anchor anything.
NOAA reports are not keyed (owner decision S1, 2026-10-15).

Usage: python3 scripts/emit_family_split_v2.py [--out manifests/split_map_family_v2.tsv]
"""
import argparse
import collections
import csv
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def split_of(i):
    d = int(i) % 10
    return "train" if d % 2 == 0 else ("validate" if d in (1, 3, 5) else "test")


def tsv(path):
    with open(os.path.join(REPO, path), newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


class Union:
    def __init__(self):
        self.p, self.why = {}, collections.defaultdict(set)

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def join(self, ids, why):
        ids = list(ids)
        for i in ids:
            self.find(i)
        for i in ids[1:]:
            a, b = self.find(ids[0]), self.find(i)
            if a != b:
                self.p[max(a, b)] = min(a, b)
        if len(ids) > 1:
            self.why[ids[0]].add(why)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "manifests", "split_map_family_v2.tsv"))
    a = ap.parse_args()

    corpus = tsv("CORPUS-MANIFEST.tsv")
    member = {r["number"]: r for r in corpus}
    u = Union()
    for i in member:
        u.find(i)

    def groups(keyed, why):
        g = collections.defaultdict(list)
        for k, i in keyed:
            if i in member:
                g[k].append(i)
        for ids in g.values():
            if len(ids) > 1:
                u.join(sorted(ids), why)

    # patent pages: every scan form of one patent page
    patents = tsv("6000-lilith-scans-public-patents/MANIFEST.tsv")
    groups((((r["patent"], r["patent_page"]), r["number"]) for r in patents), "patent-page")

    # plot runs (v1 key)
    def plot_key(path):
        m = re.search(r"_plots_([a-z-]+?)-(\d+)-s([0-9a-f]+)_", os.path.basename(path))
        return ("plots-run", m.group(2), m.group(3)) if m else None
    groups(((plot_key(r["path"]), r["number"]) for r in corpus if plot_key(r["path"])), "plots-run")

    # real-charts: one chart kind in several themes is one chart
    def chart_key(path):
        m = re.search(r"/\d{4}_plots_chart-([a-z]+)-\d+-[a-z]+_", path)
        return ("chart", m.group(1)) if m else None
    groups(((chart_key(r["path"]), r["number"]) for r in corpus if chart_key(r["path"])), "chart")

    # web captures: v1 slug key and url + page
    shots = tsv("8100-lilith-web-screenshots/MANIFEST.tsv")
    def slug_key(name):
        m = re.match(r"\d{4}_[a-z-]+_(.+?)_dpr\d+_page(\d+)", os.path.basename(name))
        return (re.sub(r"[^a-z0-9]", "", m.group(1))[:10], m.group(2)) if m else None
    groups(((slug_key(r["filename"]), r["number"]) for r in shots if slug_key(r["filename"])), "screen-page")
    def url_key(r):
        url = (r.get("url") or "").strip()
        page = re.search(r"page(\d+)", r.get("keyinfo") or "")
        if not url or url == "local-capture" or not page:
            return None
        return (url.rstrip("/").lower(), page.group(1))
    groups(((url_key(r), r["number"]) for r in shots if url_key(r)), "url-page")

    # byte-identical files
    sha = {}
    for s in ("train", "validate", "test"):
        for r in tsv(f"manifests/{s}.tsv"):
            sha[r["id"]] = r["sha256"]
    groups(((h, i) for i, h in sha.items() if h), "sha256")

    # photo bursts and pairs seen by eye
    for r in tsv("variant-sets/squintly-candidates@2026-09-22/families.tsv"):
        why = r["joined_by"]
        if "burst" in why or "near-dup-by-eye" in why:
            ids = sorted(i for i in r["ids"].split(",") if i in member)
            if len(ids) > 1:
                u.join(ids, "burst")

    fams = collections.defaultdict(list)
    for i in member:
        fams[u.find(i)].append(i)
    reasons = collections.defaultdict(set)
    for first, whys in u.why.items():
        reasons[u.find(first)] |= whys

    v1 = {r["id"]: r["split"] for r in tsv("manifests/split_map_family.tsv")}
    rows = []
    for root, ids in fams.items():
        anchor = min(ids)
        for i in ids:
            fam = f"{anchor}:{'+'.join(sorted(reasons[root]))}" if len(ids) > 1 else ""
            rows.append((i, split_of(anchor), fam, member[i]["path"]))
    rows.sort()

    # checks: one bucket per family, and per patent page
    bucket = {r[0]: r[1] for r in rows}
    for ids in fams.values():
        assert len({bucket[i] for i in ids}) == 1
    pages = collections.defaultdict(set)
    for r in patents:
        if r["number"] in bucket:
            pages[(r["patent"], r["patent_page"])].add(bucket[r["number"]])
    crossing = [k for k, b in pages.items() if len(b) > 1]
    assert not crossing, f"patent pages crossing buckets: {crossing}"

    with open(a.out, "w", newline="") as f:
        f.write("id\tsplit\tfamily\tpath\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    c = collections.Counter(r[1] for r in rows)
    multi = sum(1 for ids in fams.values() if len(ids) > 1)
    vs_rule = sum(1 for r in rows if r[1] != split_of(r[0]))
    vs_v1 = sum(1 for r in rows if v1.get(r[0]) and r[1] != v1[r[0]])
    print(f"{a.out}: {len(rows)} ids, {dict(c)}; {multi} multi-member families; "
          f"{vs_rule} ids differ from the last-digit rule, {vs_v1} from split_map_family.tsv; "
          f"{len(pages)} patent pages, 0 crossing buckets")


if __name__ == "__main__":
    main()
