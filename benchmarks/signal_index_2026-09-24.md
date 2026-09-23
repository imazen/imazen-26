# Orientation, colour and HDR signalling of every source (2026-09-24)

What each of the 2,160 source files actually signals: orientation, ICC, CICP, HDR
metadata and gain maps, by file type. Then where the png-v3 renders stand against
that, and what it means for normalized layers and for repositories split by file type.

Per-file index (one row per id, 55 columns):
`/mnt/v/output/imazen-26-variants/signal-index-2026-09-24/sources_signal.tsv`
(sha256 `68090d17…` in `SHA256SUMS` there), built by `tools/corpus-signal-probe`.

## Counts

| | JPEG | PNG | HEIC | DNG | all |
|---|--:|--:|--:|--:|--:|
| files | 417 | 1,650 | 90 | 3 | 2,160 |
| **rotated** (orientation ≠ 1) | **134** | 0 | **70** | 3 | **207** |
| ↳ 90° CW (6) / 180° (3) / 270° (8) | 128 / 5 / 1 | – | 66 / 3 / 1 | 2 / 1 / 0 | 196 / 9 / 2 |
| **ICC profile** | **234** | **41** | **90** | 0 | **365** |
| ↳ Display P3 | 166 | 41 | 68 | – | 275 |
| ↳ P3 profile with a PQ `cicp` tag (Apple Adaptive HDR) | – | – | 19 | – | 19 |
| ↳ sRGB | 66 | – | – | – | 66 |
| ↳ Adobe RGB (1998) | 2 | – | – | – | 2 |
| ↳ "Linear Gray" on an RGB image | – | – | 3 | – | 3 |
| **CICP signalled** (PNG `cICP`, HEIF `nclx`) | n/a | **0** | **0** | n/a | **0** |
| untagged (no colour signal at all) | 183 | 1,609 | 0 | 3 (camera colour) | 1,795 |
| **HDR: gain map present** | 0 (33 removed, restorable) | 0 | **43** | not probed | **43** (+33) |
| ↳ ISO 21496-1 `tmap` | – | – | 19 | – | 19 |
| HDR: PQ or HLG pixels | 0 | 0 | 0 | 0 | 0 |
| `cLLI` | 0 | 0 | 6 (all `203/64`) | – | 6 |
| bit depth | 8 | 8 (1,611), 1 (39) | 8 | 14 (2), 16 (1) | |
| other | 38 grey, 66 progressive | 25 RGBA, 39 1-bit grey, 0 interlaced, 0 palette | 34 depth maps, all 4:2:0 | 2 files over 100 MB | |

So, directly: **207 rotated, 365 with ICC, 0 with CICP, 43 HDR** (76 once the 33 JPEG
gain maps are restored). No source is PQ- or HLG-encoded. Every HDR source is an SDR
base image plus a gain map. Every CICP in the corpus lives in derived renders; none is in
an original.

Wide gamut is phone content: the 275 Display-P3 files are 166 camera JPEGs and 68 camera
HEICs (all in the photo classes 1000–1600), 31 mobile screenshots and 10 PNGs in the
photo classes. The 1,609 untagged PNGs (AI products and clip art, web screenshots, plots,
park and NOAA documents, scans) carry no `iCCP`, `sRGB`, `gAMA`, `cHRM` or `cICP` chunk;
an independent chunk scan agrees exactly.

## Quirks the index turned up

**42 HEICs keep their colour only on the tiles.** The 33 Galaxy S23 Ultra HEICs and 9 of
the 10 iPhone 8 Plus HEICs put a Display-P3 ICC profile (Samsung's "DCI-P3 D65 Gamut
with sRGB Transfer", Apple's "Display P3") on every grid tile and none on the grid
image. heic's `ImageInfo` reads only the primary item, so it reports no colour for them.
Every png-v3 render of these 42 is tagged sRGB.

**3 iPhone 13 Pro HEICs (1495, 1496, 1498) carry a "Linear Gray" profile on an RGB
image.** It is associated with the primary grid and all its tiles, not with the gain map
(whose `colr` box is empty). `color_orientation_audit_2026-09-22.md` §2 said these
colour boxes belong to the gain map; the item associations say otherwise. What a
reader should do with a grey profile on RGB data isn't settled; png-v3 tagged them P3.

**19 iPhone 16/17 Pro HEICs are Apple Adaptive HDR.** The primary carries a ~26.7 KB
profile named "Display P3 Primaries; PQ (Gain Map Preview …)" or "(Adaptive Gain Curve
…)" whose ICC `cicp` tag says 12/16 (P3, PQ), alongside an Apple gain-map auxiliary
image and an ISO 21496-1 `tmap` item. The `tmap` metadata settles what the base is:
base headroom 0 in all 19 (SDR), alternate headroom 1.31–2.79 stops. So a reader that
honours the profile's `cicp` tag would misread the base as PQ. png-v3 tagging them P3
SDR is right. For the 24 older Apple gain maps (iPhone 13/15 Pro), heic doesn't read the
parameters.

**The zencodecs probe reports effective colour, not signalled colour.** It sets CICP
1/13/0/1 on any untagged JPEG or PNG (`finalize_implicit_srgb`, on purpose) with nothing
marking it as assumed. For HEIC it calls heic's light probe, which carries no colour and
no gain-map parameters. Separately, its JPEG adapter never
sets `is_progressive`, so all 66 progressive JPEGs read as baseline. heic's full probe
carries the grid's colour and the `tmap` parameters, but it too misses tile-only colour.
The tool works around all of these by asking each codec crate directly (below).

