# Compatibility matrix: image readers vs signalling variants (2026-10-07, final round 14)

Synthetic fixtures authored by `tools/compat-matrix` (Zen encoders +
byte-level container writers, no third-party authoring; the five AVIF
matrix-coefficient fixtures encode through the pinned zenavif (which
always converts YCbCr BT.601) with the coded stream's sequence-header
matrix patched bit-exact so container `nclx` and stream agree), decoded
by reader
adapters in Docker: `imazen26-compat:lts` (`sha256:4a0588fe…`, Ubuntu 24.04
+ libultrahdr v1.4.0), `imazen26-compat:latest` (`sha256:3d9c7a4a…`,
Arch, a full reader generation newer), `imazen26-compat:browsers`
(`sha256:14ff6211…`, Playwright 1.63: Chromium 153 / Firefox 155 /
WebKit 26.6, screenshot + canvas modes). Plus two native Zen columns —
`zen` (managed decode) and `zen-raw` (raw decode, control) — on the
host. **120 fixtures × 35 adapters → 4,200 matrix cells per image set**
(per-image-set status counts in `summary.tsv`).

Machine-readable output: `/mnt/v/output/imazen-26-compat/2026-10-07-r14/`
(LTS + census + metadata), `-latest`, `-reps`, `-reps-latest` (45 corpus
representatives × 35 adapters), each with `SHA256SUMS`, a `fixtures/`
archive, per-class `.tsv.gz` extracts under `results-export/` (pointers:
`tools/compat-matrix/results/*r14*.pointer.md`).

Provenance: every cell JSON records `image_id` (docker image sha, or
`host` for the native zen/signalled passes), `adapter_sha` (adapter
script or probe binary sha256) and `fixture_sha` (exact input bytes;
browser cells post-stamped); checkpoints reuse only when all three
match. `platform.txt` records the image IDs and
adapter shas; `--check` refuses cells with empty or unlisted producer
identities — `image_id=host` is admissible only when `platform.txt`
carries a positive `host_adapter=<name>` marker for that adapter (the
`sweep_zen.sh`-written lines; the bare `adapter=` sha lines pin the
binary), and the `container_adapter=` markers refuse host identities on
docker/browser cells. Phase-1 capability probes write
`probe/<adapter>.json` sidecars, never cells, so a probe failure cannot
launder a baseline error into `n/a`. Reps renders
are hash-pinned: `output_sha` per `ok` cell at
decode time; non-zen renders are then replaced by ≤1024 px thumbnails
recorded as `thumb_sha` (`--check` refuses a PNG hashing to neither),
so cell pixels and hypotheses converge in `corpus_space` (≤1024 box →
≤512). Zen renders stay full-resolution. `--check` re-derives
`matrix.tsv`/`versions.tsv`/`separations.tsv`/`summary.tsv` and
byte-compares, re-verifies the census `thumb_sha`/`output_sha` stamps
and flags expected-but-missing cells. `calibration.tsv` +
`calibration-detail.tsv` are written **beside `hypotheses.tsv` in the
fixtures dir** — the calibration is an artifact of the hypothesis set —
and each run dir keeps an archive copy; `--check` fails on a mismatch.

Fixtures regenerate deterministically (`compat-matrix generate` → verify
gate re-parses every file against per-fixture expectations: segment/box
structure, orientation tags, `mime` types, nclx code points, `ipco`
compaction, tile-`colr` tokens). The HEIC fixtures pin a canonical
donor — the iPhone-8-Plus HEIC at `~/work/codec-corpus/imazen-26`,
sha256 `4a567974…` (per-row `donor_sha` in `fixtures.tsv`). ICC identity
is enforced by `scripts/icc_identity_check.py` at sweep preflight —
embedded profiles compare against **independent references** (lcms2's
built-in sRGB plus canonical profiles generated in-repo from published
primaries/white/transfer, Bradford→D50), at MAD < 0.05 / max ≤ 1 with a
perturbed-`bXYZ` negative test that must fail. Hypothesis renders are
lcms2-transformed from decode bases cached under fixture-content sha +
decode-command template + reference-toolchain identity (command or
image change re-keys) — HEIC bases via heif-convert (libde265)
from a remux that drops `irot`/`imir`/`clap` so no display transform is
applied (each `stored` render asserted against the primary item's `ispe`
dims; iPhone reps whose `auxid:2` depth aux libheif 1.17 rejects decode
via a depth-dropped remux), DNG/raw via LibRaw (`dcraw_emu -w -t 0
-T -6` — 16-bit TIFF decoded, graded at 8-bit PNG precision; no
auto-rotate so `stored` is the true sensor raster), AVIF/JXL
`gainmap-applied` applied in-generator via `ultrahdr_core` from the
authoring HDR buffer — never through the reader under test. (See the
grading caveat in the HEIC section.)

Classification: pattern fixtures score per-patch channel means through
orientation-mapped rects (4 channels when alpha is signalled); corpus
fixtures score whole-image p99/max in `corpus_space`. Per-run calibrated
thresholds T from the fixtures dir's `calibration.tsv` (r14: synthetic
2/2/24, corpus reps 5/3/4 lossy/lossless/corpus). The corpus bucket is
the cross-decoder noise bound: measured only on fixtures whose `correct`
reading carries no colour or orientation signal to interpret (orient-1
untagged/sRGB reps, `heic-colr-srgb`, `heic-nocolr`, `heic-irot0`,
`heic-tile-base`, `heic-exif-orient6` — ICC/nclx-signalling HEICs are
excluded so the cells T grades cannot set it), as the distance to
`correct` on the cell's raw pixels — not nearest-hypothesis, not the
better of raw/tagged. The fold is explicit decode-contract columns only
(synthetic: imageio/imageio-best/imageio-raw + wic/wic-best/wic-raw,
which land 23.00/21.00 on the signal-free HEIC set; reps: imageio-raw +
sips, 2–3.00) — rendered-thumbnail paths (Quick Look, NSImage,
sips-srgb) are never folded. `.unm` rows complete the HEIC bound: each
HEIC rep is remuxed by `probe --remux --drop-transform --unmanaged` (the
file `stored` renders from) and decoded by latest ffmpeg's native HEVC
path and zen/zen-raw (ffmpeg 2–14.00, zen/zen-raw 1.00 vs the libde265
`stored` base; LTS ffmpeg has no HEIF demuxer and records honest `error`
cells). The synthetic
runs are pooled into one T (fixtures-dir artifact, `--check`-enforced),
the two reps runs likewise; every contributing column is named in the
`decoders` column. A cell between mutually-indistinguishable hypotheses
(*collapse pair*: renders within the fine decode-noise bound FINE_T=2 —
the wide corpus T only picks the nearest) reports `not-measurable` only
when the pair contains `correct`; separable incorrect readings name the
actual one (`correct=false`). A tie — the two nearest hypotheses within
FINE_T of each other — certifies only when it lands *within* T and the
tied pair contains a correct-labelled reading (`not-measurable`, true);
a within-T tie with no correct member is `not-measurable`/false, and a
tie *beyond* T is plain `other`/false — distance keeps meaning
something. Corpus verdicts also need the runner-up ≥2× farther than
best (margin failure → `not-measurable`, never `correct`).

