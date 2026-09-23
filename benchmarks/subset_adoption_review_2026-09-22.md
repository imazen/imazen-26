# Test subsets across the zen repos: what imazen-26 should adopt (2026-09-22)

Survey of the test subsets, hard-case sets, format-coverage sets and data-carrying
branches that repos under `~/work/zen` (and `~/work/codec-corpus`, `~/work/imageflow`)
have built, judged for adoption into this corpus. Five read-only surveys covered
corpus/data repos, JPEG/WebP/PNG/GIF/TIFF codecs, JXL/AVIF/HEIC/pipeline, metrics/ML,
and processing/product repos. Everything cited below was **re-checked by listing,
counting or reading the file**. Where a count is a survey figure I did not re-check,
it says so.

Companion records: `split_leak_audit_2026-09-22.md` (split leaks),
`color_orientation_audit_2026-09-22.md` (render-layer colour and orientation),
`variant-sets/squintly-candidates@2026-09-22/SET.md` (squintly stimuli).

## Register now — already built from imazen-26, just unregistered

| set | where | n | what it is | action |
|---|---|--:|---|---|
| rd-gap train26 | zenavif `scripts/rd_gap/sample_images_train26.tsv` | 24 (train by the last-digit rule; 3 are validate under the family map) | k-means K=24 representatives; the index behind most AVIF RD-gap investigations (renders at 1024 in `/mnt/v/output/rd-gap-train26-2026-07-02/`) | **registered** as `rdgap-train26@2026-07-02` |
| lossless bench set | jxl-encoder `benchmarks/lossless_bench_set_2026-06-10.tsv` | 43 (26 train / 13 validate / 4 test under the family map) | per-stratum k-means over 23 strata, ≤16 MP, sha256 per row | **registered** as `lossless-bench-43@2026-06-10` |
| imazen-26-synth / -synth-500 | `~/work/codec-corpus/imazen-26-synth{,-500}` | 10,736 / 502 files | derived renditions and a 500-image k-means subset; gitignored, local disk only | register, then mirror to R2 and tower — today a single disk holds them |
| train-legal hunt | jxl-encoder `benchmarks/corpora/imazen26_trainlegal_hunt_2026-08-20.tsv` | 21 (all train) | split-hygiene picks | reference only |

## New content worth adopting

| set | where | n | adds | verdict |
|---|---|--:|---|---|
| Wikimedia featured/quality images | `/mnt/v/output/wikimedia-corpus/2026-04-16/` | 778 manifest rows (804 files on disk) | illustration 300, screen content 250, photos 228; per-file license, artist, credit and Commons URL (CC0 345, PD 171, CC-BY 262) | **adopt** after reconciling the 26 files on disk with no manifest row and a hash check against imazen-26; the 262 CC-BY rows need their attribution carried |
| Real product photography | `/mnt/v/collections/sierra-2026-06-07/` (598, 21 categories) and `zen/commerce-corpus` (Kaggle) | 598 + ? | the corpus's product class is 100% AI-generated; e-commerce is a large share of web images | **blocked on license** — neither source's redistribution terms are established |
| Format probes | `codec-corpus/imageflow/test_inputs/orientation/` (16: 8 EXIF orientations × landscape/portrait); `zen/gainmap-spec-status/test-vectors/` (AVIF tmap, JPEG hdrgm, JXL jhgm, ISO 21496-1 metadata; per-file source/license/sha256 in `manifest.toml`); `zen/heic/testdata/` (128 files incl. `apple-hdr/hdr-sample.heic`) | ~150 | orientation, gain-map and HEIF-feature edge cases the photographic corpus cannot exercise | **adopt as a separate format-probe set** — never mixed into content categories |
| Wide-gamut ICC samples | `/mnt/v/output/corpus-builder/wide-gamut/` (210: Adobe RGB, Display-P3, ProPhoto, Rec.2020-PQ, gray-2.2); `/mnt/v/datasets/non-srgb-by-profile/` (498 files, 63 profiles) | 708 | ICC-driven colour paths | reference only — no provenance or license recorded for either |
| AI categories not in the corpus | `/mnt/v/zen/ai-corpus/{icons,infographics,marketing}` | 24 / 61 / 111 | same PD-own AI pool as 9000/9094/9226 | optional; squintly excludes AI content by design |
| Corruption generator | `codec-corpus/crate/corruption-corpus` | generator | seeded, reproducible corruptions in 10 families | adopt as a **tool**: obvious-difference goldens for squintly, and integrity-head gates |

Skip for imazen-26 (right where they are): the `*-conformance` suites and fuzz corpora
(decoder robustness, not content), CID22/CLIC/KADID/GB82 (valuable because they are
disjoint from us), `art-cc0` (duplicates 3000/3300), `gen-clothing` (unculled WIP),
Kodak and the WebP gallery (over-familiar), `zenjpeg-perm-corpus` (synthetic parity
patches).

## Hard cases the codec and metric repos already know

Candidates for a registered "known-hard" set — regression gates, and squintly
diagnostic stimuli:

