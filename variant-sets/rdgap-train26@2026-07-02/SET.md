# rdgap-train26@2026-07-02 — zenavif's RD-gap representative sample (legacy import)

Registered 2026-09-22 from what zenavif built and has used since July; nothing was
re-rendered. The registration exists so consumers can cite a set id instead of a path.

- **Files:** 24 PNG renders at 1,024 px longest edge (`files.tsv`, sha256 per file).
- **Selection:** k-means, K=24, over 94 zenanalyze content features
  (`imazen26_features_2026-06-23.parquet`, `full` + `native` rows), the member nearest
  each centroid, **train origins only** by the last-digit rule. Selector adapted from
  zenmetrics `scripts/sweep/knobablation_firstcut_select.py`. Per-pick cluster and
  cluster size are in `selection.tsv`.
- **Render:** `vipsthumbnail --linear`, 1,024 longest edge, downscale only, from the
  v1 PNG layer (`/mnt/v/output/imazen-26-png/`). libvips is not imazen software. The
  set predates the 2026-09-02 imazen-only rule, so do not use it to produce new
  training data; it remains valid as the reference for the RD-gap results already
  measured on it.
- **Split:** built train-only, but three picks are **validate under the family-aware
  map** introduced 2026-08-27: 8268 and 8414 (web captures whose site family starts on
  a validate id) and 6096 (a patent page whose scan-variant family does). A consumer
  using `split_map_family.tsv` should treat those three as validate.
- **Storage:** `/mnt/v/output/rd-gap-train26-2026-07-02/` with its `_MANIFEST.json`
  (build commit "zenavif@c6fb345e-era"). No R2 or tower mirror is recorded.
- **Consumers:** zenavif `scripts/rd_gap/sample_images_train26.tsv` (committed
  `cd041083`) and the RD-gap investigations in zenavif's CLAUDE.md that cite these ids
  (for example 8414, 1236, 6096, 6018 and 9100).
- **Status:** active (legacy render).
