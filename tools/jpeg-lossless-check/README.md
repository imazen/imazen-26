# jpeg-lossless-check

Checks lossless JPEG transforms on corpus JPEGs at the coefficient and pixel level:
progressive→sequential re-encoding and EXIF-orientation rotation (zenjpeg's `lossless`
module), plus the JPEG-in-JXL transcode of each result. Results and findings:
`benchmarks/layer_repos_2026-09-25.md`.

```sh
cd tools/jpeg-lossless-check
~/work/zen/scripts/run-heavy -- cargo build --release --locked
target/release/jpeg-lossless-check list.tsv out.tsv   # list: id<TAB>path per line
```

Per row: whether the sequential re-encode keeps the coefficients and zenjpeg's pixels, and
whether its JXL rebuilds it; for rotated files, the rotation mode (`perfect` or `trim`),
rows/columns lost, and the difference from the pixel-rotated decode of the original
through zenjpeg and through zenjxl-decoder, overall, within 16 px of an edge and in the
interior. The `fixq_*` columns repeat the comparison with the output's quantization tables
transposed (the fix for zenjpeg #205). `DIAG=1` prints where differences sit in the block
grid; `ALL_TRANSFORMS=1` runs all seven transforms on each file (needs an MCU-aligned file).

Pins match `tools/jxl-transcode-check/head` (zenjpeg `8f703a6e`, jxl-encoder `8da452cf`,
zenjxl-decoder `940d2c51`).
