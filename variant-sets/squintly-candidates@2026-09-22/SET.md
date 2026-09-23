# squintly-candidates@2026-09-22 — stimulus candidates for the paid squintly study

A **selection manifest, not renders**: which corpus images should become squintly
stimuli, grouped so that no near-duplicate sits on both sides of a train/confirm line.
It answers the question the live squintly corpus never asked — *is this picture worth
paying an observer to look at?* — and it replaces nothing until squintly adopts it.

- **Picks:** 148 `batch1-train` + 62 `reserve-test` = 210 source images, across 13
  content strata (`selection.tsv`, picks only).
- **Families:** 186 multi-member stimulus families, with the keys that joined each one
  (`families.tsv`).
- **Full per-id table** (all 2,160 ids, including `pool` and `excluded` rows with their
  reasons, urls and paths): `/mnt/v/output/imazen-26-variants/squintly-candidates@2026-09-22/candidates_all.tsv`,
  sha256 `6ed0fb3da65747490338fc07744abb05308c88ac031b2f0d9cd6f3ff59db89dc` — kept out of
  git for size; regenerate it with the command below.
- **Contact sheets of the picks:** `/mnt/v/output/imazen-26/squintly-candidates-2026-09-22/`
  (`http://localhost:3300/imazen-26/squintly-candidates-2026-09-22/` on the dev box).
- **Generator:** `scripts/build_squintly_candidates.py` + `scripts/squintly_screening.py`.
  Deterministic; no seed. Feature input:
  `/mnt/v/output/imazen-26-features/imazen26_features_2026-06-23.parquet`
  (sha256 `b113449d35e98bda0f3266fc7a25ee5ab24b92a3991cb7140e9262d4320735bc`).

```
python3 scripts/build_squintly_candidates.py \
    --features /mnt/v/output/imazen-26-features/imazen26_features_2026-06-23.parquet \
    --set-dir "variant-sets/squintly-candidates@2026-09-22"
```

- **Consumers:** none yet — proposed for squintly's next study registration.
- **Status:** proposed.

## Why this set exists

The most recently published squintly corpus (`squintly/demo-corpus/imazen26-v5-test-noai`
on R2; what is live is whatever `SQUINTLY_COEFFICIENT_HTTP` names on the deployment, not
checked here) serves **42 distinct images**, each at four sizes. Its builder takes the
largest files in each stratum and spreads picks across the top quarter by pixel count,
so content never enters the choice. One image stands for each of the nine photo, render
and art strata; 32 of the 42 are documents, plots and screenshots; four are pages of a
single patent; and every text page is also served as a ~185×240 thumbnail no one can
read. Paid time spent on those trials buys little.

## How it was selected

**1. Stimulus families.** Four keys are unioned before anything is picked:

| key | what it catches |
|---|---|
| canonical `family` (`manifests/split_map_family.tsv`) | patent scan variants, plot seed variants, web captures across viewports |
| same `sha256` | byte-identical files filed under two ids (11 groups, all but one in `8100`) |
| same web URL + page | the same page captured under two capture-job slugs (`nps-grand-canyon` / `nps-grca`, `usgs-main-home` / `usgs-home`, `nps-yose` / `nps-yosemite`) |
| photo bursts | 1000–1600 shots whose filename timestamps are ≤120 s apart, plus 15 near-duplicate pairs seen on the contact sheets (most have no timestamp) |

A family is eligible **only if every member shares one bucket of the canonical family
split**. 43 families (133 ids) straddle it and are never picked. This keeps squintly
compatible with every other consumer: a squintly training label never lands on an image
some other model treats as validate/test, and the confirmatory reserve never holds a
near-twin of a training image. The corpus split itself is unchanged; the leak is
documented in `benchmarks/split_leak_audit_2026-09-22.md`.

