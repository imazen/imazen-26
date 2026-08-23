# sdr-fps-1p5gp@2026-06-14 — SDR training renditions (budget-first FPS, 1.5 GP)

- **Files:** 1,482 SDR PNGs, downscale-only, `<id>.scale<W>x<H>.png`.
- **Selection:** thumbnail floor (every even-id image ≤128px) + farthest-point
  sampling in content-feature space over 14,211 size candidates, truncated at the
  measured 1.5 GP coverage knee. `selection.tsv` = the priority-ordered FPS manifest
  (`rank, cumulative_gp, …` — any budget is a prefix; rendered rows = the ≤1.5 GP
  prefix). Method: zenanalyze `benchmarks/imazen26_budget_select_2026-06-14.{md,py}`.
- **Split:** train-only BY CONSTRUCTION (even leading ids only). Never source
  val/test rows from this set.
- **Render:** zenanalyze `examples/render_imazen26_variants.rs` — zenresize
  **Mitchell + sharpen** (deliberate production-emulating choice), sources read from
  the png-v1 normalization layer (`/mnt/v/output/imazen-26-png/…`, per
  `selection.tsv` paths).
- **Storage:** `/mnt/v/output/imazen-26-features/train_renditions_2026-06-14/` ·
  R2 `s3://codec-corpus/picker-sweep-2026-06-22/renditions/` (1,482 objs) ·
  refs `s3://zentrain/refs/train-renditions-2026-06-14/` (**1,455-file subset** =
  this set minus its 27 >16 MP renditions — the avifgen exclusion, verified: exactly
  27 rows in `selection.tsv` exceed 16 MP).
- **Consumers:** avifgen encode corpus (→ zensim wave-12 `train_944`/`eval8_944`),
  picker-sweep-2026-06-22 datagen sweeps, the 1,482×97 SDR feature TSV,
  SCORING_DATA_2026-06-24.
- **Footprint (measured 2026-08-23):** 1.61 GiB PNG as stored; lossless JXL 0.79 GiB
  (0.487 — the large FPS-selected renditions dominate), lossless WebP 0.87 GiB (0.539)
  — `../../benchmarks/lossless_recompress_2026-08-23.md`.
- **Status:** active. Gap: png-v1-sourced (v3 is the current public layer) —
  pixel-equivalence v1↔v3 unverified; a successor set should render from v3.
