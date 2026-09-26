# corpus-thumbs

Renders thumbnail sprite sheets of corpus sources for the browsable contact sheet:
zencodecs decode (orientation applied), conversion to sRGB with zenpixels-convert (the
colour class comes from the signalling index, since zencodecs misses HEIC tile colour),
Lanczos resize with zenresize into 256×256 cells, 100 cells per WebP sheet.

```sh
cd tools/corpus-thumbs
~/work/zen/scripts/run-heavy -- cargo build --release
target/release/corpus-thumbs list.tsv sheet_00   # list: id<TAB>path<TAB>srgb|p3|adobe
```

Writes `sheet_00.webp` and `sheet_00.tsv` (cell and thumbnail size per id). Output of the
2026-09-25 run: `/mnt/v/output/imazen-26/gallery-2026-09-25/` (with the page, its data and
`SHA256SUMS`). `DEBUG_DECODE=1` prints each decode's pixel descriptor and channel means.

Pins match `tools/corpus-signal-probe`. The resolved `Cargo.lock` (46 KB) lives next to
the output as `corpus-thumbs.Cargo.lock`.

Known gap: the three Galaxy S23 Ultra DNGs (1444, 1455, 1458) are JPEG-compressed
LinearRaw files that zenraw decodes to wrong colours in both of its backends
(imazen/zenraw#17), so their thumbnails are unusable.
