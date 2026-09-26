# Source metadata compared with earlier copies (2026-09-25)

**Question:** did the untagged sources, or the sources whose HDR went missing, lose
metadata on the way into the corpus, in particular in the whitelist metadata rewrite of
the four camera classes (1000/1200/1400/1600, `STORAGE-MAP.md`)?

**Answer:**

- **The untagged files lost nothing.** 1,789 of the 1,792 untagged JPEGs and PNGs have an
  earlier copy with the same image data, and none of those copies carried a colour tag
  either. Where the corpus file was converted from something else, the source was
  untagged or declared sRGB/grey, with one caveat about the PDF-rendered pages (below).
- **The HDR loss is the 33 Samsung UltraHDR JPEGs already known.** The pre-rewrite backup
  has all 33 gain maps, and restore candidates exist (`jpeg_in_jxl_validation_2026-09-22.md`
  §HDR). 3 GoPro JPEGs also lost an MPF second image, but it is a 960×720 preview, not a
  gain map.
- **New: the rewrite scrambled the colour profiles of 64 of the 90 HEICs.** The image data is
  untouched, but 22 now carry the wrong profile on the primary image: 19 carry the `tmap`'s
  PQ profile, 3 the gain map's "Linear Gray". Every one was Display P3 in the camera file.
  The other items' profiles (gain map, `tmap`, thumbnail) are emptied to 0 bytes or
  overwritten in all 64.
  The published R2 copies are these same files (sha256 checked on 1495, 1540, 1042).
- **The whitelist rewrite did all of it.** The oldest copies found (a 2026-06-04 snapshot,
  an iCloud shared-album export, and the camera-named attic tree) agree byte for byte, and
  still hold the GPS data. One earlier step, before the 2026-06-09 backup, removed only the
  GPS IFD from 48 files. Every colour and HDR change happens between the backup and the
  corpus (next section).

Tools: `tools/metadata-loss-audit/`. Per-file data:
`/mnt/v/output/imazen-26-variants/metadata-audit-2026-09-25/` (`SHA256SUMS`).

## Generations of the camera files

| generation | where | covers | relation to the next |
|---|---|---|---|
| oldest | `/mnt/v/zen/lilith-corpus-snapshot-2026-06-4/` (files dated 2026-05-27 to 06-04); `/mnt/v/heic/` iCloud shared-album export (52 HEICs); attic `imazen-26 - Copy (2)` (camera file names) | 309 of 319 by content, and all 319 counting the attic copies | identical bytes wherever two of them hold the same file |
| GPS removed | `/mnt/v/output/codec-corpus/lilith-photos-backup-2026-06-09/` | all 319 | 48 files differ from the oldest (27 JPEG, 21 HEIC): the GPS IFD is gone, and only Exif pointers and offsets move with it. No other tag, segment, item or property changed. The other 271 are byte-identical to the oldest |
| whitelist rewrite | the corpus (`imazen-26-unprocessed` on R2) | all 319 | everything in the sections below |

The 10 camera-class PNGs and the 3 DNGs follow the same pattern: the backup equals the oldest
copy. No script for the whitelist rewrite survives on this machine, and no session
transcript records the command beyond `STORAGE-MAP.md`'s description, so the mechanism in
§HEIC below is inferred from the results.

## What was compared

Earlier copies on `/mnt/v/output/codec-corpus/`: `lilith-photos-backup-2026-06-09/` (all
319 camera-class files, before the rewrite) and `attic-2026-08-22/` (full earlier corpus
trees and rejected sets), 5,230 files in all. Then every JPEG, HEIC and DNG on local storage
(4.8 M files) was searched by the camera file names, and 551 image files in the older roots
this turned up were keyed (the generations above). Every PNG under the older roots (the
snapshot, `imazen-26-inspo`, `imazen-26-clean*`, `imazen-26-pristine`, the `ai-corpus*`
trees, `Captures`, `collections`, `input`, `product-images`; 52,439 files) was scanned for
colour chunks.

