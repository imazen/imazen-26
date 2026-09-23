#!/usr/bin/env python3
"""Select squintly stimulus candidates from imazen-26 (selection manifest, not renders).

Emits `variant-sets/squintly-candidates@<date>/selection.tsv`: one row per corpus id with
its stimulus family, the family's bucket, a content stratum, the visual-screening grade,
a pick (`batch1-train`, `reserve-test`, `pool`, `excluded`) and a presentation suggestion.

Why a separate family key. The canonical family split (`manifests/split_map_family.tsv`)
covers patents, plots and web captures only, and keys web captures by a capture-job slug,
so byte-identical files under two slugs (8134/8136, 8135/8137 …) sit in different
buckets. A paid human study cannot afford a near-duplicate on both sides of its
train/confirm line, so this script unions four keys before assigning buckets:

  1. the canonical `family` column;
  2. exact duplicates (same `sha256` in the split manifests);
  3. web captures of the same URL and page (`8100/MANIFEST.tsv` `url` + `keyinfo` page),
     which catches captures filed under two different capture-job slugs;
  4. photo bursts: shots in 1000–1600 whose filename timestamps are <= BURST_S apart,
     plus the untimestamped near-duplicate pairs listed in BURST_PAIRS (seen by eye).

A union family is eligible only when every member shares one bucket of the canonical
family split (`manifests/split_map_family.tsv`); a family that straddles buckets is
`mixed` and never picked. That keeps squintly compatible with every other consumer of
the corpus split: a squintly training label never lands on an image some other model
treats as validate/test, and the confirmatory reserve never holds a near-twin of a
training image. The corpus split itself is not changed here.

Within a stratum, picks go by grade (A before B before C) and, inside a grade, by
farthest-point sampling over z-scored zenanalyze content features at `full`/`native`,
so a stratum's picks spread over colourfulness, texture, gradients and skin instead of
repeating one look. At most one pick per family.

Usage:
    python3 scripts/build_squintly_candidates.py \
        --features /mnt/v/output/imazen-26-features/imazen26_features_2026-06-23.parquet \
        --set-dir "variant-sets/squintly-candidates@2026-09-22"
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from squintly_screening import grade_of  # noqa: E402  (the 2026-09-22 visual screening)
BURST_S = 120
# Untimestamped near-duplicates identified by eye on the 2026-09-22 contact sheets.
BURST_PAIRS = [
    ("1529", "1530"), ("1517", "1518"), ("1520", "1521"), ("1508", "1509"),
    ("1433", "1555"), ("1442", "1553"), ("1483", "1551"), ("1536", "1537"),
    ("1543", "1544"), ("1036", "1037"), ("1037", "1038"), ("1476", "1477"),
    ("1461", "1462"), ("3307", "3308"), ("1470", "1549"),
]
FEATURES = [
    "colourfulness", "edge_density", "skin_tone_fraction", "gradient_fraction_smooth",
    "noise_floor_y", "grayscale_score", "flat_color_block_ratio",
    "high_freq_energy_ratio", "luma_histogram_entropy", "laplacian_variance",
]
# stratum -> (batch1-train target, reserve-test target)
TARGETS = {
    "photo-people": (10, 5),
    "photo-food": (14, 6),
    "photo-landscape": (14, 6),
    "photo-flora": (12, 5),
    "photo-interior": (12, 5),
    "photo-general": (14, 6),
    "art-reproduction": (12, 5),
    "render-texture": (6, 3),
    "illustration-scan": (10, 4),
    "document-graphic": (12, 5),
    "document-text": (8, 4),
    "chart": (10, 4),
    "web-screenshot": (14, 6),
}
PHOTOLIKE = {"photo-people", "photo-food", "photo-landscape", "photo-flora",
             "photo-interior", "photo-general", "art-reproduction", "render-texture",
             "illustration-scan"}


def read_tsv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        lines = [l for l in fh if not l.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


class UF:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            self.p[hi] = lo


def bucket_of(i: str) -> str:
    d = int(i[-1])
    return "train" if d % 2 == 0 else ("validate" if d in (1, 3, 5) else "test")


def stratum_of(i: str, note: str, grade: str) -> str:
    f = i[:2]
    if f == "20":
        return "photo-people"
    if f == "16":
        return "photo-food"
    if f == "12":
        return "photo-interior"
    if f == "10":
        return "photo-general"
    if f in ("14", "15"):
        return "photo-flora" if "flower" in note else "photo-landscape"
    if f in ("30", "33"):
        return "art-reproduction"
    if f in ("22", "24"):
        return "render-texture"
    if f == "66":
        return "illustration-scan"
    if f in ("50",):
        return "document-graphic"
    if f in ("52", "53"):
        return "document-graphic" if grade in ("A", "B") else "document-text"
    if f in ("60",):
        return "document-graphic" if "drawing" in note else "document-text"
    if f == "68":
        return "document-text"
    if f in ("70", "71"):
        return "chart" if grade in ("A", "B") else "synthetic-line"
    if f == "81" or f in ("82", "83", "84"):
        return "web-screenshot"
    if f == "80":
        return "ui-mobile"
    return "ai-generated"


def load_features(path: Path) -> dict[str, list[float]]:
    import pyarrow.parquet as pq

    t = pq.read_table(path)
    names = {c.split("@")[0]: c for c in t.column_names}
    cols = ["image_path", "crop_label", "size_class"] + [names[f] for f in FEATURES]
    out: dict[str, list[float]] = {}
    for r in t.select(cols).to_pylist():
        if r["crop_label"] != "full" or r["size_class"] != "native":
            continue
        m = re.search(r"/(\d{4})_", r["image_path"])
        if m:
            out[m.group(1)] = [float(r[names[f]] or 0.0) for f in FEATURES]
    return out


def fps_order(ids: list[str], feats: dict[str, list[float]]) -> list[str]:
    """Farthest-point order over z-scored features; ties and misses fall back to id order."""
    have = [i for i in ids if i in feats]
    miss = [i for i in ids if i not in feats]
    if not have:
        return miss
    k = len(FEATURES)
    mu = [sum(feats[i][j] for i in have) / len(have) for j in range(k)]
    sd = [math.sqrt(sum((feats[i][j] - mu[j]) ** 2 for i in have) / len(have)) or 1.0
          for j in range(k)]
    z = {i: [(feats[i][j] - mu[j]) / sd[j] for j in range(k)] for i in have}
    # start from the item nearest the stratum centroid: a typical member, not an outlier
    first = min(have, key=lambda i: sum(v * v for v in z[i]))
    order, dmin = [first], {i: math.inf for i in have}
    while len(order) < len(have):
        last = z[order[-1]]
        for i in have:
            if i in order:
                continue
            d = sum((a - b) ** 2 for a, b in zip(z[i], last))
            dmin[i] = min(dmin[i], d)
        nxt = max((i for i in have if i not in order), key=lambda i: (dmin[i], i))
        order.append(nxt)
    return order + miss


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--features", type=Path, required=True)
    ap.add_argument("--set-dir", type=Path, required=True)
    ap.add_argument("--full-out", type=Path, help="per-id table for all 2,160 ids (block storage; "
                    "too large for git). Default: /mnt/v/output/imazen-26-variants/<set-dir name>/candidates_all.tsv")
    a = ap.parse_args()
    set_dir = a.set_dir if a.set_dir.is_absolute() else REPO / a.set_dir

    fam = {r["id"]: r for r in read_tsv(REPO / "manifests/split_map_family.tsv")}
    split_rows = {}
    for s in ("train", "validate", "test"):
        for r in read_tsv(REPO / f"manifests/{s}.tsv"):
            split_rows[r["id"]] = r
    lic = {r["number"]: r for r in read_tsv(REPO / "CORPUS-MANIFEST.tsv")}
    hdr = {r["id"]: r for r in read_tsv(REPO / "variant-sets/png-v3-index.tsv")}
    # `local-capture` is a placeholder shared by five unrelated terminal screenshots,
    # not a URL; keying on it would merge different images.
    url = {r["number"]: r["url"] + "|" + r["keyinfo"].split("|")[-1]
           for r in read_tsv(REPO / "8100-lilith-web-screenshots/MANIFEST.tsv")
           if r["url"].startswith("http")}
    grade = {i: dict(zip(("grade", "note"), grade_of(i, fam[i]["path"]))) for i in fam}
    feats = load_features(a.features)

    # --- union families ---
    uf = UF()
    for i in fam:
        uf.find(i)
    links: list[tuple[str, str, str]] = []  # (a, b, why) — every edge, for families.tsv
    by_key: dict[tuple, list[str]] = collections.defaultdict(list)
    for i, r in fam.items():
        if r["family"]:
            by_key[("canonical-family", r["family"])].append(i)
        by_key[("same-sha256", split_rows[i]["sha256"])].append(i)
        if i in url:
            by_key[("same-url-page", url[i])].append(i)
    for (why, _), members in by_key.items():
        for m in members[1:]:
            uf.union(members[0], m)
            links.append((members[0], m, why))
    stamp = {}
    for i, r in fam.items():
        if "1000" <= i < "1700":
            m = re.search(r"_(\d{8})-(\d{6})_", r["path"])
            if m:
                stamp[i] = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    timed = sorted(stamp.items(), key=lambda kv: kv[1])
    for (ia, ta), (ib, tb) in zip(timed, timed[1:]):
        if (tb - ta).total_seconds() <= BURST_S:
            uf.union(ia, ib)
            links.append((ia, ib, f"burst<={BURST_S}s"))
    for x, y in BURST_PAIRS:
        uf.union(x, y)
        links.append((x, y, "near-dup-by-eye"))
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for i in fam:
        groups[uf.find(i)].append(i)
    def family_bucket(v: list[str]) -> str:
        b = {fam[i]["split"] for i in v}
        return b.pop() if len(b) == 1 else "mixed"

    gbucket = {g: family_bucket(v) for g, v in groups.items()}
    why_of: dict[str, set[str]] = collections.defaultdict(set)
    for x, _, why in links:
        why_of[uf.find(x)].add(why)
    with open(set_dir / "families.tsv", "w", encoding="utf-8") as fh:
        fh.write("group_id\tsize\tbucket\tjoined_by\tcanonical_family_splits\tspans_canonical\tids\n")
        for g, v in sorted(groups.items()):
            if len(v) < 2:
                continue
            spl = sorted({fam[i]["split"] for i in v})
            fh.write(f"{g}\t{len(v)}\t{gbucket[g]}\t{','.join(sorted(why_of[g]))}\t"
                     f"{','.join(spl)}\t{int(len(spl) > 1)}\t{','.join(sorted(v))}\n")

    # --- rows ---
    rows = []
    for i in sorted(fam):
        g = grade[i]
        s = stratum_of(i, g["note"], g["grade"])
        root = uf.find(i)
        fmt = split_rows[i]["format"]
        rows.append({
            "id": i,
            "squintly_split": gbucket[root],
            "canonical_split": fam[i]["split"],
            "stratum": s,
            "grade": g["grade"],
            "pick": "",
            "exclude_reason": g["note"] if g["grade"] == "X" else "",
            "group_id": root,
            "group_size": str(len(groups[root])),
            "license": lic[i]["license"],
            "lossy_origin": "1" if fmt in ("jpg", "heic") else "0",
            "hdr_available": "1" if hdr[i]["hdr_url"] else "0",
            "presentation": "",
            "note": "" if g["grade"] == "X" else g["note"],
            "width": split_rows[i]["width"],
            "height": split_rows[i]["height"],
            "png_v3_sdr_url": split_rows[i]["png_v3_sdr_url"],
            "path": fam[i]["path"],
        })
    by_id = {r["id"]: r for r in rows}

    # --- presentation suggestion (what a phone shows at 1:1 device pixels) ---
    for r in rows:
        w, h = int(r["width"]), int(r["height"])
        longest = max(w, h)
        if r["stratum"] in PHOTOLIKE:
            # Lossy origins are only shown downscaled >= 3x, so source JPEG/HEIC
            # artefacts do not sit in the reference the observer compares against.
            cap = longest // 3 if r["lossy_origin"] == "1" else longest
            rungs = [x for x in (256, 512, 768, 1024) if x <= cap]
            r["presentation"] = "scaled:" + ",".join(map(str, rungs)) if rungs else "scaled:none"
        else:
            side = min(1024, w, h)
            r["presentation"] = f"native-window:{side}"

    # --- picks ---
    for s, (n_train, n_test) in TARGETS.items():
        for bucket, want, label in (("train", n_train, "batch1-train"), ("test", n_test, "reserve-test")):
            used: set[str] = set()
            picked = 0
            for tier in ("A", "B", "C"):
                if picked >= want:
                    break
                pool = [r["id"] for r in rows
                        if r["stratum"] == s and r["grade"] == tier and r["squintly_split"] == bucket
                        and r["presentation"] != "scaled:none"]
                for i in fps_order(pool, feats):
                    if picked >= want:
                        break
                    if by_id[i]["group_id"] in used:
                        continue
                    by_id[i]["pick"] = label
                    used.add(by_id[i]["group_id"])
                    picked += 1
            if picked < want:
                print(f"  ! {s}/{bucket}: {picked} of {want} (stratum is short in this bucket)")
    for r in rows:
        if not r["pick"]:
            r["pick"] = "excluded" if r["grade"] == "X" else "pool"

    full = a.full_out or Path("/mnt/v/output/imazen-26-variants") / set_dir.name / "candidates_all.tsv"
    full.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys())
    with open(full, "w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(r[c] for c in cols) + "\n")
    # The committed manifest carries the picks only; urls and paths join from
    # manifests/split_map.tsv and variant-sets/png-v3-index.tsv by id.
    slim = ["id", "pick", "stratum", "grade", "squintly_split", "canonical_split", "group_id",
            "presentation", "lossy_origin", "hdr_available", "license", "note"]
    out = set_dir / "selection.tsv"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\t".join(slim) + "\n")
        for r in rows:
            if r["pick"] in ("batch1-train", "reserve-test"):
                fh.write("\t".join(r[c] for c in slim) + "\n")
    print(f"wrote {full}")
    c = collections.Counter((r["pick"], r["stratum"]) for r in rows if r["pick"] in ("batch1-train", "reserve-test"))
    print(f"wrote {out}")
    for s in TARGETS:
        print(f"  {s:20s} train {c[('batch1-train', s)]:3d}  test {c[('reserve-test', s)]:3d}")
    print("  total", sum(v for (p, _), v in c.items() if p == "batch1-train"),
          sum(v for (p, _), v in c.items() if p == "reserve-test"))
    multi = sum(1 for v in groups.values() if len(v) > 1)
    spans = sum(1 for v in groups.values() if len({fam[i]["split"] for i in v}) > 1)
    print(f"  union families: {multi} multi-member, {spans} span the canonical family split")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
