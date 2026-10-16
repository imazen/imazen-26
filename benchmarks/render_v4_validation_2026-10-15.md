# Render v4: how the layers are checked, and what the checks found (2026-10-15)

`tools/render-v4` writes the v4 layers from the originals pass (EXPORT-PLAN.md, "Render v4").
This page records the checks behind each layer, what they found on test sets before the
full run, and the zen fixes and issues that came out of them. Full-run results are added
when the passes finish.

All runs: dev, under run-heavy, zen crates at main (`tools/render-v4/Cargo.lock`, plus
`tools/corpus-thumbs/zen-main/COMMITS.tsv` for zencodec and ultrahdr). Third-party tools only
read files: ImageMagick 7.1.2-18 (LittleCMS, libpng), Pillow, netpbm `pngtopnm`, libpng
`pngfix`, libheif 1.21.2 `heif-dec`, libjxl 0.11.1 `djxl`/`jxlinfo`, exiftool.

## SDR PNG layers

`png-p3` keeps each source's code values and colour; `png-srgb` converts Display P3 and Adobe
RGB to sRGB in linear light and clips. `scripts/colour_oracle.py` rebuilds every wide-gamut
`png-srgb` file from its own `png-p3` twin with the published primaries matrices (no CMS) and
also with LittleCMS through ImageMagick.

| image | colour | render vs textbook, own decode | LittleCMS vs textbook |
|---|---|---|---|
| 13005 (Art Institute) | Adobe RGB | max 1, mean 0.023 | max 1, mean 0.383 |
| 11044 | Display P3 | max 1, mean 0.012 | max 1, mean 0.309 |
| 11064 | Display P3 | max 1, mean 0.044 | max 1, mean 0.540 |
| 11068 (HEIC) | Display P3 | max 1, mean 0.025 | max 1, mean 0.240 |
| 11069, 11497, 11515, 11520 (HEIC, gain map) | Display P3 | max 1 | max 1 |

- **Fixed: Adobe RGB through zenpixels** (imazen/zenpixels e91478d5). The planner labelled the
  output of its naive 8/16-bit → f32 steps as linear, so for Gamma 2.2 and BT.709-transfer
  sources it applied the gamut matrix in encoded space. 13005's `png-srgb` was up to 36 code
  values off LittleCMS (7.3% of pixels off by more than 1); now max 1. sRGB-curve sources
  (Display P3) were unaffected.
- **Fixed: Android's "Display P3 Gamut with sRGB Transfer" profile** (imazen/zenpixels
  174e01e5). zenpixels didn't identify this 520-byte profile, which tags all 32 mobile
  screenshots and 5 more phone images; render-v4 refused them. icc-gen identifies it as
  Display P3 with the sRGB curve, maximum u16 error 1, no LittleCMS disagreement. The 37
  images are re-rendered with `scripts/render_v4_redo.sh`; six control images rendered with
  the new toolchain are byte-identical to the first run's files.
- **Fixed: the 1-bit patent pages kept their depth** (98eb20c). render-v4 wrote every grey
  source through zenpng's 8-bit grey encoder, so the 39 one-bit pages became 8-bit grey PNGs,
  33–47% larger than their originals, against "bit depth follows the source". Sub-byte grey
  PNG sources now go through zenpng's layout search (as the originals' crush did) and must
  come out at the source's depth; 16000 is 1-bit again and within 0.3% of its original. Across
  the 1,260 PNG sources rendered before the fix, `png-p3` was otherwise the original's size to
  within 0.03% at the median, palette images included (zenpng's RGB path keeps their 1/2/4/8-bit
  palettes). The 39 pages are re-rendered with the redo.
- **HEIC decoders disagree slightly.** Against libheif's decode, our heic crate's differs by
  up to 3 code values on a few dozen pixels of the iPhone files (1068: 12 of 12.2 million
  pixels, by 1; 11069: 66 pixels). The pairs sit at saturated edges, which points at chroma
  upsampling or rounding order. YCbCr-to-RGB is not normative, so both are within spec; the
  render's colour checks run on its own decode, where the difference drops out.

`scripts/render_v4_readback.py` decodes every PNG with Pillow, ImageMagick and `pngtopnm`
against the recorded pixel hash, runs `pngfix`, and checks the chunk set (`sRGB`; `iCCP` +
`cICP` 12/13; `iCCP` alone for Adobe RGB; one provenance `tEXt`). On the 16-image test set:
32 of 32 files pass.

## HDR (16-bit PQ)

`png-hdr` reconstructs each gain-map source at its full headroom, 203 nits per 1.0, exact
ST 2084, `cICP` 12/16, `cLLI` measured on the written codes. `scripts/hdr_oracle.py` rebuilds
every file in numpy from libheif (HEIC base and gain map), Pillow and exiftool (JPEG base,
MPF gain map and `hdrgm` parameters).

