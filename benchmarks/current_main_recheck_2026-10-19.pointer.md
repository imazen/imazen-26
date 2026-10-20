# Current-main recheck, 2026-10-19

The unified CLI cannot inventory IMI: all 4,300 IMI routes return typed
unsupported results, tracked in [zqi issue 73](https://github.com/imazen/zqi/issues/73).
The private format remains excluded from publication. Its separate imij and
imij-oracle pixel, metadata and gain-map checks pass all 4,300 files.

## Evidence

Checked on dev:
`/mnt/v/output/imazen-26/current-main-recheck-2026-10-19/`.
NAS mirror:
`/mnt/tower/output/imazen-26-current-main-recheck-2026-10-19/`.
The mirror contains 4,751 regular files, excludes Cargo targets, and preserves
render-layer symlinks. `archive-verification.json` records three randomly
selected files checked by SHA-256 against their sources. Additionally,
`final-evidence-sha256.json` records eight core result/receipt files whose
hashes were checked on both copies. These are measurement artifacts, not
additional published corpus files.

The tools use the compatible main-source cohort with archmage/magetypes
0.9.31-beta.1 (Git main `da0ed5de`) and zentone 0.2.0. The standalone
`beta-build/` and CLI source graphs retain their own locks and overrides.
`beta-build/render-v4-build.json` and `jxl-decode-check-build.json` record
the binary, lock, metadata and local Rust/manifest hashes. Frozen source
snapshots were compared with published main before the final build.
Reference executables and their SHA-256s are retained under `reference-tools/`.

## Stored-file results

| check | measured coverage | result |
|---|---|---|
| Independent PNG readers | 4,300 PNG files | pass |
| Native PNG reader | 4,300 PNG files and 76 gain maps | pass |
| JXL native/jxl-rs and libjxl 0.12 | 4,300 JXL files | pass |
| Lossless JXL/PNG twins | 3,668 lossless files, three JXL readers | identical samples |
| Gain maps | 76 bundles, three readers | metadata and displayed alignment agree |
| Native HDR reconstruction | 76 files | pass existing thresholds |
| IMI and independent oracle | 4,300 files and 76 gain maps | pass |
| Structural JXL/libjxl check | 4,300 files | pass |
| Byte scan | 15,167 files | zero unallowed findings; four existing allowed rows |
| Unified CLI inventory | 15,091 routes | 10,791 successes; 4,300 unsupported IMI routes |
| Colour and HDR oracles | all configured wide-gamut and 76 HDR files | zero failures |

The regenerated `render-redo5/decoded-xxh3.tsv` is byte-identical to the
post-redo-5 table: SHA-256
`1c3b4d68d02ba6ea891658b9e77e06005de64dd93aa70e384d0e26ebc55ba14b`.
JPEG-in-JXL pixel rounding remains reader-specific; byte-exact JPEG rebuilding
and per-reader hashes are separate checks. No cross-reader equality is claimed
for the 632 JPEG-in-JXL files.

The focused zencodecs CICP test passes on the main-source graph. The earlier
locked graph loses AVIF primaries ([zenpipe issue 103](https://github.com/imazen/zenpipe/issues/103));
the TIFF F32 predictor fixture fails on both codec paths
([zenextras issue 52](https://github.com/imazen/zenextras/issues/52)).
Neither assertion was relaxed. Graph changes alone do not identify which
dependency caused the AVIF difference.

## Encoder samples and review candidates

Thirteen image IDs cover 28 layer groups, including three HDR sources:
61 PNG/JXL/gain-map encodes and 29 additional IMI encodes. The final sample
comparison reports nine JXL encoded-byte changes, zero size changes, zero
reported pixel changes and zero gain-map metadata changes. The JXL differences
are the intended Relative-intent header changes, including the embedded gain
maps in two source-colour samples. Three independent JXL readers checked
29 files in both stored and sample trees: 174 rows, no changed samples or gain
maps. All 29 IMI samples are byte-identical. The final published-main renderer
is byte-identical to the renderer used for the final 61 encodes.

The owner authorized code-only intent fixes; these samples did not replace
stored files. The separately authorized 24-file JXL redo 5 is already part of
the stored render.

The Task 5 decoder/wrapper candidates were also compared over all 4,300 JXL
files: 8,600 per-reader rows, zero changed rows including metadata and gain-map
fields. `decoder-candidate-build/readback/comparison.json` has SHA-256
`78c09133d026ff082fb553e17f95e2a37124e1fcf2618c7634c23d0e483300fa`.
The behavior and layout changes remain review PRs:
[decoder 65](https://github.com/imazen/zenjxl-decoder/pull/65),
[decoder 66](https://github.com/imazen/zenjxl-decoder/pull/66),
[wrapper 30](https://github.com/imazen/zenjxl/pull/30).

## Resource records

Each command ran under the shared build lock and run-heavy. Full logs and
commands are in the mirrored `logs/` directory. These are run costs, not codec
speed comparisons.

| run | seconds | run-heavy peak RSS | minimum available MiB |
|---|---:|---:|---:|
| IMI full check | 1,167 | 2.31 GiB | 46,415 |
| Byte scans | 970 | 0.16 GiB | 48,439 |
| Colour/HDR oracles | 3,844 | 20.38 GiB | 28,716 |
| JXL structural check | 299 | 0.06 GiB | 45,210 |
| Task 5 candidate readback | 1,099 | 1.81 GiB | 46,598 |

The colour-oracle run exposed nested reader/BLAS thread multiplication;
the repeatable recipe now bounds those subprocess thread pools. The JXL
structural reader calls explicitly use one libjxl thread.
