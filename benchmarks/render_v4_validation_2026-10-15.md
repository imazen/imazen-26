# Render v4: how the layers are checked, and what the checks found (2026-10-15)

`tools/render-v4` writes the v4 layers from the originals pass (EXPORT-PLAN.md, "Render v4").
This page records the checks behind each layer, what they found on test sets before the
full run, and the zen fixes and issues that came out of them. Full-run results are added
when the passes finish.

All runs: dev, under run-heavy, zen crates at main (`tools/render-v4/Cargo.lock`, plus
`tools/corpus-thumbs/zen-main/COMMITS.tsv` for zencodec and ultrahdr). Third-party tools only
read files: ImageMagick 7.1.2-18 (LittleCMS, libpng), Pillow, netpbm `pngtopnm`, libpng
`pngfix`, libheif 1.21.2 `heif-dec`, libjxl 0.11.1 `djxl`/`jxlinfo`, exiftool.

## 2026-10-19: current-main recheck

The [dated evidence record](current_main_recheck_2026-10-19.pointer.md) covers
all stored PNG, JXL, IMI, gain-map, colour/HDR and byte-scan checks with the
main-source 0.9.31-beta.1 cohort. Decoded JXL hashes are unchanged after redo 5.
The unified CLI succeeds on 10,791 routes; the 4,300 IMI routes are explicitly
unsupported and tracked in zqi issue 73. IMI's two separate readers pass.

The sample pass changes nine JXL headers under the approved Relative-intent
policy, with no size, pixel or gain-map metadata changes; PNG and IMI samples
are byte-identical. No general re-render was applied. The candidate inventory
PRs also preserve all 8,600 per-reader rows across the 4,300 JXL files.

## Full run