On six test files (two each of UltraHDR JPEG, iPhone `tmap` HEIC and legacy Apple HEIC, with
and without rotation): mean difference 0.0–0.4 PQ codes, 99.9th percentile 0.0004 stops
above 1 nit, identical `cLLI`. The rare large single-pixel differences are the HEIC decoder
differences above.

What the checks settled:

- **Gain-map sampling.** ultrahdr-core's `apply_gainmap` aligns gain-map samples at pixel
  corners (`x0 = x / scale`), as libultrahdr does, and blends with Shepard's weights. A
  centre-aligned bilinear rebuild differs by up to 0.38 stops at gain-map edges (99.9th
  percentile 0.14); the render follows ultrahdr-core. ultrahdr-core blends the gains after
  the curve where libultrahdr blends the stored values first: 0.011 stops apart at the 99.9th
  percentile on 1064 (imazen/ultrahdr#42).
- **Apple's legacy curve.** heic documents `scale = 1 + (H - 1) * sRGB_EOTF(g)` but its
  `ReconstructHdr` applies ISO parameters with gamma 1, up to 0.3 stops brighter in the mid
  gain range (imazen/heic#62). The render applies Apple's curve itself, under ultrahdr-core's
  sampling (a unit test holds render-v4's sampler to `apply_gainmap` within 1e-5).
- **Apple's `tmap` offsets.** The iPhone 16/17 `tmap` payloads carry offsets of 1e-5, so the
  SDR black maps to about 0.002 nits, PQ code 500–900 rather than 0. That is the producer's
  formula, applied as written.

## JPEG XL

`jxl` writes `jxl-p3` and `jxl-srgb`; `jxl-hdr` writes each `.hdr.png`'s lossless twin.
`scripts/render_v4_jxl_check.py` checks every file with libjxl: lossless files decode to the
PNG twin's pixel hash in `djxl` and state the same colour in `jxlinfo`; JPEG-in-JXL files
rebuild the original's sha256 in `djxl`; `.hdr.jxl` files decode to the `.hdr.png` samples at
16 bits with P3 primaries and PQ.

On the 16-image test set: 32 of 32 files pass; on the six HDR files: 6 of 6.

- **Found: a lossless P3 encode changed the pixels** (imazen/zenjxl#29). Handed a
  Display P3 descriptor with no colour in the metadata, the encoder's format negotiation
  converted the pixels to sRGB (up to 118 code values) and labelled the file sRGB. render-v4
  passes the code values labelled sRGB and states the colour in the metadata (CICP 12/13, or
  the ICC for Adobe RGB); the decode is then bit-exact.
- **zencodecs' JXL decode reports orientation instead of applying it.** A JPEG-in-JXL keeps
  the JPEG's orientation in its header (1064: orientation 6); render-v4 applies the reported
  orientation before comparing.
- **1-bit JPEG XL** (03da97a). The same 39 pages are encoded through jxl-encoder directly
  with `bits_per_sample` 1 (zencodecs' request has no bit-depth setting); libjxl reads them as
  "1-bit Grayscale" and decodes them to the PNG twins' pixels.
- **The 12 progressive Unsplash JPEGs** fall back to a bare codestream of the same DCT
  coefficients without reconstruction data (owner question 2): 2003 decodes within 4 code
  values of zenjpeg's decode of the JPEG.
- **Effort** (8 sources, both layers, under load): e5 47.4 MB in 39 s, e7 44.0 MB in 75 s,
  e9 41.3 MB in 507 s. JPEG-in-JXL sizes are equal at e7 and e9 (owner question 7).

### Gain-map form (`jhgm`)

- UltraHDR JPEG-in-JXL: the transcode carries the JPEG's MPF gain map as a `jhgm` box and
  the original still rebuilds byte for byte; its gain map decodes within 2–3 code values of
  zenjpeg's decode of the JPEG's own.
- HEIC: render-v4 appends `jhgm` to the lossless `p3` file. A `tmap` map goes in unchanged
  (HDR from the box equals the source's, 0.0000 stops); a legacy Apple map is re-quantized
  onto an ISO curve (min 0, max = headroom, gamma 1, no offsets): 0.0059–0.0060 stops from
  Apple's curve, as `benchmarks/apple_legacy_gainmap_iso_fit_2026-10-03.md` predicted.

## Inventory and byte scan

Both gates were written for the originals' 4-digit names and would have passed the
5-digit export names without checking anything; they now take both and refuse an empty
input. On the 76 test renders (PNG and JXL, SDR and HDR): 0 inventory violations (JXL parts:
`jbrd`, `jhgm`, `jxll`, the JPEG's own brotli Exif and XMP), 0 byte-scan findings. The
inventory CLI is zenpipe's `feat/inventory` branch (PR #89), not main.
