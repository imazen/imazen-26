# lossless-bench-43@2026-06-10 — jxl-encoder's lossless benchmark set (legacy import)

Registered 2026-09-22 from jxl-encoder `benchmarks/lossless_bench_set_2026-06-10.tsv`
(+ `.meta`, committed there as `1b40e5e8`). `selection.tsv` is a byte copy of that
TSV. Nothing was re-selected or re-rendered.

- **Rows:** 43 images across 23 strata; 13 are `tier=core`. 30 are PNG originals, 13 are
  JPEG originals.
- **Selection:** per-stratum k-means on zenanalyze content features, the member
  nearest each centroid (the `.meta` records the pipeline, candidate pool and fixed
  seed). Pool: corpus PNGs ≤16 MP (1,603 candidates) for the v1 30 picks, plus 13
  picks from the 10 JPEG photographic strata in v2.
- **Bench inputs:** the `bench_input` column is the file a harness feeds, pinned by
  `bench_sha256`. PNG picks use the corpus file. JPEG picks were pre-decoded to
  metadata-stripped 8-bit PNGs with ImageMagick (`convert -strip`, no auto-orient,
  ICC/EXIF dropped) under `/mnt/v/input/jxl-encoder/lossless-bench-imazen26-png/`.
  That is foreign software and predates the 2026-09-02 imazen-only rule. Those 13
  inputs also carry no colour profile and are in stored orientation. Fine for
  benchmarking bytes and speed; not a colour-correct or tuning source.
- **Split:** spans all buckets under the family-aware map: 26 train, 13 validate,
  4 test. A **benchmark set**: do not train on it, and do not quote numbers measured on
  it as held-out results.
- **Storage:** corpus files (R2 `imazen-26-unprocessed/`) plus the 13 decoded PNGs at
  the path above; no R2 or tower mirror of those 13 is recorded.
- **Consumers:** jxl-encoder lossless and perf benchmarks (`benchmarks/README.md`
  there), including its paired cjxl comparisons.
- **Status:** active.
