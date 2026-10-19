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

Finalization uses every codec from git main; `Cargo.lock` records the revisions.
The `enough` git patch keeps the tool and codecs on one cancellation trait source.

```sh
just --justfile tools/jpeg-lossless-check/justfile check
just --justfile tools/jpeg-lossless-check/justfile sequential list.tsv new-results.tsv artifacts
```

The explicit sequential-only mode compares a reconstruction-limited original's bare
coefficient codestream with the transformed JPEG's reconstructible JXL. It records
semantic coefficient/quantization SHA-256s and exact reconstruction/sample checks.
The diagnostic JPEG and JXL bytes are required in this mode and are kept under their
SHA-256 names. Existing artifact bytes must match; an existing output table is refused.
These transformed JPEGs are diagnostic inputs, not export originals.