`/mnt/tower/output/imazen-26-render-v4-2026-10-15` on tower (`RUN.meta` there records every
pass's commits, hashes and results).

- **SDR PNG** (render-v4 at 593a612, 10 jobs, 8,249 s, peak RSS 24.5 GiB): 2,071 of the
  2,115 list rows rendered; the 44 failures were the 41 images with Android's P3 profile and
  the 3 DNGs (left out of every derived layer). One redo (ee56da7, 8 jobs, 2,156 s, peak RSS
  7.4 GiB) re-rendered 348 images: the 41, the 39 one-bit pages and the 270 with the wrong
  bucket; the DNG rows left the list. Result: 2,112 images, `png-p3` 9.20 GB and `png-srgb`
  9.60 GB, 0 errors; 78 files are 1-bit (the 39 pages in both layers).
- **Colour.** 1,746 assumed sRGB, 66 tagged sRGB, 298 Display P3 and 2 Adobe RGB sources.
  The colour oracle checked all 300 wide-gamut `png-srgb` files: 0 failed, every file within
  1 code value of the textbook conversion of its `png-p3` twin. 299 of them clip at least one
  pixel; the median clips 2.70% of its pixels, 53 clip 10% or more, the most 94.9% (11443),
  86.7% (11546) and 44.7% (11068).
- No source has an alpha channel.
- **HDR** (f4163bf, 4 jobs, 2,831 s, peak RSS 14.0 GiB): 76 renders (33 UltraHDR JPEGs, 19
  `tmap` HEICs, 24 legacy Apple HEICs), 0 errors, 3.76 GB, MaxCLL 315–1,624 nits. The HDR
  oracle passed all 76: mean difference at most 0.48 PQ codes, 99.9th percentile at most
  0.0004 stops, the largest single-pixel differences 0.27–0.29 stops (HEIC decoder edges, as
  below), `cLLI` equal to within 0.2 nits. The 76 gain-map forms read back within 0.0061
  stops of Apple's curve for the legacy maps and exactly for the ISO ones. Two HDR files pass
  GitHub's 100 MiB file limit, 11521 (107.9 MiB) and 11540 (100.4 MiB); 11531 is 99.5 MiB.
  Pillow calls the Samsung gain-map JPEGs malformed MPO files and reads them as plain JPEGs;
  the camera wrote them so (1064's gain map from the 2026-06-04 snapshot of the camera file is
  byte-identical to the export original's).
- **JPEG XL** (f4163bf, effort 9, 6 jobs: 11,305 s for the SDR layers, peak RSS 21.9 GiB;
  2,636 s for the 76 `.hdr.jxl` twins, peak RSS 18.0 GiB): 3 of the 2,112 images failed,
  11415 (108 MP), 12207 and 12402 (99.4 and 101.8 MP, progressive). jxl-encoder reserves 56
  bytes per DCT coefficient for a transcode and caps an unset budget at 8 GiB, its default for
  untrusted input; they asked for 8.4–9.1 GB. render-v4 now passes the run's limits (de6bf54),
  and one JXL redo (5a930e3, 8 s, peak RSS 7.9 GiB) wrote the 6 files. Result: `jxl-p3` 2,112
  files, 3.81 GB (0.414× its PNGs): 1,656 lossless, 43 lossless with `jhgm`, 368
  JPEG-in-JXL, 33 JPEG-in-JXL with `jhgm`, 12 bare codestreams (the progressive Unsplash
  JPEGs); `jxl-srgb` 2,112 files, 4.82 GB (0.502×); 76 `.hdr.jxl`, 2.53 GB (0.673× the
  `.hdr.png` files, the largest 70.6 MiB). No JXL file nears 100 MiB.
- **JXL gate.** The pass's own check failed 79 files: the 3 above and the 76 gain-map files,
  whose kinds (`…+jhgm`) the check didn't know. Fixed (5a930e3: the kind's check plus
  libjxl's `jxlinfo -v` reading the `jhgm` bundle); the full re-check passed 4,300 of 4,300
  files.
- **`.imi`** (the private IMIJ tool, 2026-10-16): 4,300 files, 0 failures. Every file decodes
  to its PNG twin's pixel hash in imij and in imij-oracle and reads back its metadata; the 76
  gain maps decode in both. Sizes and timings stay with the private tool until IMIJ is
  released.
- **Whole-tree gates** (`scripts/render_v4_gates.sh`, 2026-10-16): the PNG read-back passed
  4,300 of 4,300 files; the inventory read all 8,600 PNG and JXL files, 0 violations; the byte
  scan found nothing in `png-p3`, `png-srgb` and `jxl-srgb` and one nested JPEG in `jxl-p3`:
  11231's JPEG-in-JXL `jbrd` box holds the UltraHDR gain-map JPEG, the original's MPF
  secondary image, all 173,712 bytes verbatim. The byte-exact rebuild needs it; brotli stored
  those already-compressed bytes raw here, and compressed them in the other 32 UltraHDR
  transcodes. The owner allowed it on 2026-10-16, on the condition that the gain maps decode
  in jxl-rs, libjxl and zenjxl (below); `manifests/byte_scan_allowlist.tsv` lists it.

### 2026-10-16: licences, gain-map orientation, re-check

- **Licences** (owner decision): the 32 phone screenshots became CC0 and the 12 lkml.org and 5
  Wayback Machine captures plain PD. Redo 2 (3a24186, 12 jobs, 81 s, peak RSS 5.0 GiB)
  re-rendered the 49 images' PNGs; the colour oracle passed them. JXL redo 2 (render-v4 at
  3a24186) wrote their JPEG XL files, and `.imi` redo 1 (zqi c08b4d87) their 98 `.imi` files,
  0 failures in imij and imij-oracle; the provenance text of every file now carries the new
  label.
- **Gain-map orientation.** zenjxl's `GainMapRender::ReconstructHdr` against the PQ renders
  (`tools/jxl-decode-check hdr`), stops over samples at or above 5% of SDR white: the 43
  lossless gain-map files at most 0.006 stops; the 8 unrotated UltraHDR transcodes a median of
  0.0001-0.005 stops (their tail, up to 0.27, is JPEG decoding: zenjxl's decode of the
  JPEG-in-JXL base against zenjpeg's of the JPEG); the 25 rotated ones (Exif orientation 6) a
  median of 0.025-0.198 stops and up to 1.50. Their `jhgm` gain-map codestreams carried
  orientation 1 under a base with orientation 6, so zenjxl laid the landscape map over the
  portrait base. jxl-encoder d73b6c98 gives the gain-map codestream the primary's orientation
  (`tests/it/jpeg_gainmap.rs`, `iso_gain_map_follows_primary_orientation`); render-v4's check
  then compared stored and turned maps and refused all 25 files in JXL redo 2, fixed in
  54b6643 (the JPEG's gain map is turned by the JPEG's orientation first). JXL redo 3 (25 ids,
  270 s and 452 s, peak RSS 17.9 and 27.0 GiB) passed libjxl's check on 75 of 75 files, and
  the 25 now match like the unrotated ones: median 0.002-0.005 stops, at most 0.17-0.23.
- **Gates re-run** after the redos: read-back 4,300 of 4,300, inventory 0 violations on 8,600
  files, byte scan 0 findings plus 11231's allowed one.
- **Three JPEG XL decoders** (`scripts/render_v4_decode_check.sh`, 12 jobs, 20 min; peak RSS
  2.1 GiB for zenjxl and jxl-rs, 7.1 GiB for the HDR comparison): zenjxl, jxl-rs 0.7.4 and
  libjxl v0.12.0 (a7a9c787, built from source because the gain-map bundle parser lives in
  libjxl's extras library) decode all 4,300 JPEG XL files at the manifest's size. All 3,644
  lossless files give their PNG twin's bitmap in all three. On the 656 JPEG-in-JXL files the
  three give three different bitmaps every time, as JPEG decoders do. All 76 `jhgm` gain maps
  decode in all three and line up with the displayed base, the three read byte-identical ISO
  21496-1 metadata equal to the gain-map form's, the 43 lossless maps equal their gain-map
  PNG exactly, and the 33 JPEG-derived maps are within 1-4 code values of zenjpeg's decode of
  the JPEG's own. zenjxl's HDR reconstruction is on target for all 76 (median within 0.01
  stops of the PQ render). Every decoded bitmap's XXH3 is in `decoded-xxh3.tsv` beside the
  layers. The first run flagged the 78 one-bit pages because the libjxl leg reported the
  header's bit depth (1) instead of the 8-bit samples it decodes; the bitmaps were identical.
  It also showed that zenpng's and zenjxl's default decode limits (120 MP) refuse the 124 MP
  panorama 11449; the check passes explicit limits, as render-v4 does.

### 2026-10-17: reader census

`scripts/render_v4_compat_census.py` reads each distinct file of the four layers (4,976 files
behind 8,600 paths) with 21 readers in the compat matrix images: Ubuntu 24.04 packages
(`imazen26-compat:lts`: libjxl 0.7.0, ImageMagick 6.9.12, GraphicsMagick 1.3.42, vips 8.15.1,
Pillow 10.2.0, gdk-pixbuf 2.42.10, OpenCV 4.6.0, Qt 6.4.2, ffmpeg 6.1.1, Netpbm 11.5.2), Arch
Linux (`:latest`: libjxl 0.12.0, ImageMagick 7.1.2-30, GraphicsMagick 1.3.48, vips 8.18.6,
Pillow 12.3.0, gdk-pixbuf 2.44.7 with glycin, OpenCV 5.0.0, Qt 6.11.2, ffmpeg 9.0.1, Netpbm
10.86.50) and Chromium 153, Firefox 155 and WebKit 26.6 (`:browsers`). Each reader runs in a
container with no network, a read-only root, 2 CPUs and a memory cap without swap.
`tools/jxl-decode-check compare` hashes every output (XXH3-64 in its own layout and as 8-bit
RGBA) and compares it with our decode (zenpng, zenjxl) and, for a wide-gamut file, with an sRGB
reference. `compat-census/census.tsv` holds one row per file and reader, `memory.tsv` each
container's cap and peak.

**PNG:** 2,488 files, 52,248 decodes, 0 unexplained.

| outcome | decodes |
|---|---|
| the same samples | 38,748 |
| the same pixels as 8-bit RGBA (the reader returns another layout) | 12,240 |
| Display P3 converted to sRGB, within 1 of our sRGB twin: Chromium and WebKit 299 each, gdk-pixbuf 2.44 2 | 600 |
| a PQ file shown as SDR or narrowed to 8 bits: Chromium, WebKit, Pillow, OpenCV, gdk-pixbuf (both images) | 608 (76 each) |
| over Qt's default image limit, 128 MB in 6.4.2 and 256 MB in 6.11.2 | 52 (47 and 5) |

**Transport.** The first PNG pass (2026-10-16, `census.data-url-2026-10-16.tsv`) handed the
browsers each file inside a `data:` URL, as the compat matrix's adapter does: WebKit failed every
file of 51.5 MB and up, and Chromium's renderer crashed on every file of 87.6 MB and up. The
census now serves the files over loopback HTTP (3958a5d). On the 327 files both passes read,
all 6,817 (file, reader) pairs that decoded in both gave the same bitmap, 948 of them in
browsers; 33 browser reads that had failed now decode (10 Chromium, 23 WebKit), and 17 Qt
refusals stayed.

**Memory.** The first full run held 12 containers of 8 GB, with docker's default swap allowance
of as much again. When it reached the JPEG XL files at 02:43Z, Ubuntu 24.04's ffmpeg grew to
the cap on each one, and dev ran out of memory for an hour; at 03:43Z the kernel's OOM killing
took down the session's systemd user manager, and the census and other running jobs with it.
The census now caps each container by the chunk's largest file, without swap, and keeps the caps
of the running containers and the compare steps within one budget (1b7e45c8; 20 GB). The 119
JXL files read in that hour are kept in `census.jxl-oom-2026-10-17.tsv` and were read again.

Three findings on the first JXL files changed the census before the JXL half ran:

- **ffmpeg 6.1 and the JPEG XL container.** Ubuntu 24.04's ffmpeg (6.1.1, libjxl 0.7.0) read
  none of our container files: it prints `invalid signature` from libjxl without end, the
  adapter's bash holds the text until the container's cap kills it, and on a test file with
  the output kept the error stream reached 25 GB in five minutes. The same file's bare
  codestream decodes, to our decode exactly; ffmpeg 9.0.1 reads the containers. libjxl 0.7.0's
  own `djxl` reads them too.
- **Orientation.** ImageMagick and GraphicsMagick read a JPEG XL file's orientation as
  metadata and return the stored pixels (62 transposed outputs and 2 turned 180° of 119 files).
  Turned by the orientation, ImageMagick's output equals our decode within 1 (orientations 3
  and 6 checked). Compare now also matches an output against our decode in the stored
  orientation (b6186507).
- **Colour management of wide-gamut JPEG-in-JXL files.** WebKit and gdk-pixbuf 2.44 (glycin,
  with jxl-oxide) convert these files to sRGB and missed our sRGB twin by 5 to 30 on all 77
  such files in that hour. The twin is made from the PNG layer, a different decode of the same
  JPEG, which lands up to 4 code values from the JXL's decode (11010); converting from P3 to
  sRGB magnifies that where a saturated colour puts an sRGB channel near zero. glycin's output
  on 11010 is libjxl's 8-bit decode converted by LittleCMS (within 3), and our twin is the
  LittleCMS conversion of the PNG (within 1), so both sides convert correctly. Every
  libjxl-based reader and glycin decode these files within 1 code value of zenjxl. Compare now
  converts our decode of each of the 170 files to sRGB as render-v4 makes the sRGB layer and
  accepts a sample within what a decode 1 code value from ours becomes after the conversion,
  plus 2 (0c5ed595; its message says 13 to 30 on 95 files, the measured figures are 5 to 30
  on 77).

**JPEG XL:** 2,488 files, 52,248 decodes, 0 unexplained (`scripts/build_v4_review.py census
<render> jxl` counts them per reader).

| outcome | decodes |
|---|---|
| the same samples | 20,400 |
| the same pixels as 8-bit RGBA | 1,917 |
| within 1 code value: mostly JPEG-in-JXL files, which libjxl decodes within 1 of zenjxl (412 or 413 in each libjxl-based reader) | 3,927 |
| Display P3 converted to sRGB: WebKit within 1 of our sRGB twin (129); WebKit and glycin within tolerance of our decode converted to sRGB (170 each, ±2 to ±18) | 469 |
| orientation left to the caller, within 1 of our decode in the stored orientation: ImageMagick 7, GraphicsMagick 1.3.42 and 1.3.48 | 408 (136 each) |
| a PQ file shown as SDR or narrowed to 8 bits: WebKit, glycin, OpenCV 5 | 228 (76 each) |
| JPEG decoding, ±2 (WebKit) | 3 |
| gray re-encoded with a gamma 2.2 curve (glycin; below) | 37 |
| 1-bit samples written as 0 and 1 (djxl 0.7; below) | 39 |
| no JPEG XL support: Chromium, Firefox, Pillow 10.2 and 12.3, Qt 6.4 and 6.11, ImageMagick 6.9, OpenCV 4.6, gdk-pixbuf 2.42 | 22,392 (2,488 each) |
| ffmpeg 6.1 on a box after the codestream (below) | 2,311 |
| 1-bit files not read: GraphicsMagick 1.3.42 and 1.3.48, OpenCV 5 (below) | 117 (39 each) |

- **ffmpeg 6.1 and boxes after the codestream.** This corrects the first finding above, which
  came from the first 119 files. Over all 2,488, Ubuntu 24.04's ffmpeg read 177, all within 1
  of our decode: the 12 bare codestreams and the 165 JPEG-in-JXL containers whose last box is
  the codestream (`jxlp jbrd jxlp`). It failed on all 2,311 files with a box after the
  codestream: the `xml ` box of the lossless files' provenance XMP, `brob` Exif or XMP boxes,
  or `jhgm`. Each loops until the container's cap kills it, except 3 that crashed at their
  3.5 and 8.5 GB caps. Checked on reordered copies (2026-10-17):
  - A 3 KB lossless file decodes exactly with its `xml ` box moved ahead of the codestream or
    dropped, and loops with the box after it.
  - Three more layouts decode exactly once reordered: a JPEG-in-JXL file with Exif, a
    lossless file with a gain map, and a JPEG-in-JXL file with Exif, XMP and a gain map.
  - 15002 (42 MP), one of the crashes, decodes once reordered.
  - libjxl 0.12's `cjxl` writes these boxes between the codestream parts (`jxlp jbrd brob brob
    jxlp`), and ffmpeg 6.1 reads that layout exactly too.
  - libjxl 0.12, zenjxl and jxl-rs decode the reordered files to the same pixels and gain
    maps, and libjxl rebuilds the same JPEG bytes from them.

  Our files have the boxes after the codestream because jxl-encoder writes the XMP and Exif
  there and `zenjxl::append_gain_map_box` appends `jhgm`. Moving them ahead would make the
  JPEG XL layers readable by Ubuntu 24.04's ffmpeg. That needs a change to those crates and a
  re-render, and has not been made. (Made the same day without a re-render: JXL redo 4
  below.)
- **1-bit files.** The codestream header of each of the 39 patent pages named `-1bit_` says 1
  bit per sample: render-v4 keeps a sub-byte gray depth. These readers return the same pixels
  as zenjxl, jxl-rs and libjxl do in the decode check: djxl 0.12, ffmpeg 9, ImageMagick 7,
  vips 8.15 and 8.18, WebKit and glycin. These do not:
  - GraphicsMagick 1.3.42 stops with `Invalid colormap index (index 255 >= 2 colors)`.
  - GraphicsMagick 1.3.48 stops with `An error has occurred reading from file`.
  - OpenCV 5.0's `imread` returns nothing.
  - libjxl 0.7's `djxl` writes them into an 8-bit PNG as 0 and 1 instead of 0 and 255.
    libjxl 0.7 itself reads them correctly under vips 8.15.
- **glycin and gray JPEG XL.** glycin 2.1.5 (gdk-pixbuf 2.44.7) returns the 37 gray
  JPEG-in-JXL files (the patent rescans and one Met manuscript) up to 9 code values lighter.
  - The mapping is the same on every pixel of every file: 2v below 8; from 8 up, the sRGB
    value re-encoded with a plain 2.2 power (8 → 17, 16 → 23, 32 → 37, 64 → 66); within 1
    from 73 up.
  - The files' headers say gray with the sRGB transfer function. libjxl, WebKit and OpenCV
    agree with our decode within 1.
  - A gray gradient encoded by cjxl, lossless and lossy, shows the same curve, and the same
    gradient as a PNG reads exactly. The cause is glycin's handling of gray JPEG XL, not these
    files.
- **Memory.** The JPEG XL half ran 4 h 52 min within the 20 GB budget, and available memory
  stayed at or above 8.7 GiB. Only Ubuntu 24.04's ffmpeg containers had OOM kills (the loops
  above). The largest cap was 11.5 GB (Chromium on the 124 MP panorama). The largest peak
  outside that ffmpeg was vips 8.15's 5.7 GiB on the same file, at an 8.5 GB cap.

### 2026-10-17: libjxl's box order (JXL redo 4)

The owner's call after the census: "if libjxl does box orders that way we should too", and
"match 1 bit files".

- **libjxl's order.** libjxl's encoder (`encode.cc`, `ProcessOneEnqueuedInput`, v0.12) puts
  the codestream header (signature, SizeHeader, ImageMetadata, CustomTransformData, ICC
  profile) in its own first `jxlp` box when boxes come before the frames, then those boxes,
  then the frames in the last `jxlp`. cjxl queues Exif, XMP, JUMBF and `jhgm` that way, and a
  JPEG transcode puts its `jbrd`, Exif and XMP there. No box follows the codestream.
  jxl-encoder 11ffbf9c writes the same order (main a8c9fd78; zenjxl 5b593da2 does it for
  animations). The layers now read:

  | layout | files |
  |---|---|
  | `JXL ftyp jxlp xml jxlp` (lossless) | 3,525 |
  | `JXL ftyp jxlp jbrd jxlp` (JPEG-in-JXL without metadata) | 328 |
  | `JXL ftyp jxlp jbrd brob(Exif) jxlp` | 235 |
  | `JXL ftyp jxll jxlp xml jxlp` (16-bit PQ, level 10) | 76 |
  | `JXL ftyp jxlp xml jhgm jxlp` (HEIC gain-map form) | 43 |
  | `JXL ftyp jxlp jbrd brob(xml) jxlp` | 36 |
  | `JXL ftyp jxlp jbrd brob(Exif) brob(xml) jhgm jxlp` (UltraHDR) | 33 |
  | bare codestream (no reconstruction data) | 24 |

- **Checked against libjxl.** jxl-encoder finds the header's end by parsing the header (an
  embedded ICC profile by encoding the encoder's profile again and checking the bits). On 20
  files cjxl v0.12 wrote with Exif or XMP (lossless and lossy, 1-bit and 8-bit gray, 16-bit,
  P3, PQ, gamma, orientation, intensity target, a 3-frame animation, JPEG reconstruction) it
  splits where cjxl split (`examples/libjxl_header_split.rs` in jxl-encoder).
  `scripts/render_v4_jxl_check.py` now fails any file that is not in libjxl's order.
- **Found on the way:** jxl-encoder wrote the intrinsic size in a form neither libjxl nor
  jxl-oxide could read (fixed in 5923e603). No v4 file sets it.
- **1-bit files.** cjxl v0.12 also writes the 1-bit pages as 1-bit grayscale JPEG XL. From
  our PNG twin it writes a codestream header identical to ours, Perceptual intent included
  (from the twin's sRGB chunk; from the original, which has no colour chunk, it writes
  Relative). GraphicsMagick 1.3.42 and 1.3.48 and OpenCV 5 refuse cjxl's own 1-bit file with
  the same errors as ours, and libjxl 0.7's `djxl` writes it as 0 and 1 too. So the 1-bit
  files already matched libjxl; only their box order changed.
- **Rewritten, not re-encoded.** A trial render of one id of each kind (11 ids, 25 files,
  render-v4 jxl at effort 9) gave every file the codestream it had before. A full re-render
  would have repeated 3 h 52 min of effort-9 encodes to move boxes, so JXL redo 4
  (`scripts/render_v4_jxl_remux.sh`, render-v4 87eb975f) rewrote the containers instead:
  `render-v4 jxl-remux` passes each `jxlc` file through the calls `jxl` makes
  (`jxl_encoder::wrap_in_container`, then `zenjxl::append_gain_map_box`) and moves a
  JPEG-in-JXL file's trailing boxes ahead of its frames. It matches render-v4 jxl byte for
  byte on 431 of 431 files (the trial's 25 and the 406 a stopped full re-render had
  finished). All 4,300 files took 218 s (12 jobs, peak RSS 1.2 GiB); the old layers stay in
  `before-box-order/`.
- **Checks.** The JXL check passes 4,300 of 4,300 files, box order included. Every
  codestream is the old file's (`scripts/jxl_codestream_compare.py`). The manifests change
  sha256 for 3,948 files (the 352 with no box after the codestream keep theirs) and size by
  16 bytes for the lossless ones (two `jxlp` headers for one `jxlc`). The inventory
  (`jxl-decode-check jxl-inventory`, which reproduces the zencodecs CLI's rows on all 4,300
  old files) lists every metadata box with the disposition it had: the 3,644 `xml ` and 337
  `brob` boxes read as metadata, `jbrd` and `jhgm` as before; 0 gate violations on 8,600
  files. Byte scan: nothing new. The three decoders give the same bitmaps as before:
  `decoded-xxh3.tsv` is byte-identical to the 2026-10-16 one.
- **Readers.** The census read the 2,488 distinct rewritten files again: 0 unexplained of
  52,248 decodes. Ubuntu 24.04's ffmpeg 6.1 now reads all of them: the 2,075 lossless files
  (the PQ and gain-map-form files included) give our decode's samples, and the 413
  JPEG-in-JXL files are within 1 code value, as in the other libjxl-based readers. The other
  49,937 (file, reader) pairs, ffmpeg 6.1's 177 earlier reads among them, gave the same
  output as before the rewrite: the same status, XXH3 and differences. In the census table
  above, "the same samples" becomes 22,475, "within 1 code value" 4,163, and the ffmpeg 6.1
  row is gone; the review no longer excuses an ffmpeg 6.1 failure (68d12aa). The run took
  4 h 17 min with 12 jobs in the 20 GB budget, with no OOM kill or failed container and at
  least 26.9 GiB available; the largest peak was 5.7 GiB (vips 8.18 and ffmpeg 6.1 on the
  124 MP panorama, at an 8.5 GB cap). The earlier JXL rows are in
  `compat-census/census.jxl-before-box-order-2026-10-17.tsv`.

### 2026-10-19: lossless progressive JPEG twins (JXL redo 5)

Owner decision applied to export ids 12003, 12005, 12009, 12012, 12013, 12022,
12203, 12204, 12207, 12212, 12402 and 12409: replace the coefficient-only fallback
with lossless encodes of the PNG twins in both families. This is 24 files; no other
image changed. Current JXL coverage is 3,668 lossless files and 632 JPEG-in-JXL
files, including 76 `jhgm` gain maps. The earlier counts above describe their dated passes.

Renderer source `1699c213`, jxl-encoder `bcd8eecb`, zenjxl `3f5e22e9`, effort 9,
three jobs. The recorded render lock has SHA-256
`6e831eba2300d84f22fbd8f6609bc806dca1b2f6709f81324b059ae36bdd89cc`.
All 24 outputs match the earlier measured candidate bytes exactly. Their individual
sizes are in the [measurement pointer](progressive_lossless_2026-10-19.pointer.md).
The largest is 68,717,977 bytes, below 100 MiB. Excluding the five XL ids, including
12402, P3 totals 6,297,804,440 bytes and sRGB 4,903,867,897 bytes, both below 10 GB.

All 24 pass libjxl box-order, colour and pixel readback; zenjxl, jxl-rs 0.7.4 and
libjxl 0.12.0 give exactly the PNG twins' samples (96 decoder rows including PNG).
Native inventory passes all 24 routes, and both byte scans have zero findings.
The canonical render retains all replaced files, reports and manifests under
`before-jxl-redo-5/`, with the new evidence in `jxl-redo-5-evidence/`. `RUN.meta`
and both JXL manifests record the pass. The full 17,276-row `decoded-xxh3.tsv`
replaces exactly the 72 affected JXL decoder rows; all 72 bitmap hashes change as
expected when coefficient decoding becomes an exact PNG twin. The other 17,204
rows remain identical. Its previous table is retained separately.

A lossless progressive-to-sequential JPEG transform succeeded on all twelve
originals: quantization tables, component descriptions and coefficient hashes
remain identical, and JPEG decoded pixels have maximum difference zero. Native
inventory covers all 36 original JPEG, rewritten JPEG and rewritten-JXL inputs
and finds `jbrd` in all twelve rewritten JXLs. Both native and libjxl reconstruction
return each sequential JPEG byte-for-byte. This would preserve coefficients and
pixels while rebuilding the transformed sequential file, rather than the original
progressive bytes; the corpus uses the PNG-twin path instead.

Resource records: encoding 926 s, run-heavy peak RSS 12.65 GiB, minimum available
37,648 MiB; the three-reader/twin/inventory/byte-scan gate 254 s, peak RSS 1.34 GiB,
minimum available 48,649 MiB. Tooling: `f984cf0c`; hash-table merging is recorded
with this validation update. The other stored P3/PQ and grayscale rendering-intent
headers retain their existing values.

**Reader census top-up, 2026-10-20.** After the four dataset repositories were
published, the census read the redo-5 replacements: 12 distinct encoded hashes
covering all 24 paths, with 252 rows from 21 readers. All 144 successful decodes
match our samples (128 natively, 16 as RGBA8); the other 108 rows are readers
without JPEG XL support. The unchanged verdict command reports **52,500 stored
JXL rows, 2,500 hashes, zero unexplained**. This includes 252 preserved rows for
the old encodes; the current files have 52,248 rows over 2,488 distinct hashes.
The original table is an unchanged prefix of the appended table.

The selected run used `--jobs 2 --mem-budget 16`; all 168 reader containers
finished without OOM kills. Full aliases still cover all 8,600 current PNG/JXL
paths. The public builder selects rows by current encoded hash, avoiding 252
duplicate path/decoder identities from historical rows. The browser check now
rejects duplicate identities. The [public review](https://imazen-26-review.pages.dev/)
was redeployed and checked: 2,112 tiles, full-resolution viewing, a byte-exact
40,591,101-byte hash download, 197,876 unique identities and zero duplicates,
HTTP 404 for a missing path, and no page or request errors. See the
[top-up evidence](review_topup_2026-10-20.pointer.md) for commands, deployment,
resource records and preserved artifacts. No image was re-encoded.

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
  174e01e5). zenpixels didn't identify this 520-byte profile, which tags 31 of the 32 mobile
  screenshots (the 32nd is an sRGB JPEG) and 10 phone screenshots filed under interiors and
  nature; the full run refused those 41. icc-gen identifies it as Display P3 with the sRGB
  curve, maximum u16 error 1, no LittleCMS disagreement. The 41 images are re-rendered with
  `scripts/render_v4_redo.sh`; six control images rendered with the new toolchain are
  byte-identical to the first run's files.
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

## Buckets

Every export bucket follows the successor family map, `manifests/split_map_family_v2.tsv`
(owner decision S1): a patent page's 1-bit original and both rescans, the pages of one URL, a
photo burst, a plot run and chart theme variants share one bucket.

- **Fixed: the full run's provenance named the wrong bucket for 270 images** (ee56da7).
  `scripts/render_v4_list.py` wrote each id's last-digit bucket, so page 1 of us5046022 had
  its 1-bit original in train and both rescans in test. 270 of the 2,112 rows differ: 143 web
  pages, 67 patent rescans, 39 burst photos, 17 plots and 4 charts. The pixels were right;
  the `tEXt` chunk of both their PNG files was not. The list now takes the family map's
  bucket, `export_sizing.py` refuses a list that disagrees with it, and the 270 images are
  re-rendered with the redo.

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
- **The 12 progressive Unsplash JPEGs** initially used a coefficient-only codestream;
  2003 decoded within 4 code values of zenjpeg's JPEG decode. Owner-approved JXL redo 5
  replaces all 24 family files with exact lossless PNG twins; see the dated results above.
- **Effort** (8 sources, both layers, under load): e5 47.4 MB in 39 s, e7 44.0 MB in 75 s,
  e9 41.3 MB in 507 s. JPEG-in-JXL sizes are equal at e7 and e9 (owner question 7).
- **libjxl's box order** (JXL redo 4, 2026-10-17): the codestream header in the first `jxlp`
  box, then `jbrd`, Exif, XMP and `jhgm`, then the frames, and no box after the codestream.
  The check fails a file in any other order.
- **Rendering intent differs from cjxl's on 3,566 of the 3,644 lossless files** (measured
  2026-10-17 with cjxl v0.12.0 on one PNG twin of each kind; historical v4 headers). cjxl
  takes the intent from the PNG: the twins' `sRGB` chunk says Perceptual, and a `cICP` chunk
  leaves the spec default, Relative. jxl-encoder ignores the input's intent:

  | lossless files | PNG twin | cjxl | ours |
  |---|---|---|---|
  | sRGB (3,360) | `sRGB` chunk, Perceptual | Perceptual | Relative |
  | Display P3, with or without `jhgm` (130) | `iCCP` + `cICP` 12/13 | Relative | Perceptual |
  | P3 PQ (76) | `cICP` 12/16 | Relative | Perceptual |
  | 1-bit gray (78) | `sRGB` chunk, Perceptual | Perceptual | Perceptual |

  Primaries, white point and transfer function agree on every kind. The JPEG-in-JXL headers
  equal cjxl's transcode of the rebuilt JPEG on all 6 colour kinds sampled (four ICC
  profiles, sRGB and gray). The intent does not change decoded samples, and the census
  readers that colour-manage matched our references with the current intents. jxl-encoder's
  `docs/LIBJXL_DIVERGENCES.md` records that measurement (33ae2413).

  **Owner decision, 2026-10-19: Relative for JXL constructors, code only.** render-v4
  hard-codes intent 0 (Perceptual) in the PNG `sRGB` chunk (`main.rs`); the old
  jxl-encoder constructors held Perceptual, while the sRGB compact header serialized
  Relative, and zenjxl hard-coded Perceptual when mapping CICP. jxl-encoder
  `21cd3e47` makes the constructors/default Relative and keeps sRGB's one-bit header
  byte unchanged; zenjxl `586952a5` maps CICP to Relative. The constructor tests read
  the intent with jxl-rs and read lossless samples with jxl-rs and libjxl v0.12;
  the wrapper tests read Relative and identical samples for P3 and P3/PQ.

  No general re-encode, remote worker or zencodec/zenpixels plumbing is part of this
  decision. The existing table remains the description of the stored v4 headers:
  the 206 P3/PQ files (and the gray files) retain their older intent until a re-render
  is authorized for another reason. PNG keeps its intent 0. The PNG/JXL twins' colour
  encodings can differ in this no-op intent field while their lossless samples agree.

### Gain-map form (`jhgm`)

- UltraHDR JPEG-in-JXL: the transcode carries the JPEG's MPF gain map as a `jhgm` box and
  the original still rebuilds byte for byte; its gain map decodes within 2–3 code values of
  zenjpeg's decode of the JPEG's own.
- HEIC: render-v4 appends `jhgm` to the lossless `p3` file. A `tmap` map goes in unchanged
  (HDR from the box equals the source's, 0.0000 stops); a legacy Apple map is re-quantized
  onto an ISO curve (min 0, max = headroom, gamma 1, no offsets): 0.0059–0.0060 stops from
  Apple's curve, as `benchmarks/apple_legacy_gainmap_iso_fit_2026-10-03.md` predicted.

## `.imi`

The `.imi` layers are written from the PNG layers by a private tool in the IMIJ repository:
each file holds its PNG's samples, colour (CICP 1/13, 12/13 or 12/16; Adobe RGB as the ICC
profile), `cLLI` and provenance (the same XMP packet as the JPEG XL files), and a gain-map
source's `p3` SDR file carries the `gain-maps/` form as its ISO 21496-1 gain map. Each file
is decoded again before it is written. The check decodes every file with imij and with
imij-oracle, a second decoder written from the format specification alone, against the PNG
twin's pixel hash, reads the metadata back, and decodes each gain map with both.

The gain-map forms come from `render-v4 gain-maps` (f4163bf), which writes each source's
form once, under `gain-maps/`: the map in ISO 21496-1 form, oriented like the `png-p3` base,
as an 8-bit PNG, and its metadata as the bare ISO 21496-1 payload a `jhgm` box carries. HEIC
sources get the form their JPEG XL file carries; UltraHDR JPEGs keep their own map, decoded
by zenjpeg like the base. The HDR the read-back form gives is compared with the source's
own: on four test sources (an UltraHDR JPEG, a legacy Apple HEIC, two `tmap` HEICs), 0.0036
stops for the Apple map and 0.0000 for the ISO ones.

On the nine-image test set (sRGB, assumed sRGB, Display P3, Adobe RGB, a 1-bit page, an
UltraHDR JPEG, a legacy Apple HEIC and two `tmap` HEICs): 22 files, all pass both decoders.

## Inventory and byte scan

Both gates were written for the originals' 4-digit names and would have passed the
5-digit export names without checking anything; they now take both and refuse an empty
input. On the 76 test renders (PNG and JXL, SDR and HDR): 0 inventory violations (JXL parts:
`jbrd`, `jhgm`, `jxll`, the JPEG's own brotli Exif and XMP), 0 byte-scan findings. The
inventory CLI is zenpipe's `feat/inventory` branch (PR #89), not main.
