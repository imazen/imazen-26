# hdr-grid-15scale@2026-06-14 — HDR multi-scale grid

- **Files:** 1,140 16-bit PQ PNGs = 76 HDR gain-map origins × 15 aspect-preserving
  scales (~96×128 … 3072×2304, log-spaced — covers the tiny bucket by design).
- **Selection:** all 76 HDR origins (no subsetting — the HDR estate is small);
  density carried by the 15-scale ladder.
- **Render:** zenanalyze `examples/extract_hdr_size_grid.rs` — **linear-light**
  resample before PQ re-encode, cICP-correct. No per-file selection.tsv exists
  (renderer + args are the provenance; recorded gap).
- **Storage:** `/mnt/v/output/imazen-26-hdr-grid-2026-06-14/` (7.8 GB) ·
  refs `s3://zentrain/refs/imazen-26-hdr-grid-2026-06-14/` · Tower mirror.
- **Consumers:** hdrgrid multi-codec corpus (102,600 cells + score + 193k diffmap
  waves), kadis-hdr-2026-07-13 (11,400 cells), zensim `hdr_v3mix`@944 leg
  (58-origin subset), the HDR feature TSVs.
- **Footprint (measured 2026-08-23):** 7.72 GiB PNG as stored; lossless JXL 4.81 GiB
  (0.624). Lossless WebP N/A — VP8L is 8-bit-only and this set is 16-bit PQ
; oxipng -o 4 ratio 0.875
  — `../../benchmarks/lossless_recompress_2026-08-23.md`.
- **Status:** superseded by [`hdr-grid-15scale@2026-08-23`](../hdr-grid-15scale@2026-08-23/SET.md) for new consumers; existing sha256 references stay valid against these bytes.
