# JPEG-in-JXL for the JPEG sources: size, exactness, colour, orientation, HDR (2026-09-22)

The question: for sources that are already JPEG, is a lossless JPEG→JXL transcode (the
JPEG's own DCT coefficients plus a `jbrd` box that rebuilds the original file) a better
JXL than a lossless render of decoded pixels? And do colour, orientation and HDR survive,
especially for readers that don't colour-manage, don't read EXIF, or don't know gain
maps?

**Short answer.** As the JXL form of a JPEG source, yes: the transcode *is* the original
(it rebuilds byte-for-byte) at 0.82× the JPEG's size, against 2.40× for a lossless JXL
render. It can't be the pixel reference, though, because two decoders don't agree on
JPEG-derived pixels. It is not ready to build yet: the transcoder drops orientation, 33
files don't rebuild exactly, and HDR doesn't survive as HDR. Separately, the corpus's
own HDR JPEGs have lost their gain maps.

## Where JPEG applies

| source format | ids | share | in the photo classes (1000–3300) |
|---|--:|--:|--:|
| JPEG | 417 | 19% | 306 of 409 (75%) |
| PNG | 1,650 | 76% | 10 |
| HEIC | 90 | 4% | 90 |
| DNG | 3 | <1% | 3 |

JPEG is most of the photographs, not most of the corpus. A PNG source already is a
lossless original, so a lossless JXL of its pixels is an exact twin. HEIC has no
transcode path into JXL, and DNG needs a raw render. 66 of the 417 JPEGs are
progressive: every Unsplash (2000/2200/2400) and Art Institute (3000) download. Every
camera photo is baseline.

## Results

Two builds of `tools/jxl-transcode-check` ran over all 417 JPEG sources and over the 33
pre-rewrite UltraHDR originals (§HDR). **published** = jxl-encoder 0.3.1 +
zenjxl-decoder 0.3.10 + zenjpeg 0.7.1; **HEAD** = jxl-encoder `8da452cf` + zenjxl-decoder
`940d2c51` + zenjpeg `8f703a6e` (committed, unpublished; details under "How it was
measured").

| 417 JPEG sources | published | HEAD |
|---|--:|--:|
| transcoded | 350 (66 progressive refused, 1 over 100 MP) | **417** |
| JXL bytes / JPEG bytes (total) | 0.828 (0.935 → 0.774 GiB) | **0.824** (1.196 → 0.985 GiB) |
| per-file ratio, median (range) | 0.835 (0.300–0.875) | 0.821 (0.274–0.907) |
| rebuild byte-exact | 267 of 350 | **384 of 417** |
| rebuild differs | 83 (62 scan-data mismatches, 21 trailing RST) | 21 (trailing RST) |
| `jbrd` present, rebuild fails | 0 | 12 (progressive) |
| ICC carried byte-identical | 181 of 181 | 234 of 234 |
| header orientation | `Identity` for all 350 | `Identity` for all 417 (134 wrong) |
| gain map exposed (`jhgm`) | 0 | 0 |
| encode time, median | 0.33 s | 1.08 s |

HEAD carries the JPEG work done after 0.3.1: progressive parsing, DQT-id quant tables,
and zenjxl-decoder's reconstruction-writer fix. No published jxl-encoder can build this
layer today, and neither can current jxl-encoder main (Blockers).

## Size

Over all 417 JPEG sources (HEAD):

| form | GiB | × JPEG |
|---|--:|--:|
| JPEG original | 1.196 | 1.00 |
| JPEG-in-JXL transcode | 0.985 | 0.82 |
| lossless JXL of the png-v3 render | 2.874 | 2.40 |
| png-v3 SDR render | 5.410 | 4.52 |

The render figures come from `split_branches_design_2026-09-22.md` (sizes.tsv there).
The transcode is 2.9× smaller than the lossless JXL render and keeps the original,
not a decoded copy. The two outliers at 0.27× (9933, 9972) are one 632 KB generated
product image, stored twice.

## Colour: managed and naive readers

234 of the JPEGs carry an ICC profile: 166 Display-P3 (165 Samsung "DCI-P3 D65 Gamut
with sRGB Transfer", 1 "Display P3 Gamut with sRGB Transfer"), 66 sRGB variants and 2
Adobe RGB (1998). The JXL carries every one of them byte-for-byte as its colour
encoding. A colour-managed reader shows the same colours from either file.

The 183 without a profile get an sRGB colour encoding in the JXL (145 RGB) or grey with
the sRGB transfer (38 greyscale). That's the assumption a reader makes for an untagged
JPEG anyway.

A naive reader, one that ignores the profile, gets the same pixel values from the JXL as
from the JPEG: nothing converts them. (In the pixel comparison below, the mean difference
stays at or under 1.05 levels for every file; a P3→sRGB conversion would move saturated
colours by far more.) So a naive reader shows the 168 wide-gamut photos (P3 and Adobe RGB)
desaturated in both formats. The transcode can't fix that, because converting to sRGB
changes the coefficients and breaks the byte-exact rebuild. Consumers that can't
colour-manage need the sRGB layer `split_branches_design_2026-09-22.md` proposes.

## Orientation

134 of the 417 JPEGs have an EXIF orientation other than 1: 128 × 6 (rotate 90° CW),
5 × 3 (180°) and 1 × 8 (270°). All 417 transcode with orientation 1 (`Identity`) in the
JXL header. JXL readers orient from the header: zenjxl-decoder (`adjust_orientation`,
on by default) and libjxl (`JxlDecoderSetKeepOrientation`, off by default) both apply
it. So those 134 display sideways or upside down. The Exif box is carried into the
container, so the value isn't lost, but readers don't take orientation from it.

libjxl's JPEG recompression copies the EXIF value into the header
(`JxlEncoderAddJPEGFrame` → `InterpretExif`, `lib/jxl/encode.cc`). jxl-encoder's JPEG
path has no equivalent. The fix doesn't touch the bytes the `jbrd` box rebuilds.

Once it's fixed, the JXL is *more* robust for naive readers than the JPEG: a JXL
decoder applies the header orientation unless told not to, while a JPEG reader only
gets orientation right if it parses EXIF.

## HDR

**The corpus's UltraHDR JPEGs have lost their gain maps.** zenjpeg (built with its
`ultrahdr` feature) finds a gain map in none of the 417 canonical JPEGs. It finds one in
all 33 pre-rewrite originals kept at
`/mnt/v/output/codec-corpus/lilith-photos-backup-2026-06-09/` (Samsung UltraHDR: primary
JPEG, MPF, XMP `hdrgm`, ISO 21496-1 APP2, then the gain-map JPEG and a Samsung trailer).
The gain-map JPEGs run 18.7–173.7 KB (median 58.3 KB).

The metadata rewrite behind the canonical files changed metadata only (the image data
from the first table to EOI is byte-identical in all 33). It dropped the MPF, ISO
21496-1 and an APP4 segment, the `hdrgm` fields from the XMP, and everything after the
primary EOI; the canonical files are 64.5–196.9 KB smaller. It also applied the
location-metadata whitelist, and any restoration has to keep that.

All 33 ids have png-v3 HDR renders, which today's canonical files could no longer
produce. A new render pass from today's originals would drop HDR for 33 of the 76 HDR
ids (the other 43 are HEIC). `STORAGE-MAP.md` ("Metadata policy") and `ACCESS.md` both
state that gain maps were hash-verified unchanged by the rewrite; for the JPEGs they
weren't. (The HEIC gain maps weren't checked here.)

**The transcode keeps a gain map, but hides it.** On the 33 originals (HEAD): 33 of 33
rebuild byte-exact, gain map included, because it travels in the `jbrd` box as tail data
after EOI. None gets a `jhgm` box, so even an HDR-capable JXL reader shows only the SDR
base. The primary image's XMP goes into the container's `xml ` box with its
`hdrgm:Version` field, announcing a gain map the JXL doesn't expose. Ratio 0.832; 25 of
the 33 also have orientation 6.

For naive readers nothing changes: without gain-map support, either format shows the
SDR base image, which is the camera's own SDR rendering.

**Restore candidates exist.** `scripts/restore_uhdr_gainmaps.py` rebuilds each of the 33
from the canonical file (its whitelisted Exif, ICC and image data) plus the original's
container XMP, ISO 21496-1 marker, MPF (sizes and offset recomputed) and gain-map JPEG.
It leaves out the original's APP4 segment, full Exif and vendor trailer (191–256 bytes).
All 33 pass: zenjpeg finds each gain map at the original's exact size, the JPEG-in-JXL
transcode rebuilds each byte-exact, ICC and orientation match, and no metadata segment
mentions location or a device id. They are 17–172 KB larger than today's canonical
files. Candidates and `restore_manifest.tsv` (canonical, original, restored and gain-map
sha256 per id): `/mnt/v/output/imazen-26-variants/uhdr-restore-candidates-2026-09-22/`.
Swapping them in is decision 8 in `split_branches_design_2026-09-22.md`.

## Byte-exact rebuild

384 of 417 rebuild exactly at HEAD. The 33 that don't fall into two groups.

**21 Galaxy S21 Ultra photos rebuild 2 bytes short.** At 4000×3000 the camera uses a
restart interval of 11,750 MCUs; the image has 47,000, so it writes one more RST marker
after the last MCU and the file ends `FF D3 FF D9`. libjxl records a marker there as a
top-level entry in `marker_order` (`enc_jpeg_data_reader.cc`) and its writer re-emits it
(`EncodeRestart`, `dec_jpeg_data_writer.cc`). jxl-encoder's parser consumes it as scan
data (`skip_entropy_data`, `src/jpeg/parse.rs`), and zenjxl-decoder's writer has no arm
for a standalone RST in `marker_order` either. The rebuilt JPEG decodes to the same
pixels, but its sha256 doesn't match, and that match is the whole promise. The other 144
corpus JPEGs with a restart interval rebuild exactly, including four S21 Ultra files
whose MCU count isn't a multiple of the interval. Ids: 1002–1006, 1401, 1402, 1404,
1405, 1408–1414, 1416, 1602–1605.

**12 progressive Unsplash JPEGs don't rebuild at all.** Each JXL carries a `jbrd` box
(id 2012: 101,702 bytes), but zenjxl-decoder can't write a JPEG from it. All 12 are
4:2:0 and use the same 10-scan script (spectral selection plus successive approximation,
no restart interval) as the 54 progressive JPEGs that rebuild exactly, 48 of which are
also 4:2:0. So the trigger depends on content. `reconstruct_jpeg` reports this as `Ok(None)`, the same answer as "this JXL has
no `jbrd` box"; the underlying error is kept inside the decoder and not returned. Ids:
2003, 2005, 2009, 2012, 2013, 2022, 2203, 2204, 2207, 2212, 2402, 2409.

## Decoder agreement, and why the pixel reference stays a render

The tool compared zenjxl-decoder's decode of each transcode with zenjpeg's decode of
the original, both in stored orientation, no colour management, 8-bit RGB:

| HEAD, 417 files | median | p95 | max |
|---|--:|--:|--:|
| max abs difference per file (levels) | 6 | 20 | 36 |
| mean abs difference | 0.47 | | 1.05 |
| % of samples off by more than 2 | 0.024 | 0.80 | 10.9 |

4:4:4 files differ most (37 baseline files: median max difference 18, median 0.45% of
samples off by more than 2), led by generated product images and Met Museum photos.
The 4:2:0 camera photos sit at the median.

Neither decoder is wrong. The same DCT coefficients decode to slightly different pixels
in two decoders, and JXL decoding of a transcode is one more decoder. So the transcode
can't carry `pixel_sha256`, the contract in `split_branches_design_2026-09-22.md` that
every decoder must reproduce exactly. Only a lossless render can.

## What changes in the twin design

For JPEG sources the JXL member of the pair becomes the transcode, with its own gate:

| source | JXL member | gate | pixel reference |
|---|---|---|---|
| JPEG (417) | JPEG-in-JXL transcode | rebuilt JPEG sha256 = original sha256; header orientation and colour match the source | PNG render, `pixel_sha256` |
| PNG (1,650) | lossless JXL of the pixels | decodes to `pixel_sha256` | the PNG |
| HEIC (90) | lossless JXL of the render | decodes to `pixel_sha256` | PNG render |
| DNG (3) | lossless JXL of the render | decodes to `pixel_sha256` | PNG render |

That also makes the JXL member of a JPEG pair a test in its own right: any decoder that
implements JPEG reconstruction has to produce the original sha256.

Size effect, using the measured lossless-render sizes for the other ids (GiB):

| bucket | JPEG ids | JXL layer: lossless renders → with transcodes | PNG + JXL twins |
|---|--:|--:|--:|
| train | 210 | 4.03 → 3.11 | 11.20 → 10.28 |
| validate | 133 | 2.41 → 1.78 | 6.63 → 6.00 |
| test | 74 | 1.63 → 1.28 | 4.55 → 4.21 |
| all | 417 | 8.06 → 6.18 | 22.38 → 20.49 |

It doesn't change the layout conclusion: train twins still exceed a 10 GB repository.

## Blockers

1. **Orientation** (imazen/jxl-encoder#119): write the EXIF orientation into the JXL
   header, as libjxl does. 134 files.
2. **Trailing RST** (imazen/jxl-encoder#120, imazen/zenjxl-decoder#58): record the marker
   on parse and emit it on rebuild. 21 files.
3. **Progressive rebuild** (imazen/zenjxl-decoder#59): fix the rebuild for the 12 files,
   and make `reconstruct_jpeg` return the error instead of `Ok(None)` when a `jbrd` box
   is present.
4. **Gain maps as `jhgm`** (imazen/jxl-encoder#122): transcode an UltraHDR JPEG's gain
   map into a `jhgm` bundle so the JXL is HDR, not just able to rebuild an HDR JPEG. The
   bundle serializer exists (`hdr/bundle.rs`).
5. **Restore the 33 gain maps in the corpus** (this repo; owner decision): verified
   candidates are built (§HDR). Swapping them in changes 33 canonical sha256s (manifests,
   R2 objects, anything pinned by source sha256), and the whitelist rewrite as specified
   would strip the gain maps again, so it needs an exception for the MPF, ISO 21496-1
   and `hdrgm` pieces.
6. **Build** (imazen/jxl-encoder#121): main (`ac733993`) doesn't compile with
   `jpeg-reencoding`. `ca264f4f` declared `LosslessConfig.limits`, `with_limits` and
   `limits` a second time. CI doesn't catch it: every failing job in the run for
   `ac733993` stops earlier, at `cargo build --locked`, on a stale Cargo.lock.

Two build notes for anyone reproducing the published run. magetypes 0.9.21 added a
required token argument to the generic `f32x8::load_8x8` that zenjpeg 0.7.1 calls, so
jxl-encoder 0.3.1 builds need magetypes pinned to 0.9.20 (and linear-srgb to 0.6.11).
And zenjpeg's `GainMapHandling::PreserveRaw` compiles without the `ultrahdr` feature but
then finds nothing (imazen/zenjpeg#203); an earlier run of this tool reported 0 gain maps
in the 33 originals for exactly that reason.

## How it was measured

`tools/jxl-transcode-check` (this repo). Per file it transcodes with jxl-encoder
(`read_jpeg` → `encode_jpeg_to_jxl_container`), records the `jbrd` box size, rebuilds
the JPEG with zenjxl-decoder `reconstruct_jpeg` and compares sha256, decodes the JXL as a
plain reader would (`zenjxl_decoder::decode`: pixels, colour profile, orientation,
`jhgm`), decodes the original with zenjpeg (stored orientation, gain map kept raw) and
compares pixels, and reads the ICC profile, EXIF orientation and the bytes after the
primary EOI itself. Failures go into the `error` column; no row is skipped.

- `tools/jxl-transcode-check/Cargo.toml`: published crates, pinned exactly (lockfile
  committed).
- `tools/jxl-transcode-check/head/Cargo.toml`: the same source against git revisions:
  jxl-encoder `8da452cf` (the parent of `ca264f4f`, the last main commit that builds
  with `jpeg-reencoding`), zenjxl-decoder `940d2c51`, zenjpeg `8f703a6e`, zenanalyze
  `b102fa5f` (zenjpeg main needs its unpublished 0.2.0).

Inputs: the 417 JPEG sources (all match their manifest sha256) and the 33 backups. Six
processes in parallel under `run-heavy`, 2026-09-22.

Per-file results: `/mnt/v/output/imazen-26-variants/jpeg-in-jxl-validation-2026-09-22/`
(`head_sources.tsv`, `head_uhdr_backups.tsv`, `pub_sources.tsv`, `pub_uhdr_backups.tsv`,
input lists, summaries). `head_sources.tsv` sha256
`777ac4827ac32d7ea04bca23554d64cff902fd755ff971ef812d70142450c6c3`; the rest are in
`SHA256SUMS` there. Not mirrored to tower (not mounted this session).
