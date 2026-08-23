# krep-500-even@2026-06-18 — within-train re-cluster

- **Rows:** 500 reps / 386 images, 0 odd — 11,902 even-id `(image, crop)` units
  clustered with z-score stats from the train population only.
- **Method:** zenmetrics `scripts/imazen26_recluster_even.py` (replicates the K500
  method exactly, filtered to even ids BEFORE clustering — the fix for the
  hold-out-contamination caveat on `krep-500`).
- **Manifest:** [`../../manifests/imazen26_representatives_K500_even_2026-06-18.tsv`](../../manifests/imazen26_representatives_K500_even_2026-06-18.tsv)
- **Consumers:** dense-r6 sources; even-only sweep planning (HETERO plan).
- **Caveat:** correct for TRAIN-ONLY work; a corpus built solely from these reps has
  no validate/test coverage (the dense-r6 lesson).
- **Status:** active for train-only selection.