Files were paired by content, not by name. The key covers the image data only: JPEG from
the first non-APPn marker to EOI, PNG `IHDR`+`IDAT`, HEIC the coded bytes of every `hvc1`
item through `iloc`. So a pair is the same image with possibly different metadata.

| canonical files | matched |
|---|--:|
| by content | 2,154 |
| by name only (the 3 DNGs; the rewrite changes their bytes) | 3 |
| by hand (6605, re-rendered from `haeckel_0062_pitcher-plants.png`) | 1 |
| no earlier copy (9869, 9874: AI products) | 2 |

Each earlier copy was probed with the same signal probe as the index
(`signal_index_2026-09-24.md`), and every colour, orientation, HDR, EXIF and XMP signal was
compared with the canonical file's. HEIC item properties were compared item by item.

## The untagged files

"Untagged" as in the signal index: no ICC, `cICP`, `sRGB`, `gAMA` or `cHRM`.

| class | untagged | earlier copy with the same image data | earlier copy tagged |
|---|--:|--:|--:|
| 1000–1600 camera JPEGs | 42 | 42 (pre-rewrite backup) | 0 |
| 3000 AIC, 3300 Met | 31 | 31 | 0 |
| 5000 NPS, 5200 EPA, 5300 NOAA | 128 | 128 | 0 |
| 6000 patents | 113 | 113 | 0 |
| 6600, 6800 IA scans | 72 | 71 | 0 |
| 7000 plots, 8100 web screenshots | 496 | 496 | 0 |
| 9000, 9094, 9226 AI images | 910 | 908 | 0 |
| **total** | **1,792** | **1,789** | **0** |

What the sources said, where the corpus file was converted:

- **Older PNG copies:** of the 52,439 scanned PNGs, 157 outside test-input folders carry a colour
  chunk. 82 of them hold the same image data as a corpus file, and each of those corpus
  files carries the identical `iCCP` profile. The rest match no corpus file by name or size,
  or match by size only a corpus file that is itself P3-tagged, with one exception. 9975 (an
  AI product image) has `sRGB`+`gAMA` in all five `ai-corpus*` copies (RGBA, checked on
  one), but the corpus file is RGB with neither chunk: the alpha-flattening step dropped
  them. The displayed colour is the same, since sRGB is also the untagged default.
- **Patent scans:** the source PDFs declare only DeviceGray/DeviceRGB, so the verbatim JPEG
  and CCITT extraction left no colour declaration behind.
- **Camera JPEGs:** 38 of the 42 are Samsung files whose EXIF `ColorSpace` says sRGB, in the
  camera file and in the corpus file. The other 4 are 3 GoPro files (`ColorSpace` 0, not a
  defined value) and 1214 (no `ColorSpace` in the camera file). The index doesn't count
  EXIF `ColorSpace` as a colour signal.
- **IA scans:** the six archive.org items' JP2 page scans (1,672) all declare an
  enumerated colour space, sRGB for 1,671 and greyscale for 1. The 8 Trouvelot plates come
  from TIFFs with no ICC profile.
- **Museum, IA and NPS files:** each class manifest's sha256 equals the corpus file, so
  none was rewritten after its manifest was made.
- **PDF-rendered pages (5000/5200/5300):** the source PDFs are on `/mnt/v`, and their colour
  spaces vary. The EPA report and the NOAA reports use DeviceRGB/DeviceGray or an embedded
  sRGB profile. Of the 59 NPS pages, 28 come from RGB/grey-only PDFs. The other 31 come
  from PDFs with CMYK or spot-colour content or a non-sRGB profile: 4 pages from PDFs with
  a U.S. Web Coated (SWOP) v2 output intent, and 3 with Adobe RGB (1998) profiles. The rasterizer and its colour handling are not
  recorded. So for those 31 pages, whether the colours were converted correctly into the
  untagged PNG is unverified. A zenpdf re-render would settle it. No tag was dropped: a
  render has no source tag to carry.

