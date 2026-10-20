# Adobe RGB to Display P3, 2026-10-20

Owner decision: replace the two Adobe RGB renditions in the P3 family with actual
Display P3 conversions. IDs 13005 (validate) and 13006 (train) use relative
colorimetric conversion through zenpixels-convert, gamut clipping, and lossless
encoding of the converted 8-bit samples. Original JPEGs and sRGB renditions remain
unchanged. The private IMI twins and their two affected sets follow the new PNGs.

Published revision:
https://github.com/imazen/imazen-26-jxl-p3/releases/tag/v2026.10.20

The catalogue commit is `be5cc5f2606ea58cc3cf695c7785678b3c053819`.
Its `BRANCHES.tsv` pins train, validate and test. All twelve CI jobs pass on those
four exact branch commits (Linux, Windows ARM64 and macOS ARM64). Anonymous
GitHub downloads match both replacement hashes. The previous tag is unchanged;
the other three published repositories retain their previous main commits.

| ID | clipped pixels | JXL bytes | encoded SHA-256 |
|---|---:|---:|---|
| 13005 | 49 | 4657471 | `2ef3b61f8f0b467c920ff214f8cac516b7811f53be7ded451a8a43cc83c86087` |
| 13006 | 153 | 5286525 | `66ce81ddce9a12a5daa793c656d8cbd532d0d51686ddaf3a19d12aa06885f3b7` |

Both the independent matrix calculation and direct LittleCMS with interpolation
optimization disabled differ by at most one 8-bit level. ImageMagick's optimized
LittleCMS path differed by two levels in the initial diagnostic; its output is
not used to encode any published file. zenjxl, jxl-rs and libjxl reproduce the PNG
twins exactly. All structural, inventory and byte-scan checks pass for the
replacements. The full report passes 4,300 JXL files and all 3,670 lossless twins;
only eight of the 17,276 bitmap rows change. New full-table SHA-256:
`a998604d395999e653b4cc1de72dbb424fbea8478081114cf4e2087c187bf859`.

The two new P3 PNGs and JXLs have 84 reader-census observations. Historical rows
remain available; the public view selects current encoded hashes. The full alias
map still covers 8,600 paths. Previous files, reports, inventories, tables and
archives are retained beside their replacements.

Evidence checked on dev:
`/mnt/v/output/imazen-26/p3-conversion-2026-10-20/`.
The mirror is `/mnt/tower/output/imazen-26-p3-conversion-2026-10-20/`.
`tool-build.json` records the renderer, lock and package source fingerprints;
`dependency-snapshots.json` records the committed dependency snapshots.
Renderer source: `bcea0abc1210ac589ada62c80df9dca177f13ff7`;
binary SHA-256 `eb75023eda257d5dd71966031bde9d0c89da9c27dbbfa1f1867318aab41471b1`;
Cargo.lock SHA-256 `7b2dc730c04c842156ded3a266dceea48b9aa7664aa5366e8d8571eb3af0e089`.

Resource logs: render and initial diagnostics 187 s, peak RSS 1.96 GiB;
independent conversion, readback, inventory and IMI checks 27 s, 1.30 GiB;
publication 220 s, 0.14 GiB; census 124 s, 0.18 GiB. Full `run-heavy` lines
are retained in the evidence logs; these are separate measured runs.

The retained sRGB twins were made directly from the Adobe RGB source. Converting
these new, quantized P3 samples to sRGB differs from those twins by at most three
levels (native `compare` diagnostic). Chromium/WebKit comparisons against the
unchanged twins differ by three or four levels, leaving six visible comparison
findings in the census. These observations are retained alongside the independent
ICC checks and exact lossless readback results.

Review deployment `44abf1c2` passes the browser check: 2,112 tiles, working full
resolution, HTTP 404 for missing paths, and 197,876 unique downloaded bitmap
identities with zero duplicates. The public index matches the local deployment;
both converted tiles state Display P3 and all eight new native hashes match.
Downloaded hash-table SHA-256:
`e860b2a9b2846a47bc9c5e2d233d1659cc9b5c1135988e2ff1dcf248c2f7f77d`.

https://imazen-26-review.pages.dev/

Both affected private sets were rebuilt and every entry read back: train has
1,103 entries and validate 664. Their previous versions remain in
`imi-sets/before-p3-conversion-2026-10-20/`. Refresh/readback/promotion measured
416 s, peak RSS 0.15 GiB; site build/deployment 142 s, 0.58 GiB; browser check
8 s, 0.34 GiB. Full resource lines are retained with the evidence.