Every cell is scored twice, both readings in `matrix.tsv`: **raw** —
the emitted pixels as-is (`verdict`/`d1`/`d2`, the historical reading)
— and **tagged** — the output PNG's colour declaration interpreted to
sRGB first (`verdict_tagged`/`correct_tagged`/`d1_tagged`/`d2_tagged`,
the declared tag in `out_profile`). Precedence follows PNG-3 §11.3.2:
cICP > iCCP > sRGB > gAMA+cHRM; an sRGB-equivalent ICC, sRGB cICP or an
sRGB chunk short-circuits (no conversion); a `gAMA+cHRM`-only output
converts with the declared power curve + primaries (`gama-chrm:<name>`).
When the raw pixels already sit on a named reading within FINE_T and
the declared tag describes the *source* space, the tagged reading
reports `mis-tagged:<raw verdict>`; an output profile the pipeline
cannot convert that declares HDR (PQ/HLG TRC, or an ICC description
naming PQ/HLG/HDR) reports `hdr-output` (correct=n/a — see `hdr/`).
Orientation evidence never depends on the colour verdict: on fixtures
with more than one expected orientation, `orientation_ok` grades the
orientation axis alone. `n/a` is emitted only when the adapter declares
the format unsupported — errors and crashes on supported formats are
counted failures; a webkit-canvas all-zero readback is `flaky`, kept out
of `summary.tsv` error counts and `diff_runs.py` move tallies.


## Status (2026-10-19): where this work stopped

- **Stopped at round 14 by the owner** (2026-10-17). Rounds 1–13 each had an independent review
  (verify-only, `~/tmp/handoff/compat-review*/` on dev); round 14 fixed review 8's findings and was
  not reviewed again. The round-14 exports are the final data: `2026-10-07-r14`, `-latest`, `-reps`,
  `-reps-latest` (4,200 synthetic cells per image set, 1,575 per reps set), mirrored to tower under
  `imazen-26-compat-archive-2026-10-07/r14/`.
- **Checked when this landed** (2026-10-19, tool at this commit): `cargo fmt --check`,
  `cargo clippy --all-targets -D warnings` and the tests pass, and `compat-matrix matrix --check`
  passes on all four round-14 exports. The only cells it names as missing are the two LTS ffmpeg
  6.1 JPEG XL cells that crash the reader (`jxl-exif-orient6`, `jxl-jhgm`), kept out on purpose.
- **Platforms:** the Mac was retired 2026-10-18, so the macOS columns stay at round 14 (macOS 27.0,
  ImageIO 3.3.0) and the Safari column never produced data. The shipped Chrome 155 and Firefox 157
  adapters live in imazen/image-compat.
- **Where the results went:** the synthetic-fixture findings are public as
  `zenpipe/docs/reader-compat.md` (imazen/zenpipe 9019cd64) and on the image-compat site; the
  encoder-default recommendations are in imazen/zencodec#132 and imazen/zenpixels#84. The render v4
  reader census (every shipped file through these readers, 104,496 decodes, 0 unexplained) is in
  `render_v4_validation_2026-10-15.md`.
- **Known open items:** the corpus census below ran on the pre-v4 corpus copy. `tools/compat-matrix`
  here is the tool's only copy: the planned copy into imazen/image-compat (its site and adapters
  live there) was not made.

## Reader versions

**LTS image**: libjpeg-turbo 2.1.5, Netpbm 11.5.2, WebP 1.3.2, libheif
1.17.6, libavif 1.0.4, libjxl 0.7.0 (djxl), IM 6.9.12-98, GM 1.3.42,
libvips 8.15.1, FFmpeg 6.1.1, Pillow 10.2.0, OpenCV 4.6.0, GDK-Pixbuf
2.42.10, Qt 6.4.2, LibRaw 0.21.2, libultrahdr v1.4.0. Browsers: Chromium
153, Firefox 155 (screenshot + canvas + cm=2 profile — pref read back
from `prefs.js`), WebKit 26.6. Native: zen 0.1.0 (probe binary sha
`8377b4fa…` recorded per cell).

**Latest image**: libheif 1.23.2, libavif 1.4.2, libjxl 0.12 (djxl),
IM 7.1.2-30, GM 1.3.48, FFmpeg 9.0.1, OpenCV 5.0.0, Pillow 12.3.0,
Qt 6.11.2, vips 8.18.6, gdk-pixbuf 2.44.7, dwebp 1.6.0, netpbm 10.86.50,
libraw 0.22.2, libultrahdr v2.0.2 (`latest/versions.tsv`).

## Orientation

### JPEG EXIF (o1–o8)

Applied by 20 readers: chromium×2, firefox×4, gm-best, im-autorot,
im-best, opencv, pillow(+best), qt(+best), vips(+best), webkit×2,
ffmpeg, **zen**. Stored pixels only: djpeg, gdkpixbuf, graphicsmagick,
imagemagick, opencv-unchanged, vips-raw, zen-raw (`-best` adds
`-auto-orient`/`icc_transform`).

`jpeg-exif6-xmp-o1`/`jpeg-exif6-xmp-o3` (conflicting XMP
`tiff:Orientation`): every orienting reader renders the **EXIF** value.

### AVIF irot/imir

LTS: applied by chromium, firefox (all modes), gdkpixbuf, IM×3, GM×2,
vips×3, zen. **avifdec 1.0.4, ffmpeg 6.1.1, webkit apply neither**
(`orient1`). In latest, avifdec 1.4.2, ffmpeg 9.0.1 and pillow 12.3
apply both.

`imir` axis semantics (ISO/IEC 23008-12 §6.5.12): axis 0 = top/bottom
(EXIF 4), axis 1 = left/right (EXIF 2) — every applying reader agrees
**except zen's AVIF path, which swaps them** (`avif-imir0` → orient2,
`imir1` → orient4).

`avif-irot3-exif6` (irot=3 + Exif item o6 — double-rotation trap):
readers honouring irot land `single-rot`; **`graphicsmagick-best`
double-applies** (`both` — irot and Exif composed); avifdec/ffmpeg land
`none`.

### HEIC irot/imir/EXIF