## HDR

| set | files | in the earlier copy | in the corpus |
|---|--:|---|---|
| Samsung UltraHDR JPEG | 33 | MPF + XMP `hdrgm` + ISO 21496-1 APP2 + gain-map JPEG | all four removed; restore candidates built |
| GoPro HERO7 JPEG | 3 (1499–1501) | MPF second image, 960×720 preview | removed; not HDR |
| Apple HEIC with gain map | 43 | gain map, `tmap` for 19 | gain maps and `tmap` kept; their profiles emptied (next section) |

## HEIC colour profiles after the rewrite

Pixel data, `irot`, `clli` and the item structure are unchanged in all 90 HEICs. Only the
`colr` properties differ:

| HEICs | camera | primary image (grid + tiles) | other items |
|--:|---|---|---|
| 26 | iPhone 13 Pro (19), 15 Pro (2), 8 Plus (1), 4 whose names carry no camera | unchanged | unchanged |
| 33 | Galaxy S23 Ultra | unchanged (P3 on the tiles) | thumbnail profile emptied |
| 9 | iPhone 8 Plus | unchanged (Display P3 on the tiles) | thumbnail profile emptied |
| 19 | iPhone 16 Pro (14), 17 Pro (5) | **Display P3 → the `tmap`'s "Display P3 Primaries; PQ (…)"** | `tmap` profile and every auxiliary profile (gain map, others) emptied; thumbnail (16 with their own profile) → the PQ profile |
| 3 | iPhone 13 Pro (1495, 1496, 1498) | **Display P3 → the gain map's "Linear Gray"** | gain-map profiles emptied |

The pattern looks as if the rewrite copied one profile, the last one in the file, onto the
first `colr` property and emptied the others. It is consistent with the whitelist step
keeping one `-icc_profile` for a file that holds several.

What it changed downstream:

- The **19 Adaptive HDR files are ordinary HDR gain-map files.** The camera puts
  Display P3 on the SDR base and the PQ profile on the `tmap` item, which describes the
  HDR rendition. The index's "P3 profile with a PQ `cicp` tag on the primary" and the
  reasoning built on it ("a reader honouring the tag would misread the base as PQ") describe
  the rewrite, not the camera.
- The **3 "Linear Gray" files are Display P3.** The camera puts Linear Gray on the gain map,
  as `color_orientation_audit_2026-09-22.md` §2 first said. The item-association
  correction made on 2026-09-24 described the rewritten file.
- png-v3 tagged all 22 as Display P3 SDR, which matches the camera files.
- A reader of the corpus files gets PQ-tagged or grey-tagged SDR pixels for these 22, and
  can't recover the HDR rendition's colour from the emptied `tmap` profile.

## Other changes by the rewrite (not colour, listed for completeness)

- 46 camera JPEGs lost the EXIF Interop IFD (`R98`, the DCF sRGB marker). `ColorSpace` is kept.
- 2 JPEGs (1214, 1407) and the 3 DNGs gained `ColorSpace` = Uncalibrated.
- 1451 lost its XMP (capture date and IPTC fields).
- DNGs: the DNG colour tags (`ColorMatrix1/2`, `AsShotNeutral`, `CalibrationIlluminant1/2`)
  are unchanged. `ImageDescription`, `Software`, `OffsetTime`, `OffsetTimeOriginal` and
  `SubSecTime` were removed, and `SubSecTimeOriginal` shortened.

## What restoring would take

- **33 UltraHDR JPEGs:** candidates exist, built and verified by
  `scripts/restore_uhdr_gainmaps.py`.
- **64 HEICs:** take the backup file's `colr` properties and keep the corpus file's
  whitelisted Exif. This needs a HEIF-aware rewrite: rebuild `ipco` and shift the `iloc`
  offsets. Verify it by pixel-identical decode against the backup and an item-property diff
  showing only the Exif change.

Both are candidates beside the corpus. Swapping them in changes published bytes, so it
is the owner's decision.
