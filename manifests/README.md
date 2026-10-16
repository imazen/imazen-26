# imazen-26 canonical split manifests

**THE RULE** (deterministic, no seed; identical to zenmetrics
`scripts/picker/origin_split.py`): the **last digit of the 4-digit image id** decides
the bucket —

| last digit | bucket |
|---|---|
| 0, 2, 4, 6, 8 | `train` |
| 1, 3, 5 | `validate` |
| 7, 9 | `test` |

**The v4 export uses the successor family map instead.** Its repositories and every
exported file's provenance bucket each image by `split_map_family_v2.tsv` (owner decision
S1, 2026-10-15), which keeps related images in one bucket; for 270 of the 2,115 ids that
differs from the last digit.

Every derivative of an image — resize, crop, re-encode, feature row, metric row —
**inherits the image's bucket**. Datasets never invent their own split; they join on
`id` (the leading 4 digits of every corpus filename and of every spec-conformant
variant name).

## Files

| file | rows | what |
|---|---|---|
| `split_map.tsv` | 2,115 | bare `id → split` map (plus class + path) |
| `train.tsv` | 1,062 | full rows for the train bucket |
| `validate.tsv` | 642 | full rows for the validate bucket |
| `test.tsv` | 411 | full rows for the test bucket |
| `split_map_family_v2.tsv` | 2,115 | successor family map (`scripts/emit_family_split_v2.py`): the same lowest-id rule over wider families: patent page (1-bit original + rescans, by `patent_page`), url + page, sha256 and photo bursts. It is computed again on the final membership after the removal review |
| `retired.tsv` | 45 | ids removed from the corpus: path, sha256, date, reason, and the id a duplicate repeats |

Columns: `id, split, content_class, path, width, height, format, bytes_manifest,
bytes_actual, sha256, raw_url, png_v3_sdr_url, png_v3_hdr_url`. `sha256`/`bytes_actual` are computed
from the canonical files at generation time (`bytes_manifest` is the historical
`CORPUS-MANIFEST.tsv` value, which can lag after metadata rewrites). `raw_url` serves
the original bytes; `png_v3_sdr_url` / `png_v3_hdr_url` the codec-test-ready PNG
renders.

**Never derive a render URL from `path`.** The corpus filename ends in a `_WxH`
token from the *stored* dimensions; the render pass applied EXIF rotation and
named its output by the *rotated* dimensions, so for the 196 images with EXIF
Orientation 5/6/7/8 the two numbers are transposed and an extension swap 404s.
Use the columns, or `variant-sets/png-v3-index.tsv`. An empty value means the
object does not exist (3 rows for SDR; only 76 rows have an HDR companion).

Regenerate:

```
python3 imazen-26/scripts/make_canonical_split.py --repo-im26 imazen-26 --check-urls 14
```

Browsable per-bucket folder views (relative symlinks, no byte duplication) live under
[`../splits/`](../splits/).

## Retired ids

An id in `retired.tsv` has left the corpus and is never reused, so results that cite it
stay unambiguous. Its rows are gone from every manifest and split link; registered variant
sets and dated selections keep it as a record of what they used. Retire with `scripts/retire_ids.py`. The first 11 (2026-10-15)
are byte-identical duplicates: 10 web pages captured twice by capture jobs with different
slugs, and one AI product image filed in two categories. Each group keeps its lowest id.
The family map drops them without re-bucketing anyone; its successor recomputes buckets.

## Supersedes

The pre-2026-08 `manifests/{train,val}.tsv` (an ~86/14 split over PNG-v3 render rows,
built from `picker-sweep-2026-06-22/imazen26_manifest.tsv`, with **no test bucket**)
are **superseded and removed**. Anything trained on them should be re-interpreted
through `split_map.tsv`; rows whose origin id lands in `validate`/`test` here must not
be treated as training data going forward.

## Known R2 drift (probed 2026-08-22)

- ids **9231, 9869, 9874** (renamed during curation): `png_v3` URL live, `raw_url`
  404 — `imazen-26-unprocessed/` still holds the pre-rename objects. Reconciliation
  pass queued.
- ~~id **1433**: `png_v3` 404 (render missing under the current name).~~
  **Resolved 2026-08-30 — misdiagnosed.** The render exists; the manifest URL was
  built by swapping the extension on the corpus name, and 1433 is one of the 196
  EXIF-rotated images whose render name transposes the `WxH` token. The URL
  columns are now generated from `variant-sets/png-v3-index.tsv` rather than
  derived, so this class is gone. Genuinely absent renders: **3** (ids 1444,
  1455, 1458 — the corpus's only DNG originals), which now carry an empty
  `png_v3_sdr_url`.
- The R2 prefixes also hold objects with **no manifest row** (pre-curation working
  material). `CORPUS-MANIFEST.tsv` is the membership oracle; ignore unmanifested
  objects.

## Near-duplicate caution (the id rule does not group these)

The split is by id, so related images with different ids can land in different
buckets. If your task is sensitive to near-duplicate leakage, drop or same-bucket
these enumerable groups:

- `6000-lilith-scans-public-patents`: 3 patents × 3 scan variants of the same pages.
- `5000-national-park-service-brochures`: `color/` + `grayscale/` renders of the same
  brochures.
- `8100-lilith-web-screenshots`: the same URL captured at up to 6 viewports.
- `6600` + `6800` IA scans: illustrations vs text pages drawn from the same 6 source
  works.

Measured 2026-09-22 (`../benchmarks/split_leak_audit_2026-09-22.md`), the family map
(`split_map_family.tsv`) still misses: byte-identical files under two ids (11 groups;
same URL captured under two capture-job slugs), photo bursts in 1000–1600 (consecutive
shots alternate buckets), and multi-page NOAA reports. Group by `sha256`, by the 8100
`url` + page, and by capture timestamp if your task is near-duplicate-sensitive.

1214 was replaced by its camera original on 2026-10-07 (the earlier file was a 3000×3556
crop whose colour a re-save tool had mangled; see `../benchmarks/signal_index_2026-09-24.md`).
Its path is now `…_20240424-123020_4000x3000.jpg`. The dated selections
`imazen26_representatives_K500_2026-06-14.tsv` and `…_K500_even_2026-06-18.tsv` keep the
old path as a record of what was picked, as do the registered variant sets.
