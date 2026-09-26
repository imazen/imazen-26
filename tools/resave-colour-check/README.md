# resave-colour-check

Finds a re-saved crop inside its camera original and measures which colour handling the
re-save applied. Both files are decoded by zencodecs with orientation applied, the crop
offset is found on a luma grid, and the crop is compared with the original under three
hypotheses: values kept (profile dropped), converted wide-gamut → sRGB, and treated as
sRGB then converted → wide gamut. The pixels where the hypotheses differ by more than 8
levels decide; the right hypothesis sits at JPEG-noise error with no bias.

```
cargo build --release
target/release/resave-colour-check <original.jpg> <crop.jpg> [--from p3|adobe]
```

Used on imazen-26 id 1214 (2026-09-26); see `benchmarks/signal_index_2026-09-24.md`.
Cargo.lock is gitignored (dependency pins match `tools/corpus-thumbs`).
