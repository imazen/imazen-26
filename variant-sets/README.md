# variant-sets — the registry of imazen-26 variant sets

Every scaled/cropped/re-encoded derivative set of this corpus is registered here.
A set = one directory `variant-sets/<name>@<date>/` containing:

- `SET.md` — identity, selection method + parameters, generator + kernel, split
  composition, storage locations, **consumers** (which projects/datasets used it),
  status, known gaps.
- `files.tsv` — `file  sha256  bytes  width  height` for every rendition (the
  integrity oracle; regenerate any mirror against it).
- `selection.tsv` (where one exists) — the ordered/annotated selection record
  (e.g. the FPS priority manifest, the ladder provenance TSV).

**Contract:**

1. A registered set is **immutable**. Fixing a set = registering a successor id and
   marking the old one superseded. Git tags on this repo version corpus + splits +
   registry together.
2. New sets are born registered: generate through
   [`../scripts/make_variant_set.py`](../scripts/make_variant_set.py) (which emits
   the set directory), or import a legacy set with full honesty about missing
   provenance. Density and selection follow
   [`../VARIANTS-SPEC.md`](../VARIANTS-SPEC.md) (v2 task profiles).
3. Bytes live on the object stores, not in git. `SET.md` records every known copy;
   `files.tsv` makes any copy verifiable.
4. Consumers must cite the set id (not a bare path) in their provenance docs.

## Registered sets

| set id | what | files | status |
|---|---|---:|---|
| [`sdr-fps-1p5gp@2026-06-14`](sdr-fps-1p5gp@2026-06-14/SET.md) | SDR training renditions, budget-first FPS @1.5 GP, Mitchell+sharpen | 1,482 | active (train-only by construction) |
| [`hdr-grid-15scale@2026-06-14`](hdr-grid-15scale@2026-06-14/SET.md) | HDR 16-bit PQ, 76 origins × 15 linear-light scales | 1,140 | active |
| [`cleanpicker-ladder11@2026-06-26`](cleanpicker-ladder11@2026-06-26/SET.md) | 414 K-rep sources × ≤11-rung Lanczos ladder, all three splits | 4,497 | active — the SDR picker corpus |
| [`krep-500@2026-06-14`](krep-500@2026-06-14/SET.md) | k-means K=500 (image,crop) representative selection, all ids | 500 rows | active (selection manifest, not renders) |
| [`krep-500-even@2026-06-18`](krep-500-even@2026-06-18/SET.md) | within-train re-cluster of the above | 500 rows | active for train-only work |
| [`dense-r6@2026-06-26`](dense-r6@2026-06-26/SET.md) | 2,000 renditions / 672 origins from K500_even reps | 2,000 | **deprecated** — train-biased AND local bytes lost |

Base layers (1:1 normalizations, not subsets — referenced, not registered here):
`imazen-26-png-v3` on public R2 (current), `-png-v2` (in-code canonical for the HDR
sweep path), `-png` v1 (historical; the FPS renders read their sources from it).

## Who used what (per-project map, reconstructed 2026-08-22/23)

| project / dataset | set consumed | notes |
|---|---|---|
| **avifgen** SDR AVIF corpus (`jobs/avifgen-enc-20260806`, 562,860 jobs → zensim wave-12 `train_944`/`eval8_944`) | `sdr-fps-1p5gp` minus its **27 >16MP** renditions = exactly the 1,455 refs at `s3://zentrain/refs/train-renditions-2026-06-14/` | exclusion verified against `selection.tsv` (27 rows >16 MP in the 1.5 GP prefix); 4 byte-identical rendition pairs dedup'd at declare, all train/train |
| **hdrgrid** multi-codec HDR corpus (`jobs/hdrgrid-enc-20260806`, 102,600 cells) | `hdr-grid-15scale` (refs `s3://zentrain/refs/imazen-26-hdr-grid-2026-06-14/`) | 115-cell zenav1-svt#11 residue enumerated absent-not-failed |
| **kadis-hdr-2026-07-13** (11,400 cells) | `hdr-grid-15scale` | KADIS distortions applied to the HDR refs |
| zensim `hdr_v3mix` @944 leg | `hdr-grid-15scale` (58-origin subset → 38 train / 20 val) | |
| **canonical-picker-2026-06-27** 5-codec SDR sweeps → **2026-07-01-zensimA** (5.74M rows) → tbig/ext **720/924/944** backfills → jxl-lossless re-canonical 2026-07-03 → jxl-lossy-hqfill(-A) → fill4 4-metric sidecars | `cleanpicker-ladder11` (refs `s3://zentrain/refs/clean-picker-corpus-2026-06-26/`, workers' `ZEN_CORPUS_PREFIX`) | the big lineage; encoded variants persist in per-codec sweep tars |
| committed pickers: zenjpeg v0.4/v0.5, jxl-lossy ssim2 v0.1-cleansplit/v0.2 | `cleanpicker-ladder11`-derived datasets | `.bin`s in the codec repos |
| jxl-lossy picker v0.1 (`dense-r6-evenodd`, committed in zenjxl) + `zenjxl_lossy` provisional canonical | `dense-r6` | deprecated lineage — supersede per the roadmap |
| knob-ablation firstcut 2026-06-28 (47 sources) | `krep-500` train subset (16 reps × {256,512,768}) | analysis run |
| picker-sweep-2026-06-22 `renditions/` on R2 (1,482 objs) | mirror of `sdr-fps-1p5gp` | |
| **jxl knobspace-ablation P0 fleet corpus** | **NONE PINNED** — the program doc names a pool ("imazen-26 renditions + screenshots + collections") with no concrete set | the known gap: build + register it via `make_variant_set.py` before the fleet run |
