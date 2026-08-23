# krep-500@2026-06-14 — k-means representative selection (all ids)

- **Rows:** 500 `(image, crop)` units spanning 414 distinct images; 11-unit crop
  vocabulary (`full` + c50/c25 × {center,tl,tr,bl,br}).
- **Method:** k-means over 84 z-scored CONTENT features (geometry excluded), K at
  the measured knee subject to every-class-≥2 + singleton retention. Record:
  zenanalyze `benchmarks/imazen26_cluster_ablation_2026-06-14.{md,py}`.
- **Manifest:** [`../../manifests/imazen26_representatives_K500_2026-06-14.tsv`](../../manifests/imazen26_representatives_K500_2026-06-14.tsv)
  (K300/K1000 siblings alongside).
- **Caveat:** clustered over ALL ids → 202/414 sources are odd (validate/test). Fine
  as a SOURCE-SELECTION for corpora that will be split afterward (that is exactly
  what made cleanpicker-ladder11 usable); NOT fine as a train-only rep set — use
  `krep-500-even@2026-06-18` for that.
- **Consumers:** cleanpicker-ladder11 sources; knob-ablation firstcut (16 train reps);
  the CLEAN_PICKER re-sweep runbook mandates this one ("NOT the _even one") when
  building future all-split corpora.
- **Status:** active (selection manifest).
