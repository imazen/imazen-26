# cleanpicker-ladder11@2026-06-26 — the SDR picker corpus (all three splits)

- **Files:** 4,497 PNGs = 414 source images × ≤11-rung log ladder (64…1024
  longest-side, dense in the starved small/medium band; tiers 224/448/840),
  `o_<id>.png.scale<W>x<H>.png` naming era.
- **Selection:** sources = the 414 distinct images of `krep-500@2026-06-14`
  (all-parity k-means — includes odd ids, which is what gives this set real
  validate/test coverage: renditions split 2,307 train / 1,382 validate / 808 test
  by the canonical id rule). Ladder + provenance: zenmetrics
  `scripts/picker/gen_dense_corpus.py`; `selection.tsv` = its `_provenance.tsv`
  (rendition → source file + source sha256 + dims + tier).
- **Render:** PIL **Lanczos** (recorded honestly — predates the
  one-renderer rule; kernel differs from sdr-fps-1p5gp's Mitchell+sharpen).
- **Storage:** `/mnt/v/output/clean-picker-corpus-2026-06-26/` ·
  `s3://codec-corpus/clean-picker-corpus-2026-06-26/` (public) ·
  refs `s3://zentrain/refs/clean-picker-corpus-2026-06-26/` (fleet
  `ZEN_CORPUS_PREFIX`).
- **Consumers:** the canonical picker lineage — canonical-picker-2026-06-27 sweeps →
  2026-07-01-zensimA (5.74M rows) → tbig/ext 720/924/944 backfills → jxl-lossless
  re-canonical 2026-07-03 → jxl-lossy-hqfill(-A) → fill4 sidecars; committed
  zenjpeg v0.4/v0.5 + jxl-lossy cleansplit picker bins; the zensim bigcodec legs.
- **Footprint (measured 2026-08-23):** 1.02 GiB PNG as stored; lossless JXL 0.67 GiB
  (0.656), lossless WebP 0.69 GiB (0.673) — `../../benchmarks/lossless_recompress_2026-08-23.md`.
- **Status:** superseded by [`cleanpicker-ladder11@2026-08-23`](../cleanpicker-ladder11@2026-08-23/SET.md) for new consumers; existing sha256 references stay valid against these bytes.