## Where the png-v3 renders stand

Joining each source's colour to its png-v3 SDR render's tag
(`png_v3_tag_vs_source.tsv` next to the index):

| source colour | renders | png-v3 tag | verdict |
|---|--:|---|---|
| untagged PNG | 1,609 | untagged | ok |
| untagged JPEG | 183 | `cICP 1/13/0/1` | ok (sRGB assumed) |
| sRGB ICC (JPEG) | 66 | `cICP 1/13/0/1` | ok |
| Display P3 ICC (PNG) | 41 | `iCCP` | ok |
| Display P3 on the grid (HEIC) | 26 | `cICP 12/13/0/1` | ok |
| P3 with a PQ tag, SDR base (HEIC) | 19 | `cICP 12/13/0/1` | ok (base headroom 0 verified) |
| **Display P3 ICC (JPEG)** | **166** | `cICP 1/13/0/1` | **mislabelled** |
| **Display P3 on tiles only (HEIC)** | **42** | `cICP 1/13/0/1` | **mislabelled** |
| **Adobe RGB (JPEG)** | **2** | `cICP 1/13/0/1` | **mislabelled** |
| Linear Gray on RGB (HEIC) | 3 | `cICP 12/13/0/1` | unverified |
| DNG | 3 | no render | — |

**210 png-v3 renders are tagged sRGB although their source is wide-gamut.** (The
2026-09-22 audit counted 165 within pristine-8th's 505 renders.) pristine-8th has the
mirror-image problem on 22 HEICs: it wrote the 19 Adaptive HDR files and the 3 Linear
Gray files untagged, so a reader takes the 19 as sRGB although their base is P3.

## Normalization

Keep the originals byte-identical. Tile-only colour, odd profiles, trailing restart
markers and rotated phone photos are exactly what decoders meet in the wild, so the
originals are the decoder test surface. Normalize the derived layers instead, with one
rule set applied to every source type:

- **Orientation applied** in every derived file (207 sources need it). Where a derived
  container can hold the original orientation instead (a JPEG-in-JXL transcode), it goes
  in the header.
- **Colour explicit, native gamut:** `cICP` where H.273 can say it (sRGB 1/13, Display P3
  12/13), `iCCP` otherwise (the 2 Adobe RGB). Colour is read the way a careful decoder
  reads it: HEIC tile colour when the grid has none, and the profile's matrix/TRC over
  its `cicp` tag when a `tmap` says the base is SDR. Untagged sources are written as
  sRGB and marked `assumed` in the manifest.
- **HDR recorded, never guessed:** the SDR layer is the camera's base image; the HDR
  layer is the gain map applied at a headroom written into the manifest (the `tmap`
  alternate headroom where there is one), as 16-bit PQ with `cICP 12/16/0/1` + `cLLI`.
  76 sources once the JPEG gain maps are restored.
- **Signalling columns in the manifests:** the index above, so a consumer can select
  "P3 HEIC with a gain map" without re-probing.

Three sources need a call before they can be normalized: the 3 Linear Gray HEICs.

## Repositories by file type

The originals split cleanly by type, and each type has its own natural JXL form:

| repository | contents | GiB | fits raw git? |
|---|---|--:|---|
| `imazen-26-jpeg` | 417 originals + 417 JPEG-in-JXL transcodes | 1.20 + 0.99 = 2.19 | yes |
| `imazen-26-png` | 1,650 originals (+ lossless JXL twins) | 3.83 (+ 2.17 = 6.00) | yes; with twins, over GitHub's 5 GB recommendation |
| `imazen-26-heic` | 90 originals | 0.19 | yes |
| DNG | 3 originals | 0.26 | no: 1455 and 1458 exceed GitHub's 100 MB file limit (keep on R2 / LFS) |
| normalized renders | SDR + HDR, PNG + JXL | 22.4 | no (LFS on R2, as `split_branches_design_2026-09-22.md` proposes) |

Per bucket (train / validate / test, canonical split), originals only: JPEG 0.57 / 0.42 /
0.20 GiB, PNG 1.98 / 1.11 / 0.74, HEIC 0.09 / 0.05 / 0.05. A codec developer testing JPEG decoding
clones 2.2 GiB instead of 5.5, and every file in it is a real JPEG with its quirks. Bucket
directories inside each repository (with sparse checkout) work better than bucket
branches here: one clone per format, and a family moved between buckets is a rename,
not a cross-branch copy.

## How it was measured

`tools/corpus-signal-probe` (this repo), one process, 2026-09-24, over all 2,160 sources
(all match their manifest sha256; 0 probe errors). Per file it records the zencodecs
probe (`zencodecs::from_bytes` at zenpipe `6a5b052`) and each codec's own view:
`zenpng::probe` (colour chunks), zenjpeg's `container::probe` (ICC, MPF, ISO 21496-1,
XMP `hdrgm`, SOF type), heic's `ImageInfo`, HEIF container (`colr` on the primary item,
else its first tile; `clli`; `tmap`), full probe (gain-map headroom) and auxiliary-image
list. ICC profiles are named with `zenpixels::icc::identify_common` and their `desc`
tag. Git dependencies are pinned to the revisions zenpipe's own Cargo.lock resolves at
`6a5b052`.