**2. Visual screening.** Every non-AI image was graded by eye from 200-px contact sheets
(thumbnails rendered by zenpipe's `pristine_downscale`, Mitchell, linear light):

| grade | meaning | ids |
|---|---|--:|
| A | engaging — a picture people would choose to look at | 367 |
| B | acceptable | 316 |
| C | dull for paid viewing; used only when a stratum needs it | 516 |
| X | excluded, reason recorded | 961 |

Exclusions: the 910 AI-generated images (squintly's own design decision, see its
`build_demo_corpus.py`), the 32 `screenshot-unverified` mobile screenshots (license),
private individuals as subjects without a model release (3), 7 bot-blocked
"Access Denied" captures, 5 broken-layout captures, and 4 blank pages.

**This screening is one pass by Claude from thumbnails, not a human curator.** It judged
subject appeal and legibility at thumbnail scale. It did not judge crops, and it cannot
see artifacts that only show at 1:1. A human pass in squintly's curator mode
(`#curator`) should confirm the picks before paid collection, and it should pick crops.
EPA pages (`5200`–`5224`) were graded from their descriptors: the thumbnail renderer
refuses their RGBA sources (see Known gaps).

**3. Picks.** Per stratum and bucket, candidates are taken A before B before C. Within a
grade they follow farthest-point order over ten z-scored zenanalyze content features
(`colourfulness`, `edge_density`, `skin_tone_fraction`, `gradient_fraction_smooth`,
`noise_floor_y`, `grayscale_score`, `flat_color_block_ratio`,
`high_freq_energy_ratio`, `luma_histogram_entropy`, `laplacian_variance`, at
`full`/`native`), starting from the member nearest the stratum centroid. So a stratum
spreads across skin, sky gradients, saturated chroma and fine texture instead of
repeating one look. At most one pick per family.

| stratum | batch1-train | reserve-test | source folders |
|---|--:|--:|---|
| photo-people | 10 | 5 | 2000 |
| photo-food | 14 | 6 | 1600 |
| photo-landscape | 14 | 6 | 1400 (sky, sea, snow, ice, sunsets) |
| photo-flora | 12 | 3 ▲ | 1400 (flowers, foliage) |
| photo-interior | 12 | 5 | 1200 |
| photo-general | 14 | 6 | 1000 |
| art-reproduction | 12 | 5 | 3000, 3300 |
| render-texture | 6 | 3 | 2200, 2400 |
| illustration-scan | 10 | 4 | 6600 |
| document-graphic | 12 | 5 | 5000 colour, EPA/NOAA figures and covers, patent drawings |
| document-text | 8 | 4 | EPA/NOAA text, 6800, patent text |
| chart | 10 | 4 | 7000 charts, heatmaps, flat-colour polygons |
| web-screenshot | 14 | 6 | 8100, one page per family |

▲ short: only 3 bucket-clean flora families exist in test.

Grades picked: train 109 A / 34 B / 5 C; reserve 36 A / 23 B / 3 C. Seven of the eight
C picks are text pages, where the corpus has little that is attractive and the stratum
is needed anyway (text is where SSIM-family metrics most often part ways with human
judgment). The eighth, `3319` (reserve art), fills a bucket short of A/B art; swap it if
a curator finds better.

**4. Presentation suggestion** (`presentation` column): what a phone can show at 1:1
device pixels without panning.

- `scaled:<rungs>` — photos, art, renders, illustration plates. Rungs come from the
  VARIANTS-SPEC grid and stop at 1024 (no current phone is narrower than ~1080 device
  px). **Lossy-origin sources (jpg/heic, 131 of the 210) are only offered at ≥3×
  downscale**, so the reference an observer compares against does not carry the
  source's own JPEG/HEIC artifacts.
- `native-window:<side>` — documents, charts, screenshots: a native-resolution window,
  because text is never downscaled on the web, and a 240-px thumbnail of a text page is
  not a stimulus. Placement is not chosen here; zensally's smart crop
  (`ContentAnalyzer` → `zenlayout::smart_crop`, 9:16) or the curator should choose it.

**5. Split use.** `batch1-train` is for the development labels that squintly's
`docs/STUDY_READINESS_2026-09-15.md` §2 recommends for the first paid batch.
`reserve-test` is for a later confirmatory study: do not mine it, and do not run
pilots on it. Validate-bucket families are left in `pool`.

## Known gaps

- **Rendering route.** The reference and every encode must go through one imazen Rust
  path (zencodecs decode → zenresize linear light), per STUDY_READINESS §3. squintly's
  builder still decodes, converts ICC and resizes with Pillow (`LANCZOS`, gamma space),
  so it cannot consume this set as-is.
- **EPA pages (`5202`, `5218` train; `5217` test).** The sources are RGBA with an unused
  alpha channel and no colour chunk. `pristine_downscale` refuses them on write-verify:
  zenpng writes RGB8 with the transfer unknown. The same route will need a fix, or
  these three picks swapped out.
- **`3006`** (Hiroshige, Art Institute): Adobe RGB with gamma 2.2 has no CICP code, so the
  pristine route refuses it (as in `pristine-8th`). It needs an explicit, recorded
  conversion to sRGB, or a swap.
- **`1449`** (not picked) is a 124 MP panorama above zenpng's default 120 MP decode limit.
- **Missing content classes.** No real (non-AI) product photography, and no high-DPR
  phone screenshots with cleared licenses (the `8000` set is third-party and unverified,
  and every `8100` mobile viewport was captured at DPR 1). E-commerce products and
  phone UI are large shares of web traffic, so both are gaps worth filling for a
  phone-first study.
- **HDR.** `hdr_available` marks the 17 picks with a 16-bit PQ companion (11 train,
  6 test). No HDR arm is proposed: STUDY_READINESS keeps native HDR behind physical
  display qualification.
