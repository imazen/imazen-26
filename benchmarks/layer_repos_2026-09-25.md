# Originals and colour-normalized layer repositories (2026-09-25)

**Status: proposal.** Five repositories, each with `train`, `validate` and `test` branches:
the originals, and four derived layers in two colour spaces and two lossless formats. This
note sizes them and sets the rendering rules, answers where HDR goes, and records what a
lossless transform of the JPEG sources can and can't do (measured).

Builds on `split_branches_design_2026-09-22.md` (GitHub limits, bucket rule),
`signal_index_2026-09-24.md` (what each source signals) and
`jpeg_in_jxl_validation_2026-09-22.md`.

## The repositories

| repository | holds | GiB, all branches | train / validate / test |
|---|---|--:|---|
| `imazen-26-originals` | the 2,160 source files, byte-identical | 5.47 (measured) | 2.79 / 1.70 / 0.99 |
| `imazen-26-png-srgb` | every image as 8-bit sRGB PNG, orientation applied | ~10.5 | 5.27 / 3.23 / 2.04 |
| `imazen-26-png-p3` | every image as 8-bit Display-P3 PNG, plus 16-bit P3 PQ HDR for 76 | ~14.3 | 7.17 / 4.22 / 2.93 |
| `imazen-26-jxl-srgb` | lossless JXL of the `png-srgb` pixels | ~5.6 | 2.80 / 1.76 / 1.07 |
| `imazen-26-jxl-p3` | lossless JXL of the `png-p3` pixels | ~8.1 | 4.03 / 2.41 / 1.63 |

Buckets follow the family-aware split map. The derived sizes come from the png-v3 renders
(native gamut) and their measured lossless JXL; the sRGB- and P3-converted layers haven't
been rendered, so theirs will differ somewhat.

**What fits GitHub:** all branches of a repository share its 10 GB, and history keeps
every earlier render. `png-srgb` and `png-p3` exceed 10 GB on the first pass. `jxl-p3` fits
once, with no room for a second pass. The originals fit but are over the recommended 5 GB,
and two DNGs (1455, 1458) exceed the 100 MB file limit. So all five should carry their bytes
as LFS objects on R2 (the mechanism the `variant/*` branches already use), unless the
originals repository drops the two DNGs and never changes.

## Rendering rules for the four derived layers

One route for every source: zencodecs decode, then zenpixels-convert, then zenpng or
jxl-encoder, then decode back and compare before writing.

- **Orientation baked into the pixels** (`zenpixels_convert::orient`), EXIF removed. 207
  sources need it.
- **Colour conversion with zenpixels-convert:** named-profile matrices for sRGB ↔ Display
  P3 ↔ Adobe RGB, and the moxcms plug-in for vendor or LUT profiles (Apple's 26.7 KB
  Adaptive HDR profiles). Relative colorimetric, converted through a 16-bit or float
  intermediate and rounded once to 8 bits.
  - **P3 → sRGB clips** out-of-gamut colours. The builder records the clipped-pixel count
    per file in the manifest.
  - **sRGB → P3 at 8 bits is not reversible** (two sRGB colours can land on one P3 code).
  - **Untagged sources** (1,609 PNGs, 183 JPEGs) are treated as sRGB and marked `assumed`.
  - **HEIC tile colour** counts when the grid has none (42 files). The 22 HEICs whose
    primary profile the metadata rewrite replaced (19 with the `tmap`'s PQ profile, 3
    with the gain map's Linear Gray) are converted as the Display P3 SDR their camera
    files declare (`metadata_audit_earlier_copies_2026-09-25.md`).
- **Signalling:** `cICP` 1/13/0/1 or 12/13/0/1 in every PNG, the matching colour encoding
  in every JXL. Never untagged.

## HDR twins

All 76 HDR sources (43 HEIC with Apple gain maps; 33 JPEG once their gain maps are
restored) are Display-P3 phone photos with an SDR base image and a gain map. None is
PQ- or HLG-encoded.

**HDR "sRGB" doesn't really make sense.** sRGB names an SDR transfer. The HDR version of it
is BT.709 primaries with PQ (`cICP 1/16/0/1`), which is legal, but it clips the P3 gamut of
every one of our HDR sources, exactly in the saturated highlights HDR exists for. zenmetrics'
HDR ingress accepts P3 primaries, so no consumer we have needs BT.709 PQ.

So HDR lives only in the P3 repositories: `<name>.hdr.png` and `<name>.hdr.jxl` next to
`<name>.png`, 16-bit, P3 primaries, PQ, `cICP 12/16/0/1`, measured `cLLI`. The SDR file
beside it is the camera's base image in P3. The manifest records the headroom applied (the
`tmap` alternate headroom for the 19 iPhone 16/17 Pro files) and the diffuse white (BT.2408's
203 nits unless decided otherwise). `png-srgb` and `jxl-srgb` stay SDR-only.

## JPEG-in-JXL and lossless transforms (measured)

`tools/jpeg-lossless-check`, 2026-09-25, over all 417 JPEG sources (zenjpeg `8f703a6e`,
jxl-encoder `8da452cf`, zenjxl-decoder `940d2c51`). Per-file results:
`/mnt/v/output/imazen-26-variants/jpeg-lossless-check-2026-09-25/` (`all_417.tsv`,
`rotated_134.tsv`, `SHA256SUMS`).

