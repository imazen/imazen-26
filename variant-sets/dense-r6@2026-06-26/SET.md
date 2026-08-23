# dense-r6@2026-06-26 — DEPRECATED (train-biased; local bytes lost)

- **Was:** 2,000 renditions / 672 origins built from `krep-500-even` reps plus
  `v2_src<NNNN>` renditions (imazen-26-png-v2 lineage).
- **Why deprecated:** train-biased by construction (560/672 even; only 64 validate +
  48 test origins — too thin for held-out evaluation). Declared superseded in
  CLEAN_PICKER_PROGRAM.
- **Bytes:** `/mnt/v/output/dense-corpus-r6-2026-06-26/` is **empty as of
  2026-08-23** and no R2/Tower mirror is documented — the rendition BYTES are
  considered lost. Names + features survive in the derived pareto parquets
  (`/mnt/v/backups/home/picker-pp/train/zenjxl_lossy_dense.*.parquet`) and in
  `s3://zentrain/canonical/2026-06-27/zenjxl_lossy/`.
- **Consumers (historical):** the `zenjxl_lossy` provisional canonical dataset and
  the committed `zenjxl_lossy_picker_v0.1_dense-r6-evenodd_2026-06-26.bin`.
- **Status:** deprecated + unreproducible. Do not extend; supersede its consumers
  per the training roadmap (jxl-lossy picker v0.2 from a registered set).
