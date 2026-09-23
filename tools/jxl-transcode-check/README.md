# jxl-transcode-check

Validates lossless JPEG → JXL transcodes of corpus JPEGs: size, byte-exact rebuild from
the `jbrd` box, ICC carry-over, EXIF orientation against the JXL header, gain-map
survival, and pixel agreement between a plain JXL decode and zenjpeg's decode of the
original. Results and findings: `benchmarks/jpeg_in_jxl_validation_2026-09-22.md`.

Two builds share `src/main.rs`:

| manifest | crates | binary |
|---|---|---|
| `Cargo.toml` | published: jxl-encoder 0.3.1, zenjxl-decoder 0.3.10, zenjpeg 0.7.1 (magetypes pinned to 0.9.20 in `Cargo.lock`) | `target/release/jxl-transcode-check` |
| `head/Cargo.toml` | git revisions: jxl-encoder `8da452cf`, zenjxl-decoder `940d2c51`, zenjpeg `8f703a6e`; enables the `head` feature | `head/target/release/jxl-transcode-check-head` |

```sh
cd tools/jxl-transcode-check
~/work/zen/scripts/run-heavy -- cargo build --release --locked
(cd head && ~/work/zen/scripts/run-heavy -- cargo build --release --locked)

# input: one `id<TAB>path` per line; output: one TSV row per input
target/release/jxl-transcode-check list.tsv out.tsv
```

Each process is one file at a time; split the list and run several for a corpus pass.
A failed step fills the `error` column instead of dropping the row. `recon_exact` is
`1`, `0` (rebuilt but different; see `recon_first_diff` / `recon_diff_ctx`),
`rebuild-failed` (a `jbrd` box is present but zenjxl-decoder returned nothing) or
`no-jbrd`.