**Every libheif-family reader (heif-dec, vips×3, gdkpixbuf, GM×2, IM×3)
and zen honours the HEIC `irot`/`imir` boxes** — `heic-irot1/2/3`,
`heic-imir0/1` and `heic-irot3-exif1` land `correct` at MAD 0–1.
**zen-raw is the exception: it emits the untransformed raster**
(`stored`, correct=false) on all of them — it applies neither `irot`/
`imir` nor the Exif item. `heic-irot0` is `not-measurable` everywhere
(no-op transform; correct≡stored). Grading caveat: `stored` renders
through heif-convert (libde265) and `heif-dec` *is* that binary — its
cells agree with the base by construction; zen-raw lands `stored` at
1.00, within one level, so the verdicts don't rest on it alone.

The HEIC Exif item is informational — irot is the authoritative display
directive: `heic-exif-orient6` (irot absent, Exif o6) expects `stored`
and every reader lands `correct` **except `graphicsmagick-best`, which
applies the Exif item** → `exif-applied` (correct=false). When irot and
Exif agree (`heic-irot3-exif6`: both rot90cw) every reader lands
`single-rot` — **except `graphicsmagick-best`, composing irot with
Exif** → rot180, `double-applied` (correct=false). On `heic-irot3-exif1`
(Exif-1 identity) that double-apply is invisible and it lands `correct`
with everyone else; zen-raw lands `stored` throughout.