### Progressive → sequential: lossless

zenjpeg's `lossless::transform` with no transform re-encodes the same coefficients as a
baseline sequential JPEG with optimized Huffman tables. On all 417:

- coefficients identical, and zenjpeg decodes both files to identical pixels (max
  difference 0);
- the sequential file's JPEG-in-JXL rebuilds it byte-exact in all 417 cases. That includes
  the 12 progressive and 21 trailing-restart-marker files that don't rebuild from their
  originals (zenjxl-decoder #58/#59, jxl-encoder #120);
- the JXL decodes to the same pixels as the original's JXL.

Size: the 66 progressive files grow 5.1% as sequential JPEG (241.4 → 253.6 MiB), but their
JXL shrinks 2.3% (211.7 → 206.9 MiB). The 351 baseline files shrink 2.7% (optimized
Huffman, restart markers dropped), and their JXL is unchanged.

### Rotation in the coefficient domain: lossless only when the edge is MCU-aligned

A 90° rotation moves the bottom edge to the left; 270° moves the right edge to the top;
180° moves both. JPEG can only hold a partial MCU on the right or bottom, so the moved edge
has to be a whole number of MCUs or be trimmed. Of the 134 rotated JPEGs, **2 are aligned**
(1423, 1611). **132 are not**: 4:2:0 phone photos at 4000×3000 (126) or 4000×2252 (6),
whose rotation must drop 8 or 12 rows.

Measured against the pixel-rotated decode of the original, through zenjxl-decoder (float
IDCT, so 1 level is rounding):

| case | files | interior (≥ 16 px from an edge) | near the edges |
|---|--:|--:|--:|
| aligned, 90°/270° | 2 | max 1 | max 1 |
| trimmed, 90°/270° | 127 | max 1 | median 5, max 20 |
| trimmed, 180° | 5 | max 1 | max 3 |

Those figures are with the quantization tables transposed (below). The border band on the
trimmed files is the "border issue": the rows removed with the partial MCU were the chroma
neighbours of the new edge, so the edge interpolates differently, on top of the 8 or 12
rows lost. zenjpeg's own decode differs from its pixel-rotated output by up to 4 levels
even where the coefficients match exactly (up to 3 for a horizontal flip, 0 for a vertical
one); zenjxl-decoder stays within 1.

**Two zenjpeg defects surfaced, both filed:**

- **imazen/zenjpeg#205:** the transposing transforms (EXIF 5–8) keep the untransposed
  quantization tables, so any JPEG with an asymmetric table decodes wrong after rotation.
  Up to 70 levels here, median 25 on the asymmetric files. 386 of the 417 JPEGs, and 113 of
  the 134 rotated ones, have an asymmetric table. Transposing the tables (tested by
  rewriting the output's DQT) brings the interior to within 1 level.
- **imazen/zenjpeg#204:** `apply_exif_orientation` trims silently. Trimming has to be an
  explicit opt-in.

### What to do with the 132

| option | lossless? | border issue | extra bytes (132 files) | status |
|---|---|---|--:|---|
| **Orientation in the JXL header**, coefficients untouched | yes, and the original rebuilds byte-exact | none | 0 | needs jxl-encoder #119 |
| Coefficient rotation, trimmed | the rest of the image, yes | 8 or 12 rows lost, edge band up to 20 levels | ≈ 0 | needs zenjpeg #205 |
| Coefficient rotation into a cropped JXL frame | yes | none expected | ≈ 0 | not supported by jxl-encoder; no JPEG rebuild possible |
| Decode, rotate, store as lossless JXL | pixel-exact to one decoder's output | none | +0.58 GiB (0.958 vs 0.377 GiB; 2.5×) | possible today |
| same, as PNG | same | none | +1.49 GiB (1.862 GiB; 4.9×) | possible today |

The lossless JXL price comes from the measured lossless-JXL sizes of the png-v3 renders
(median 7.6 MB per file, against 2.9 MB for the transcode).

**Recommendation:** keep JPEG-in-JXL a container transform of the original: coefficients
in stored orientation, orientation in the JXL header (#119), which JXL decoders apply by
default. It stays exact, with no border band and no extra bytes. It belongs with the
originals, not in `jxl-srgb`/`jxl-p3`: its decoded pixels depend on the decoder (median
6 levels from zenjpeg's), so it can't be the pixel twin of a PNG, and its colour can't be
converted without leaving the coefficient domain. The `jxl-*` layers are lossless renders.

## Decisions for the owner

1. **Five repositories** as above, LFS on R2 for all, or plain git for the originals
   without the two DNGs?
2. **JPEG-in-JXL placement:** a `jxl/` twin inside `imazen-26-originals` (+0.99 GiB), a
   separate `imazen-26-jpeg-jxl`, or neither until jxl-encoder #119 lands?
3. **HDR only in the P3 repositories** (proposed), or also BT.2020 PQ?
4. **P3 → sRGB:** relative colorimetric with clipping (proposed), or a gamut-compression
   intent?
5. **HEIC colour profiles:** restore the 64 HEICs' camera `colr` properties in the
   originals first (`metadata_audit_earlier_copies_2026-09-25.md`), or build the layers
   from the corpus files with the 22 primaries overridden to Display P3?
