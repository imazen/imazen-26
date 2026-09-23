# corpus-signal-probe

Indexes what each corpus source signals: orientation, ICC profile (named via
`zenpixels::icc::identify_common` and its `desc` tag), CICP, HDR metadata (`cLLI`,
`mDCV`), gain maps (presence, geometry, ISO 21496-1 headroom) and depth maps.
Results and findings: `benchmarks/signal_index_2026-09-24.md`.

Two views per file, because they differ:

- **effective**, from `zencodecs::from_bytes` (zenpipe `6a5b052`): what a zen pipeline
  would assume. Untagged JPEG/PNG come back as CICP 1/13/0/1.
- **signalled**, from each codec crate: `zenpng::probe` (colour chunks), zenjpeg's
  `container::probe` (ICC, MPF, ISO 21496-1, `hdrgm`, SOF type), and heic's
  `ImageInfo`, HEIF container (grid `colr`, else the first tile's; `clli`; `tmap`), full
  probe (gain-map headroom) and auxiliary-image list. Columns `sig_*`, `png_*`,
  `jpeg_*`, `heic_*`, `heif_*`.

```sh
cd tools/corpus-signal-probe
~/work/zen/scripts/run-heavy -- cargo build --release
target/release/corpus-signal-probe list.tsv out.tsv   # list: id<TAB>path per line
```

Git dependencies are pinned to the revisions zenpipe's Cargo.lock resolves at
`6a5b052`. The resolved `Cargo.lock` (46 KB) is kept on block storage, not in git:
`/mnt/v/output/imazen-26-variants/signal-index-2026-09-24/corpus-signal-probe.Cargo.lock`
(sha256 in `SHA256SUMS` there); copy it next to `Cargo.toml` to rebuild the exact graph.
The whole corpus probes in about 5 seconds.