| image / condition | repo | failure |
|---|---|---|
| near-lossless band (q≥85), all content | zensim `benchmarks/failure_profiles_2026-08-31.md` | 189 of 322 board cells have ≥1 backwards ladder at q≥85 (median inversion 2.83%, p90 8.56%); AVIF worst, WebP nearly clean |
| `hf_nearlossless` 48-reference corpus | same, §5.3 | shipped model ranks 20.8% of ladders backwards; scored by only 13 of 379 board cells |
| magnified vs native presentation | zensim `benchmarks/hfhuman_2026-09-01.md` | 14 of 36 subset × scorer verdicts flip with 2× boosted pixels |
| 2400 (textures) | jxl-encoder CLAUDE.md | RD and IQA non-monotonic at d≥12 (survey figure) |
| 6629 (Trouvelot flat gradient) | zenavif CLAUDE.md | worst AVIF RD gap vs libaom, +25% (survey figure) |
| 8414 (lkml screen content) | zenavif | intraBC screen-content class, +22.5% BD (survey figure) |
| 5058 (NPS brochure) | jxl-encoder | RD monotonicity violations d2.25→2.5, d3.0→3.25 (survey figure) |
| 8025 (Display-P3 Android PNG) | jxl-encoder | reference cjxl fails to decode it (survey figure) |
| EXIF-rotated 4:2:0 photos; non-MCU-aligned widths | zenjpeg issues #149, #21, #188 | auto-orient pixel errors; chroma boundary errors up to 39 levels (issue text; open/closed state not checked) |
| CID22 + `sharp_yuv` | zenwebp issue #17 | −17 to −26 zensim, the opposite of the intended effect (issue text; state not checked) |
| partial-alpha WebP resize | zenwebp issues #10, #12 | RGB destroyed under 0<α<255; banding (issue text; state not checked) |

## Problems found

Corpus (this repo): see the two audits — byte-identical duplicates across buckets,
photo bursts across buckets, ~165 Display-P3 photos labelled BT.709 in png-v3,
orientation differing between png-v3 and pristine-8th, 16 zero-value entries.
Also: the 25 EPA pages are RGBA with an unused alpha channel and no colour chunk,
which zenpipe's `pristine_downscale` refuses on write-verify (zenpng writes RGB8,
transfer unknown); 1449 (16320×7612, 124 MP) exceeds zenpng's default 120 MP decode
limit; 3005/3006 are Adobe RGB, which has no CICP code, so the pristine route refuses
them.

Derived data:
- `nonphoto-picker-corpus-2026-06-26` copies 349 imazen-26 images under new ids and
  re-buckets 217 of them (26 test → train). Its README's "no cross-split leakage"
  holds only inside that corpus.
- `codec-corpus/picker-train/` is untracked and not ignored.
- Two family definitions disagree: `manifests/split_map_family.tsv` and zensr's
  `tools/corpus_split.py` (which adds NOAA-advisory and site-level web grouping).

Test hygiene (other repos; not changed here):
- Silent skips (banned pattern): `zengif/tests/quantizer_quality.rs:339-360`,
  `zenextras/zentiff/tests/corpus_decode.rs:257-259`,
  `zenresize/tests/real_vs_synth.rs:167`.
- A second, stale clone of `imazen/codec-corpus` at `~/work/codec-eval/codec-corpus`
  (last commit 2026-04-14 vs 2026-08-30) is what zenjpeg's justfile defaults point at.
- Stale sibling workspaces with nothing unique (survey finding, not re-checked): the
  `zenjpeg--*`, `zenavif--*`, `zenjxl--*`, `zencodec--*` siblings, `zenpng--tracefix2`;
  `jxl-gpu` duplicates `jxl-encoder-gpu`. The four `zenmetrics--*` workspaces each
  carry the same 2026-05-16 `CONTEXT-HANDOFF.md` about an unrelated task (verified
  identical).
- `~/work/imageflow/.claude/worktrees/focus-rects-smart-crop` exists and, per the survey,
  holds uncommitted saliency/crop work parallel to zensally's smart crop (contents not
  re-checked). Decide which one owns smart cropping.

## Branches

No repo surveyed keeps unmerged test data on a branch worth rescuing, with two
exceptions in codec-corpus: `add-jxl-rs-issue-765-regression` (three JXL repro files
that belong in zenjxl-decoder's regression set) and `recovery-corpus-before-native`
(RAW-conformance LFS recovery, WIP). Branch counts in zenrav1e (~110) and rav1d-safe
(~100) were not audited one by one. This repo's `variant/*` LFS branches, with objects
on R2 behind the proxy, are the pattern the rest of the workspace lacks: checkoutable
render sets that cost nothing against GitHub's limits.

## Format coverage imazen-26 lacks

Animation (GIF/APNG/animated WebP/AVIF sequences), TIFF/CMYK/float samples, native
alpha outside the AI clipart, native tiny sources (everything small is a downscale),
Adobe RGB/ProPhoto/Rec.2020 SDR beyond the two AIC scans, and phone screenshots at
real device DPR (every `8100` mobile viewport was captured at DPR 1; `8000` is
unlicensed). Present and well covered: HDR gain maps (76: 43 HEIC + 33 JPEG
with gain maps), Display-P3 photos (191 lossy origins), EXIF-rotated images (196), 1-bit scans
(39), 16-bit PQ renders.