`heic-tile-base` (corpus iPhone tile grid remux): under the canonical
donor the fixture carries a **malformed `colr prof` — a 0-byte payload**
(byte-parse-verified). Readers that decode the raster (heif-dec,
gdkpixbuf, GM×2, IM×3, zen, zen-raw) all land `not-measurable` — with
no usable ICC the unmanaged readings collapse (correct≡stored at 0.00).
**vips hard-fails `bad seek` in both versions** — 8.15.1 to 11975;
8.18.6 to 11999/11976/11970/11968 — a robustness finding on corpus
bytes (r9's "clean decode" measured a different donor copy — round-10).

### PNG / WebP / JXL orientation

- `png-exif-orient6` (eXIf chunk): applied by chromium, firefox (all
  modes), gm-best, opencv, pillow(+best), vips(+best), zen (13). Ignored
  by webkit(+canvas), gdkpixbuf, graphicsmagick, IM6(+autorot/-best),
  qt(+best), ffmpeg-6.1.1, pngtopam, opencv-unchanged, vips-raw, zen-raw (14).
- `webp-exif-orient6`: applied by gm-best, pillow(+best), vips(+best),
  zen (6); ignored by all browsers, dwebp, ffmpeg-6.1.1, IM6, GM, opencv,
  vips-raw, zen-raw.
- `jxl-orient1..8` (codestream orientation): applied by djxl(+best),
  ffmpeg, vips×3, GM-best, zen in LTS; plain GM passes raw.
- `jxl-exif-orient6` (Exif box, codestream=1): ignored by every
  JXL-capable reader in LTS incl. zen — codestream wins.
- ffmpeg 6.1.1 crashes on the two JXL fixtures carrying extra boxes
  (`jxl-exif-orient6`, `jxl-jhgm`) — `crash` verdicts, counted failures.

## Colour

Browser engines and "best-mode" library paths colour-manage to sRGB —
usually bit-exactly (distances below are patch-centre MAD on the pattern
fixtures; corpus fixtures use whole-image p99 — see the HEIC section).

| fixture | chromium | webkit | firefox default | firefox cm=2 | zen |
|---|---|---|---|---|---|
| png-iccp-p3 | p3-as-p3 0.00 | p3-as-p3 0.00 | raw 1.00 | p3-as-p3 1.00 | p3-as-p3 0.00 |
| jpeg-icc-p3 (+v2) | p3-as-p3 0.00 | p3-as-p3 0.00 | raw 1.00 | p3-as-p3 0.00 | p3-as-p3 0.00 |
| webp-icc-p3 | p3-as-p3 0.00 | **raw** 1.00 | raw 1.00 | p3-as-p3 1.00 | p3-as-p3 0.00 |
| avif-icc-p3 | p3-as-p3 1.00 | **raw** 1.00 | raw 1.00 | p3-as-p3 1.00 | p3-as-p3 0.00 |
| avif-cicp-p3 | p3-as-p3 1.00 | **raw** 1.00 | raw 1.00 | p3-as-p3 1.00 | p3-as-p3 1.00 |
| png-cicp-p3 | p3-as-p3 0.00 | **raw** 1.00 | raw 1.00 | p3-as-p3 1.00 | p3-as-p3 1.00 |
| png-gama-chrm-p3 | gama-chrm-p3 0.00 | **raw** 1.00 | raw 1.00 | gama-chrm-p3 0.00 | raw 1.00 |
| jxl-enum-p3 | n/a | p3-as-p3 0.00 | n/a | n/a | p3-as-p3 1.00 |
| heic-colr-p3 | n/a | n/a | n/a | n/a | **correct** (p99 1.00 vs `correct`, 36.00 vs `stored`) |

(AVIF/JXL residuals ~1–2 levels = encode noise — every fixture is 4:4:4,
no chroma subsampling.)

- **Chromium 153**: manages every signalled format — PNG iCCP+cICP, JPEG
  ICC v2/v4, WebP iCCP, AVIF ICC + nclx, PNG gAMA+cHRM (`gama-chrm-p3`
  **0.00** on the gAMA-P3 row, both capture paths — the declared power
  curve + primaries are honoured exactly; runner-up `p3-as-displayp3` at
  3.00, the γ2.2-vs-sRGB-TRC gap the hypothesis separates on).
- **WebKit 26.6**: manages PNG/JPEG ICC exactly and **decodes JXL in this
  image — 16/16 cells `ok` in both LTS and latest sweeps** (`jxl-icc-p3`
  → `p3-as-p3`, `jxl-enum-srgb` → `srgb-as-srgb`, all eight orientation
  cells correct; canvas path identical). It passes WebP iCCP, all AVIF
  colour, PNG cICP and PNG gAMA+cHRM raw — per-format gaps, not
  engine-wide. OpenCV is the contrast: 5.0.0 decodes JXL 16/16; LTS 4.6
  errors all 16.
- **Firefox 155**: Playwright default profile is CM-off (raw on
  everything, both capture paths — `gfx.color_management.mode=0` read
  back from prefs). `mode=2` manages everything measured incl. PNG cICP.
- **zen**: manages ICC, nclx, cICP, JXL enum primaries correctly; treats
  EXIF-only declarations and APP14 as untagged (raw) — see conflicts.
- **-best adapters** (vips `icc_transform`, pillow ImageCms, qt
  convertToColorSpace, IM/GM `-profile srgb.icc`): `p3-as-p3`/`srgb-as-srgb`
  ≤2 MAD on ICC-carrying formats (worst: gm-best `jpeg-icc-adobe` 2.00).
  djxl 0.7 ignores `--color_space` silently; djxl-best 0.12 manages
  enum/ICC in latest. `-best` paths are ICC-only: cICP rows pass raw, as
  do all non-best LTS decoders on every mechanism.
- **EXIF-only colour declarations never trigger a conversion anywhere**:
  cs0/cs1/uncal/InteropIndex r98+r03 all pass raw everywhere (zen
  included). APP14 Adobe on JPEG ignored everywhere.

#### Raw pixels vs the tag, per reader (r14)

Every colour statement below names both readings: what the emitted
pixels are (`verdict`) and what they become once the output PNG's own
colour declaration is honoured (`verdict_tagged`).

- **Honest passthroughs** (raw unmanaged + honest tag ⇒ tagged
  `correct`/`p3-as-p3`): heif-dec, avifdec, djxl, imagemagick,
  imagemagick-autorot, graphicsmagick, vips, vips-raw, ffmpeg, pillow,
  qt. E.g. on `jxl-enum-p3`: djxl raw `p3-as-srgb` / tagged `p3-as-p3`
  — the enum primaries are copied to the output tag without touching
  pixels. These readers render no conversion but their tag tells the
  truth.
- **Genuine mis-tag** (converted pixels + a tag naming the *source*
  space): djxl-best 0.12 `mis-tagged:p3-as-p3` on every signalled JXL —
  it converts to sRGB then writes the Display-P3 profile. sips-srgb on
  `png-gama-chrm-p3` is the same shape with a different mechanism — it
  renders the gAMA+cHRM conversion correctly (`gama-chrm-p3` 0.00) but
  copies the source gAMA+cHRM chunks onto the converted file, so the
  tagged column reads `mis-tagged:gama-chrm-p3`. gAMA+cHRM is the only
  mechanism sips propagates verbatim.
- **gAMA+cHRM honoured** (raw `gama-chrm-p3` 0.00, both capture paths
  where they exist): chromium ×2, firefox-cm2 ×2, qt-best, and on the
  host ImageIO default/best, NSImage, Chrome and Edge on Windows —
  i.e. Apple decoders and every Chromium/Gecko engine with CM on.
  **Tag-only carriers** (raw `p3-as-srgb`, tag interprets to
  `gama-chrm-p3`): ffmpeg, graphicsmagick ×2, qt. **ImageMagick ×3**
  copies cHRM but *not* gAMA (`out_profile=chrm-only:p3`): primaries
  alone without the declared power curve read `p3-as-srgb` tagged —
  the label exists so a primaries-only tag is never confused with the
  full declaration. WebKit, zen and zen-raw treat the chunks as
  untagged (`p3-as-srgb` raw — zen's PNG pipeline ignores gAMA+cHRM).
- **Rendered/coordinator paths** (host columns): Quick Look emits a
  thumbnail whose pixels match no hypothesis (`other`-class
  `not-measurable` ~108 out — a rendered pipeline, not a decode), but
  its output tag is honest — tagged `p3-as-p3` 1.00/35 on
  `png-iccp-p3`, `gama-chrm-p3` 1.00/4.00 on `png-gama-chrm-p3`. sips
  (decode path) mirrors imageio-raw: raw `p3-as-srgb` 1.00/34 with the
  source profile written back — tagged `p3-as-p3`/`gama-chrm-p3`
  ~1.00. WIC converts to sRGB when it manages (`p3-as-p3` on ICC rows)
  but ignores gAMA+cHRM (`p3-as-srgb` both readings).

### Precedence on conflicting declarations (PNG-3e §4.3: cICP > iCCP > sRGB)

| fixture | spec answer | verdicts |
|---|---|---|
| `png-conflict-iccp-p3-cicp-srgb` | cICP→sRGB | `srgb-as-srgb` (cICP-correct): chromium×2, ff-cm2×2, zen + raw paths; `srgb-as-p3` (iCCP-wins): webkit×2, gm/im/pillow/qt/vips-best |
| `png-conflict-iccp-srgb-cicp-p3` | cICP→P3 | `p3-as-p3` (cICP-correct): chromium×2, ff-cm2×2, zen; `p3-as-srgb` (iCCP or raw): webkit×2, all `-best`, raw set |
| `png-srgb-chunk-plus-iccp-p3` | iCCP→P3 | every CM reader takes iCCP → `p3-as-p3` |
| `avif-conflict-icc-p3-cicp-srgb` | ICC | CM readers take ICC → `p3-as-p3` (chromium, ff-cm2, gm/im/vips-best, zen) |
| `heic-colr-conflict` (nclx sRGB + prof P3) | spec-silent; `icc-wins` marked correct | `icc-wins`: gm-best, im-best, vips-best, **zen**; `nclx-wins`: heif-dec, vips, vips-raw, gdkpixbuf, gm, im, im-autorot, zen-raw |
| `heic-colr-conflict-range` (nclx sRGB **limited** + prof P3) | spec-silent; `icc-wins` correct | `icc-wins` (correct): gm-best, im-best, vips-best (+gdkpixbuf latest); `nclx-wins`: heif-dec, vips, vips-raw, gdkpixbuf-lts, gm, im, im-autorot; `stored`: zen-raw; **zen `icc-range-ignored`, correct=false** — zen applies the ICC but drops the nclx **range** flag (full-res MAD 0.09 vs that hyp, 9.72 vs `icc-wins`, 9.78 vs `nclx-wins`) |
| `jpeg-conflict-icc-p3-exif-cs1` | ICC | CM readers take ICC → `p3-as-p3` |

On conflict rows the injected nclx is decode-neutral where full-range
(`heic-nocolr` ≡ `heic-colr-srgb`, MAD 0.000), so `nclx-wins` ≡ no
conversion; the **limited** variant makes nclx carry a real transform
(MAD 9.62; range compression 9.62→3.18). libheif-family `nclx-wins`
there means "honoured nclx including the range flag" — rendered through
libheif itself (`corpus:libheif-nclx` hyp).

### AVIF matrix / subsampling / bit depth / range (r13)

Five fixtures exercise the AV1 sequence-header colour description and
the container `nclx` box as two independent signal levels (both
byte-verified by `verify`; coded-stream properties asserted through
`av1C` profile/subsampling/bit-depth tokens):

| fixture | bit | chroma | nclx cp/tc/mc + range | seq-header cdp + range | content |
|---|---|---|---|---|---|
| `avif-cicp-srgb-mc1` | 8 | 4:4:4 | 1/13/1 full | 1/13/1 full | BT.601-coded |
| `avif-420-srgb-mc6` | 8 | 4:2:0 | 1/13/6 full | 1/13/6 full | BT.601-coded |
| `avif-420-srgb-mc1` | 8 | 4:2:0 | 1/13/1 full | 1/13/1 full | BT.601-coded |
| `avif-10bit-cicp-srgb` | 10 | 4:4:4 | 1/13/6 full | 1/13/6 full | BT.601-coded |
| `avif-cicp-srgb-limited` | 8 | 4:4:4 | 1/13/6 **limited** | 1/13/6 limited | BT.601-coded |

Because zenavif's pinned encoder (`11033c9`, via zencodecs) always
converts YCbCr with BT.601, `av1_seq_mc_patch` rewrites the
bit-packed `matrix_coefficients` field of the reduced still-image
sequence header so the coded stream and `nclx` agree (the mc1 fixtures
signal BT.709 in both while the content stays BT.601 — a consistent
declaration of the wrong matrix).

Two named hypotheses separate matrix readings from generic colour ones:
`mc-709-decode`/`mc-601-decode` dump the coded YUV planes with
ffprobe+ffmpeg and convert to sRGB with the named matrix in Python —
explicit reference math, never the tested reader's colour path. On
sRGB/untagged fixtures the *signalled* matrix's hypothesis is marked
correct; on P3/Adobe fixtures both readings stay named but neither is
marked correct (primaries unresolved). On the mc1 pair
`mc-709-decode` is the spec-correct reading (it renders what the file
declares — visible hue shift, ~40 p99 from `mc-601-decode`) while
`mc-601-decode` is the content-true but unsignalled one; both stay in
`matrix.tsv` so a reader's matrix choice is named either way. On
orientation fixtures `orientN-mc-709` hypotheses keep the colour-matrix
reading from swallowing orientation evidence — `orientation_ok` is
graded on the orientation axis alone (see `avif-irot1`/`avif-imir1`).

**WIC (Windows 11, AV1 Video Extension 2.0.35 + HEIF Image Extension
1.2.48)** performs *primaries- and bit-depth-dependent* matrix
selection: on the 8-bit sRGB-declared fixtures (`avif-cicp-srgb`,
`avif-untagged`, `avif-icc-srgb`) its raw output sits within ~2 levels
(p99 1, mean 0.10) of the BT.601-coded content converted with BT.709 —
i.e. it selects BT.709 regardless of `nclx` or the sequence-header
matrix — while on `avif-cicp-p3` and `avif-10bit` its output is correct.
Neither signal level changes the 8-bit sRGB behaviour. The mc fixtures
settle whether the selection is matrix-agnostic: **mc1 can't separate
always-709 from signal-honest** (the signalled matrix IS 709 — WIC's
`avif-420-srgb-mc1`/`avif-cicp-srgb-mc1` cells land `not-measurable`/
true on the correct clique either way), **mc6 can**: on
`avif-420-srgb-mc6` (601 signalled) every WIC column lands
`mc-709-decode` 1.03 with the correct render 39.00 out —
`correct=false`, the only failing host cells on the fixture (ImageIO
×3 and sips read the signalled matrix, `not-measurable`/true inside the
correct clique). WIC's AVIF matrix selection is fixed BT.709. No advice
is given to write `nclx` for WIC.

Measured (r14): on all five fixtures every matrix adapter that decodes
at all lands within the correct collapse pair — 105 ok cells on the LTS
image, 110 on latest, all `not-measurable` + `correct=true` under both
raw and tagged scoring (the signalled-matrix hypothesis and
`srgb-as-srgb` are pixel-equal on these files, so the pair certifies
together; a signal-ignoring reader would instead land on
`mc-601-decode`, `correct=false`, ~40 p99 out). None did — every AVIF
reader in the matrix honours the signalled matrix and, on
`avif-cicp-srgb-limited`, the signalled range. The one measured
exception is in the host columns: WIC decodes with a fixed BT.709
matrix and its `avif-420-srgb-mc6` cell lands `mc-709-decode`/
correct=false (above). The repack side also removed ffmpeg's last Exif
blind spot: ffmpeg reads `avif-exif-r03`/`orient6` in **both** images
(verdicts `adobe-as-srgb`/`orient1`) — LTS 6.1.1 opens the repacked
Exif AVIFs too; it is latest 9.0.1 that additionally decodes HEIC
natively.

Gain-map AVIF rows distinguish *multi-image output handling* from decode
capability (checked 2026-10-07, both images): ImageMagick 6 and 7 decode
the primary **and** the gain-map item fine — plain `convert in out.png`
emits `out-0.png`/`out-1.png`, so the adapter's expected `out.png`
simply never appears (multi-scene naming, not a decoder failure).
GraphicsMagick 1.3.42 refuses the file at library level ("Number of
images is not supported") while decoding the untagged AVIF — a
multi-image limitation, again not a gain-map decode failure. Qt fails
the gain-map *and* the untagged AVIF alike (no AVIF delegate in the
image) — not a gain-map-specific failure either.

Re-measure after the next dependency bump (pins unchanged this round —
the `zen` column and zenavif-written fixtures reflect them): zenavif
`5e493d39` (Exif item as one iloc extent — zenavif#52; the generator
repacks multi-extent items so ffmpeg's reference path can read the Exif
fixtures, which makes the repack a no-op after the bump), zenavif
`505793b` (imir axis semantics — zenavif#54; `avif-imir0/1` verdicts
below reflect the pinned behaviour and should flip), zenavif `c6c037c0`
(wide-gamut sources keep an ICC next to nclx), heic `f9052720` (reads
both colr boxes — heic#53 open until the colr-conflict fixture is
measured against libheif), zenpipe `eeb3f606`/`8b78d1b4` (re-encodes
bake orientation, EXIF/XMP rewritten to 1), zenjpeg `1242539b`/`169e5487`
(the primary's hdrgm/GContainer XMP now writes only under
`GainMapEncodingFormat::Xmp | Both` — ultrahdr/encode.rs:620-645 on
main; the generator's XMP strip for `jpeg-ultrahdr-iso` becomes a no-op
after the bump and stays until then, re-verified with exiftool).

### HEIC `colr` rows (corpus-donor remuxes)

Container facts (demux-verified): the iPhone HEIC has **no nclx colr** —
only `prof` ICCs on tile items plus the malformed zero-length `prof`
described under tile-base; the unspecified HEVC decodes as BT.601
full-range (libheif bit-identical; zen within 1 level on 2.7% px, MAD
0.009). The injected nclx is `*/13/6/full` except `-range` (`1/13/6`
**limited**); `heic-remux-base` carries the donor's Exif/`mime` items
plus a generator-injected XMP `mime` item (`application/rdf+xml`,
verified).

Distances on these rows are whole-image **p99/max** (corpus metric):

- `heic-colr-p3` (nclx P3): **zen is the only `correct`** — it applies
  the declared P3 primaries (p99 1.00 vs correct, 36.00 vs stored).
  Every libheif-family reader lands `stored` (correct=false): p3-vs-srgb
  separates at p99 36 / max 105, clear of the libde265 bound (≤1) though
  not of the cross-decoder bound (ImageIO/WIC 21–46) — only
  libde265-family cells are decidable here (M-5). The non-libde265 HEIC
  paths in the matrix are zen and latest ffmpeg 9.0.1 (native `hevc`
  decoder, no libde265/libheif linkage) — ffmpeg lands d1 = 2.00 on the
  irot/imir fixtures (`correct` through its own HEIF demux+decode; LTS
  ffmpeg has neither and errors on every HEIC cell).
- `heic-colr-srgb` / `heic-nocolr`: `not-measurable` for every reader —
  declared sRGB ≡ unmanaged decode (correct≡stored at 0.00); sRGB
  handling unattributable.
- `heic-icc-p3` (grid `prof` P3, no nclx): the family splits on the two
  readings. **Raw pixels**: `stored` for heif-dec, vips, vips-raw, IM,
  IM-autorot, GM and latest ffmpeg (2.00) — libheif reads the YUV raster
  and passes the `prof` through as a tag without converting. `correct`
  pixels only for the `-best` paths (gm-best, im-best, vips-best — an
  explicit lcms step), zen, and latest gdkpixbuf. **Tagged**: the
  passthrough family reads `correct` — the copied `prof` honestly names
  the pixels. `stored` both readings: LTS gdkpixbuf, zen-raw.
- `heic-remux-base` (donor's real `appl` tile ICCs): the same split —
  `correct` pixels only for gm-best, im-best, vips-best and latest
  gdkpixbuf; the rest of the libheif family reads `stored` raw /
  `correct` tagged; **zen and zen-raw land `stored` both ways** — zen
  honours grid-level colr and a single-item `prof` but not per-tile
  `prof`s in the 48-tile grid; ffmpeg `stored`.
- `heic-colr-conflict[-range]`: precedence table above.

## HDR / gain maps

`probe --hdr` renders zen's reconstruction (full boost, linear light,
stored orientation) as reference; `mean |Δlog2|` vs reader HDR output.
`gainmap-applied` is generated from the authoring HDR buffer via
`ultrahdr_core` (4× boost, clip 1.0, sRGB OETF) — separates from
`sdr-base` at p99 118 / max 124 on the JPEG rows. Table: `<run>/hdr.tsv`.

| fixture | zen | ultrahdr_app | other detection |
|---|---|---|---|
| jpeg-ultrahdr-xmp (MPF+hdrgm XMP) | reconstructs | HDR out, Δlog2 0.033 | — |
| jpeg-ultrahdr-iso (ISO 21496-1 APP2 only — `noxmp` verified) | detects but **flat** — zencodecs reads XMP `hdrgm` only | HDR out, Δlog2 **1.377** — zen's flat reference diverges | — |
| jpeg-ultrahdr (hdrgm XMP + ISO APP2 + GContainer `mime`) | reconstructs | HDR out, 0.033 | — |
| jpeg-ultrahdr-mpf-corrupt | probe-hdr fails (base decode fine) | **HDR out on both v1.4.0 and v2.0.2** — both emit linear-f16 | — |
| avif-tmap (branded) | reconstructs | n/a | avifdec 1.4.2 shows the tmap; `avifgainmaputil` detects; `tonemap --headroom 2` agrees with zen (Δlog2 0.031); 1.0.4 silent |
| avif-tmap-archived-serializer | reconstructs | n/a | 1.0.4 silent; 1.4.2 prints `absent`; gainmaputil `not recognized` — needs the `tmap` brand + `grpl`/`altr` group |
| jxl-jhgm | reconstructs | n/a | jxlinfo sees the `jhgm` box; djxl decodes base only |

Authoring caveat: `zenjpeg::ultrahdr` writes hdrgm XMP even for
`GainMapEncodingFormat::Iso21496`; `jpeg-ultrahdr-iso` is made ISO-only by
byte-removing the XMP APP1. No other reader produces an HDR rendition —
the UltraHDR rows land `not-measurable` (intended `sdr-base≡stored`
collapse).

AVIF Exif caveat (measured): zenavif `11033c9` writes Exif as a
two-extent `iloc` item — legal BMFF, and exiftool reads it, but exiv2
reports "corrupted image metadata" and **ffmpeg rejects it** (6.1.1:
`iloc: extent_count > 1 not supported`; 9.0.1: `Not yet implemented`).
Because ffmpeg is the AVIF hypothesis reference path, the generator
repacks multi-extent items to a single extent at fixture build, so the
shipped `avif-exif-*` files are ffmpeg-readable — the two-extent
shape is a zenavif-encoder artifact, preserved only in pre-repack form.
zenavif `5e493d39` (zenavif#52) emits single-extent Exif natively;
re-measure after the pin bumps, when the repack step should become a
no-op.

Corpus reps: on iPhone 16/17 `tmap` HEICs zen reports `gainmap: none`
(its HEIC path doesn't surface them — zenpipe#81); heif-info detects
them where `auxC` strings survived. The macOS reps column
(`2026-10-07-reps-macos/hdr`) shows ImageIO and Core Image applying the
Apple MakerNote and ISO `tmap` maps on the restored twins — per-file
JSONs under `2026-10-07-reps-macos/hdr/{imageio,cihdr}`: ImageIO
`hdr_max_linear` peaks 3.382 / 5.947 / 3.418 / 2.803 on the four HEIC
twins (`HDRGainMap`/`ISOGainMap` aux), per-pixel mean |Δlog2| vs the
paired Core Image output 0.011–0.026 stops (peak ratios up to 0.167).
The paired corpus copies read: 1497/1516 carry no `aux` markers with
`hdr_max_linear` 60.2/59.4 under ImageIO vs 108/75 under Core Image;
1520 `HDRGainMap`+`Disparity` at 5.947; 1509 `HDRGainMap` 1.044; the
`Disparity`-only ≈1.00 rep is 1498, which has no restored twin.

### Metadata readers (`metadata/metadata.tsv`)

exiftool + exiv2 over all 120 fixtures; heif-info on the 41 HEIF-family
files; jxlinfo, webpinfo, avifdec on their formats; a byte-marker scan
folded into the exiftool row (`note=markers-byte-scan`). What they
*report* (not what decoders do with it): exiftool surfaces EXIF
`tiff:Orientation`, AVIF `irot` (as `[QuickTime] Rotation` — not `imir`;
both `*-imir1` rows are faithfully empty) and the Exif item on HEICs,
both colr conflict arms, and the UltraHDR MPF marker — the ISO-21496
APP2 signature is found by the byte scan, not exiftool. exiv2 reports
InteroperabilityIndex `R98`/`R03` and ICC presence via `-pC`. The
warnings column drops filename/path-valued keys (`SourceFile`,
`FileName`, `Directory`, `MIMEType`) before filtering benign lines. No
reader *acts* on the cs0/cs1/r98/r03 declarations — the metadata layer
sees what the decode layer ignores.

## Alpha / depth / other

Alpha is scored (4-channel patches; canvas mode for browsers).

- `alpha-honored`: png-alpha, png16-alpha, webp-alpha-lossy, avif-alpha,
  jxl-alpha — nearly universal.
- `alpha-dropped` (RGB correct, alpha flattened): opencv IMREAD_COLOR
  (unchanged preserves); ffmpeg on avif-alpha.
- `png-apng` → `frame0` for every decoding reader except webkit (`other`
  ~239 — compositing artefact); gdkpixbuf: no APNG decode.
- `png-palette-trns`: `decoded` by every library reader incl. canvas
  modes; the four screenshot cells and opencv's alpha-dropping decode land
  `other` at 159 MAD (trns composited opaque); firefox canvas `other` at
  3.00.
- `png16-*`: quantized to 8-bit on output; `png16-p3` ICC managed by the
  same set as 8-bit iCCP.
- `jpeg-rgb-app14`/`jpeg-app14-adobe`: APP14 `0`/`1` honestly written;
  treated as untagged by all readers.
- ffmpeg `webp-alpha-lossy`: `other` at 2.01 — near-miss.

## Corpus representatives (45 real files × 35 adapters → 1,575 cells/run)

`corpus_reps.tsv` picks 45 real files covering corners synthesis can't
fake (Apple `appl` ICCs, colr-tile fallbacks, tmap/auxl gain maps,
EXIF-CS declarations, iPhone 16/17), sha256+size asserted at build.
LTS verdict shape: **608 n/a** (declared coverage), **193 error + 3
flaky**; of the 771 ok cells **435 not-measurable** (mostly untagged
sRGB where managed ≡ raw), **176 stored**, **95 orient-only**, **57
correct**, **8 other**.

- **`correct` on real files**: jpeg P3 reps correct for the CM-reader set;
  the ultrahdr-restored rep → `correct` for the CM set incl. zen. On the
  rotated DisplayP3 HEIC reps **zen, im-best, vips-best and (latest)
  gdkpixbuf land `correct`** — colour *and* rotation applied (zen is
  `orient-only` on the tile-icc/`tmap` rotated reps); the rest of the
  libheif family lands `orient-only`; raw paths `stored`.
- **iPhone 16/17 Pro HEICs**: on LTS the only `ok` cells are zen/zen-raw —
  heif-dec 1.17.6 `Non-existing item ID referenced`. On latest **the
  whole libheif-1.23.2 family decodes them** — a version fix, not a
  format limitation.
- The `colr-grid-icc` iPhone-16/17 grids carry a ~26.7 KB Apple v4 ICC
  with a PQ `cicp` tag (12/16/0/1) and an ISO `tmap` gain map. Latest
  splits them: vips-best is `correct` on both orient6 twins (the
  hypothesis set does cover a tmap-composited render); the other
  `-best` libheif paths land `other` — they apply the tmap, ending
  beyond T of every unmanaged hypothesis; qt-best/pillow-best/
  opencv-unchanged `error`; unmanaged readers land `stored` (19),
  `orient-only` (16) or `not-measurable` (2).
- reps-latest shape: **608 n/a / 100 error + 2 flaky**, ok cells 454
  not-measurable / 196 stored / 106 orient-only / 71 correct / 35 other /
  3 colour-only (calibration 5/3/4).
- **DNG reps: the `-t 0` LibRaw base makes `stored` the sensor raster** —
  `correct`/`orient-only` apply the signalled rotation on top (identical
  pixels on these `noicc` files → one clique). dcraw_emu — LibRaw's own
  path, which *does* apply the flip — lands `not-measurable` inside the
  correct clique on all three; vips(+best), IM-autorot/-best join.
  Orientation-ignoring readers name themselves: plain imagemagick and
  latest vips-raw land `stored` (correct=false); zen's magenta-raw
  rendition stays `other` at 248–255 — an equidistant far-out tie
  between hypotheses, which the corrected rule (H-1) refuses to
  certify. Census flags the same 3 files `zen-vs-libraw`.
- **`graphicsmagick-best` double-rotates the rotated HEIC reps** — `other`
  on every orient6 rep it opens (6/6 LTS, 8/8 latest; iPhone-16/17 files
  error under LTS libheif 1.17) — the r9/r10 "double-rotation" reading
  stands (irot∘Exif, see HEIC section).
- webkit-canvas is **nondeterministic run to run** — all-zero readbacks
  land the distinct `flaky` verdict (3 reps / 2 reps-latest cells) rather
  than `error`; `flaky` is excluded from error counts and the
  LTS-vs-latest diff.

## Latest vs LTS (one generation newer)

Same 35 adapters against `imazen26-compat:latest`; verdict/status diff
between the two run matrices:

**185 cell diffs across 71 fixtures**. By status: **147 `error→ok`**
(pillow-best gains AVIF; opencv 5.0.0 + opencv-unchanged gain all 16
JXL fixtures each; IM gains JXL + eXIf, GM gains 2 AVIF cells; ffmpeg
9.0.1 and the libheif-1.23.2 family decode the HEIC set — including
the repacked Exif AVIFs, ffmpeg's last blind spot), **2 `crash→ok`**
(ffmpeg on `jxl-exif-orient6`/`jxl-jhgm`), **34 `ok→ok` verdict
moves** plus 2 tagged-only moves:

| move | n | who |
|---|---|---|
| `p3-as-srgb → p3-as-p3` | 10 | gdk-pixbuf 2.44.7 is colour-managed now — every ICC fixture flips; djxl-best 0.12 honours `--color_space` |
| `orient1 → orient6/8/3/4/2` | 17 | avifdec 1.4.2 + ffmpeg 9.0.1 apply AVIF `irot`/`imir` (10); ffmpeg, IM7-autorot/-best, opencv apply PNG/WebP eXIf (7) |
| `none → single-rot` | 2 | avifdec/ffmpeg apply irot on `avif-irot3-exif6` |
| `stored → correct` | 2 | gdk-pixbuf CM on `heic-icc-p3` and `heic-remux-base` |
| `nclx-wins → icc-wins` | 2 | gdk-pixbuf CM on both `heic-colr-conflict*` rows |
| `adobe-as-srgb → adobe-as-adobe` | 1 | gdk-pixbuf on `jpeg-icc-adobe` |
| (untagged scoring note) | — | r12's `p3-as-p3 → other` djxl-best rows now resolve as `p3-as-p3` raw / `mis-tagged:p3-as-p3` tagged — djxl-best 0.12 converts to sRGB but writes the Display-P3 profile; the tag column names it |

- **gdk-pixbuf 2.44.7 is colour-managed** (2.42 was raw-everything) —
  the largest mover: 22 `error→ok` + 13 flips to the applied reading.
- **libheif 1.23.2 decodes the iPhone-16/17 reps** (heif-dec, vips×3,
  gdkpixbuf, GM/IM `ok` where 1.17.6 raised `Non-existing item ID
  referenced`).
- ffmpeg 9.0.1 decodes all 16 JXL fixtures + PNG/WebP eXIf; IM 7.1.2
  gains JXL + eXIf; djxl-best 0.12 honours `--color_space`.

## Corpus census (2,160 corpus images × reader roles)

`census/census.tsv` is rebuilt deterministically from per-file JSON
checkpoints; every cell carries producer identity (`image_id`,
`adapter_sha`, `fixture_sha`). The measured copy is
`~/work/codec-corpus/imazen-26` (census run 2026-10-07; reader modes:
plain `vips`/`pillow`/ImageMagick 6 from the LTS image — not `-best`) —
**319 camera-class files differ in byte size from `CORPUS-MANIFEST.tsv`**
(the June manifest predates the July metadata rewrite); census claims
about camera files describe this copy. `census/signalled/` is the
header-level pass (`probe --meta`) over all 2,191 corpus files — its
cells record the probe binary that ran them (`0884c905…`). The
zen-reader census JSONs were stamped **after the census ran**: their
`thumb_sha` fields hash the retained ≤1024 px thumbnails, not the
full-resolution renders.

Cells: zen-reader 2,160 · vips/pillow/imagemagick 2,160 each · browser
2,067 · pngtopam 1,650 · djpeg 417 · heif-dec 90 · dcraw_emu 3 — 12,867
cells across nine reader roles. Statuses: **12,708 ok / 159 error** —
pillow fails all 90 HEICs (declared, unsupported in practice);
heif-dec 1.17.6 fails 21 (iPhone-16/17-era); vips/IM fail 18 HEICs
each; the 3 DNGs fail in vips and pillow; 6 browser jpg/png fails.

Signalled orientation (`orientation_reported` at header level), counted
over **images only**: 1,953 `1`; **207 non-1** — 196 `6`, 9 `3`, 2 `8` —
the denominator the "3 rotated files" claim understated.

## Coverage gaps (documented, not silently dropped)

- No CMYK/arithmetic/12-bit JPEG variants — zen encoders can't author
  them; third-party authoring is out of scope.
- In-image browser decoders cover JPEG/PNG/WebP/AVIF only plus JXL on
  WebKit (16/16 cells `ok`); the host Chrome 155 on Windows also decodes
  JXL — 15/15 measurable cells `correct` (`jxl-alpha` is the
  screenshot-mode `n/a`). Edge on Windows does not (`img.onerror`). The
  census browser column is jpg/png only; other formats report `n/a`.
- Screenshot-mode alpha rows are n/a (`alpha_measurable=false`) —
  screenshots composite transparency.
- Firefox shipped-CM is emulated via `gfx.color_management.mode=2` —
  real desktop profiles are outside this harness.
- JXL fixtures' ICCs live inside the compressed codestream — the
  byte-level ICC identity gate doesn't cover them.

## Withdrawn claims (cumulative)

- Rounds 1–7 (carried): broken reference hypothesis coloured all "no
  reader colour-manages" claims; "firefox performs no colour conversion"
  (default profile); PNG-3e chunk order; "opencv ignores EXIF"
  (mode-dependent); "zen vs libultrahdr diverge 2.289" (alignment
  artefact — real ≈0.03); "only 3 rotated corpus files" (signalled
  207); "heif-dec rejects 21 HEICs" (18 parse + 3 writer fails); "22
  icc-unhandled = appl profiles" (19 tmap-PQ + 3 Linear Gray); "avifdec
  1.4.2 doesn't recognize tmap" (measured the archived container);
  "ffmpeg applies AVIF irot" (6.1.1 doesn't; 9.0.1 does); "chromium
  prefers sRGB over iCCP"; "webkit/firefox iCCP beats cICP".
- Round-8: "vips `heic-tile-base` hard-fail was fixed" (`bad seek`
  reproduces); "ultrahdr_app v2.0.2 rejects the corrupt-MPF fixture"
  (emits linear-f16 like v1.4.0); "heic-icc-p3 is an unresolvable
  collapse pair" (separates cleanly); "heic-colr-conflict
  un-attributable" (icc-wins/nclx-wins split); "GM-best `-profile`
  fires wrongly on JXL"; "JXL Exif box ignored by every reader"
  (IM7-autorot/-best apply).
- Round-9: "GM-best produces a blue-shifted wrong HEIC rendition" —
  *reinstated as double-rotation* under the stripped bases (round-11);
  "zen ultrahdr writer needed" (`zenjpeg::ultrahdr` authors all);
  "Pillow 12.3 newly applies PNG/WebP EXIF" (10.2 did); "the ICC gate is
  an lcms2 identity check" (independent references); "zen DNG reps
  correct" (now LibRaw hypotheses); "cells not provenance-keyed" (all
  three keys gated); "ffmpeg 9.0.1's reject is `extent_count > 1`"
  (reports only `Not yet implemented`).
- Round-10: "vips decodes `heic-tile-base` cleanly — the r8 bad-seek was
  a fixture defect" (malformed `prof` in the *canonical* donor; r9 used
  a June-backup copy — donor now sha-pinned); "`heic-tile-base` carries
  the donor's real `appl` ICC" (wrong donor copy); "DNG reference
  hypotheses correct" (the cache key ignored the decode command; under
  `-t 0 -6` `stored` is the sensor raster);
  "every libheif reader applies HEIC `irot`" — *reinstated* (r11's
  withdrawal was the baked-base artifact — see round-11);
  "zen `not-measurable` on `heic-colr-conflict-range`" (collapse now
  decided at T=2 — zen names `icc-range-ignored` correct=false);
  "browser cells emit `fixture_sha` natively" (r9 post-stamped them);
  "the phase-1 gate runs before phase 2" (a `ultrahdr_app`
  override-leak fixed).
- Round-11 (corrected this round): "no reader honours HEIC `irot`/`imir`;
  zen-raw rotates it the wrong way" — `stored` bases carried
  `irot`/`imir`/`clap` applied, inverting every orientation verdict;
  stripped bases restore the r10 reading — and show what the earlier
  single-reading scores conflated: the libheif family's `prof`-ICC
  handling on `heic-icc-p3`/`heic-remux-base` is *tag propagation*, not
  pixel conversion (raw `stored`, tagged `correct`);
  "gm-best `correct` on the rotated reps, not double-rotation"
  (inverted); "webkit-canvas all-zero readbacks counted as `error`"
  (now `flaky`); "phase-1 gate refuses adapters that can't decode a
  format" (now a capability probe; refusal only on
  decode-but-not-correct); "docker/browser `image_id=host` cells pass
  `--check`" (now refused); "real 16-bit DNG base" (16-bit TIFF graded
  at 8-bit); "census `output_sha` stamps" (renamed `thumb_sha`).
