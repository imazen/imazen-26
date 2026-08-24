# fleetbench-anchor@2026-08-24

- **Files:** 242 renditions, 0.184 GP total.
- **Selection:** stratified by content_class, 3 per class across all 21 classes (padded
  to 64 from the largest class) from the TEST split (manifests/test.tsv) — chosen
  deliberately from `test` because nothing consumes test-split renditions in any live
  training run, so this benchmark corpus can be re-generated/re-scored freely with zero
  collision risk. NOT a k-means/farthest-point pick (fleetbench_reps_2026-08-24.tsv uses
  the krep-* column schema `--select reps` expects, but the row selection itself is
  stratified-random by class, not clustered).
- **Render:** kernel=lanczos, generator=make_variant_set.py@c4b8d46; split=test; crops=none.
- **Purpose:** frozen fleetbench workload for the Nomad-migration mission's measured gates
  (G-P0/G-N1/G-P2/G-P3/G-T1 — zenmetrics `docs/status/fleet-orchestration-2026-08.md`).
  Declared through the normal zenfleet job system: encode (zenjpeg/zenavif/zenjxl/zenpng,
  Step5 q-grid) + GPU-score (ScoreFile) + CPU-score kinds, same workload for every A/B.
- **Storage:** /home/lilith/tmp/fleetbench-variants (register mirrors here when synced).
- **Consumers:** zenmetrics fleetbench gates (2026-08-24, in progress).
- **Status:** active.
