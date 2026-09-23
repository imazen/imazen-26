# Split-leak audit: what the family split still misses (2026-09-22)

Extends `split_crossid_dupes_2026-08-27.md`, whose provenance-derived families became
`manifests/split_map_family.tsv`. That map covers three folders — patents (74 ids),
plots (105), web screenshots (370) — and keys web captures by a normalized
capture-job slug. This audit measured, over all 2,160 ids, what related content still
lands in more than one bucket of the family split. Everything below was computed from
this repo's manifests except where a file outside it is named.

## 1. Byte-identical files under two ids

`exact_dup_groups_2026-09-22.tsv`: **11 groups, 22 ids** share a `sha256` in
`manifests/{train,validate,test}.tsv`. Ten are web screenshots, one is an AI product
render. **7 of the 11 span buckets under the family split** (6 under the plain rule;
the family re-bucketing split one more pair). Example: `8210` (test) and `8212` (train)
are the same file.

Cause: the same URL was captured by two capture jobs with different slugs
(`nps-grand-canyon` / `nps-grca`, `usgs-main-home` / `usgs-home`, `nps-yose` /
`nps-yosemite`, …). The slug normalizes to different family keys
(`npsgrandca` / `npsgrca`), so the family split cannot see that they are one page.
The `url` column in `8100-lilith-web-screenshots/MANIFEST.tsv` can: grouping by
`url` + page catches all of them.

## 2. Photo bursts

The id rule alternates consecutive shots across buckets, and the family split does not
cover the photo folders. 238 of the 319 photos in 1000–1600 carry a capture timestamp
in their filename; **149 pairs were taken within 10 minutes of each other, and 107 of
those pairs straddle buckets.** Not every same-session pair is a near-duplicate (a
glass exhibit photographed piece by piece is a series, not a burst), but many are.
Confirmed by eye on 200-px contact sheets:

| pair | seconds apart | buckets |
|---|--:|---|
| 1049 / 1050 (Seine) | 2 | test / train |
| 1019 / 1020 (Space Needle) | 12 | test / train |
| 1026 / 1027 (turtle) | 42 | train / test |
| 1476 / 1477 (sunset) | 97 | train / test |
| 1461 / 1462 (clouds from the air) | 134 | validate / train |
| 1529 / 1530 (whale tail) | no timestamp | test / train |
| 1517 / 1518, 1520 / 1521, 1508 / 1509, 1442 / 1553, 1470 / 1549 | — | cross-bucket |

`variant-sets/squintly-candidates@2026-09-22/families.tsv` unions bursts (≤120 s apart)
with the pairs seen by eye. Under that key, **36 photo families straddle the family
split.**

## 3. Multi-page documents

- **NOAA:** keyed by storm/report id (`al092024` …), **all 15 reports have pages in more
  than one bucket**. zensr's descriptor-based key (`tools/corpus_split.py`, descriptor
  minus `_pNN`) finds 12 of 20. Pages of one report share typography and layout, not
  content.
- **Web sites:** 35 of 41 sites have captures in more than one bucket. At url + page
  granularity, 7 of 79 groups do: six are the slug aliases above (grca, yell, yose,
  usgs ×2, weather.gov), and the seventh is `local-capture`, a placeholder `url`
  shared by five different terminal screenshots. That one is not a real URL and must
  stay out of any url key.
- The IA works (`6600` + `6800`) and the EPA report were already known cases.

Grouping these by document costs the held-out buckets entirely: zensr measured that
grouping IA by work leaves 6600/6800 with no test bucket at all. So this is a
per-consumer trade, not a defect with one fix. The squintly candidate set keeps page
granularity and records the choice.

## 4. Derived corpora that invent their own split

`/mnt/v/output/nonphoto-picker-corpus-2026-06-26` (502 origins, ids 10000–10501)
copies **349 imazen-26 images under fresh ids** and splits them by the new ids' last
digit. Mapping each row's `source` path back to its imazen-26 id:

| imazen-26 bucket → nonphoto bucket | n |
|---|--:|
| test → train | 26 |
| validate → train | 64 |
| train → test | 34 |
| train → validate | 47 |
| validate → test | 22 |
| test → validate | 24 |
| unchanged | 132 |

A model trained on its train split has seen 26 imazen-26 test images, and one trained
on imazen-26 train is scored on 34 of its own training images there. Its README's "0
duplicate-content groups" is true within that corpus only. This breaks
`manifests/README.md`'s rule that derived datasets inherit an image's bucket.

## 5. Entries with no stimulus value

- 7 bot-blocked captures showing "Access Denied": every `bls.gov` capture (8103, 8162,
  8222, 8274, 8333, 8396, 8397).
- 5 broken-layout captures, content squeezed into one narrow column or mostly empty
  (8285, 8289, 8417, 8423, 8425).
- 4 blank page scans, paper show-through only (6058, 6088, 6825, 6826).
- 12 `lkml.org` captures of its "Not Found" page with a patch list below. They are
  legitimate dense text, but not the page the URL names.

## Stakes

The 2026-08-27 audit measured the family leak's effect on zensim eval SROCC at ≈0
(median Δ +0.0043). That result stands for metric evaluation. Two uses weigh it
differently:

- **Paid human studies.** A near-duplicate spends observer time on a question the study
  has already asked, and a twin across the train/confirm line contaminates a
  confirmatory claim that must stand on its own.
- **Held-out claims from derived corpora.** Section 4 is not a near-duplicate question:
  those are the same images, in the other bucket.

## Recommended fixes (not applied here)

1. Extend `scripts/derive_sharing_provenance.py` with four more family keys — `sha256`,
   `url` + page, photo bursts (timestamp gap plus an eye-checked pair list), and NOAA
   report id — and emit a successor `split_map_family` manifest rather than rewriting
   the current one. Every consumer re-derives from it.
2. Adopt zensr's `tools/corpus_split.py` keys into that successor, so one definition
   exists instead of two that disagree.
3. Re-key `nonphoto-picker-corpus` rows by imazen-26 id, inheriting the bucket, before
   anything else trains on it.
4. Mark the 16 zero-value entries in section 5 in the per-folder manifests (or retire
   them through the corpus's normal `nope/` path), so consumers stop sampling them.
