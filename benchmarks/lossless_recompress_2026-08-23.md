# Lossless recompression of the registered variant sets — MEASURED 2026-08-23

Question: how many bytes does each variant set occupy as stored (PNG), and how much
smaller would it be as lossless JPEG XL or lossless WebP?

**Method — every file, not a sample.** All 7,119 files of the three surviving
registered sets were individually re-encoded with `cjxl v0.11.1 -d 0 -e 7` and (8-bit
sets only) `cwebp 1.5.0 -lossless -m 6 -q 100`; encoded sizes recorded, outputs
deleted. Run under a 20-worker/24G-cgroup cap, 967 s wall, 0 encode failures.
Losslessness verified by roundtrip (`djxl`/`dwebp` → `compare -metric AE` = **0**
pixels different on spot files from every set, and the 16-bit HDR file decodes back
at depth=16). Per-file data: `lossless_recompress_{cleanpicker,sdrfps,hdrgrid}_2026-08-23.tsv`
(columns `file, png, jxl, webp`).

## Results

| set | files | PNG (as stored) | lossless JXL | ratio (median/file) | lossless WebP | ratio (median/file) |
|---|--:|--:|--:|--:|--:|--:|
| `cleanpicker-ladder11@2026-06-26` (8-bit) | 4,497 | 1.02 GiB | 0.67 GiB | 0.656 (0.669) | 0.69 GiB | 0.673 (0.686) |
| `sdr-fps-1p5gp@2026-06-14` (8-bit) | 1,482 | 1.61 GiB | 0.79 GiB | 0.487 (0.652) | 0.87 GiB | 0.539 (0.670) |
| `hdr-grid-15scale@2026-06-14` (**16-bit PQ**) | 1,140 | 7.72 GiB | 4.81 GiB | 0.624 (0.667) | **n/a** | — |
| **total** | **7,119** | **10.35 GiB** | **6.27 GiB** | **0.606** | | |

- **JXL saves 4.08 GiB (39.4%) across everything**, and beats lossless WebP on every
  set (WebP saves 32.7% / 46.1% on the two sets it can hold).
- **Lossless WebP cannot represent the HDR set at all** — VP8L is 8-bit-only; an
  8-bit squash would violate the zero-tolerance pixel rule, so it is reported as
  unsupported, not as a ratio.
- The sdr-fps total ratio (0.487) is better than its median (0.652) because the FPS
  selection's few hundred large full-detail renditions compress far better than the
  thumbnail mass — the byte total is dominated by the big files.

## Interpretation / caveats

- **Optimized-PNG baseline (MEASURED 2026-08-23, follow-up):** `oxipng 10.2.0 -o 4`
  (no stripping — cICP/chunks preserved, verified; roundtrip AE=0, 16-bit kept), all
  7,119 files, 302 s, 0 failures. Per-file TSVs: `oxipng_{cleanpicker,sdrfps,hdrgrid}_2026-08-23.tsv`.

  | set | oxipng ratio (median/file) | JXL vs optimized PNG |
  |---|--:|--:|
  | cleanpicker-ladder11 | 0.890 (0.923) | 0.737 |
  | sdr-fps-1p5gp | 0.698 (0.872) | 0.698 |
  | hdr-grid-15scale | 0.875 (0.885) | 0.713 |
  | **total** | **0.849** — 10.35 → 8.79 GiB, saves 1.56 GiB | **0.713** — JXL stays 28.7% below optimized PNG |

  So of JXL's 39.4% total saving, ~15 points were generic PNG slack (the as-rendered
  files were never optimized — the large sdr-fps renditions had the most, 0.698) and
  the remaining ~29% below even optimized PNG is genuine format advantage. Ranking on
  every set: **JXL < WebP < oxipng < stored PNG**.
- Every canonical reference to these sets (registry `files.tsv`, R2 refs, ledger
  provenance) keys on the **PNG bytes' sha256**. Re-encoding changes every hash:
  converting a registered set in place is a NEW set under the registry contract,
  never an overwrite. Use JXL for archive/mirror tiers or for future successor sets
  registered natively as JXL — not for silently rewriting existing refs.
- At R2 pricing the saving is ~$0.06/month — the practical wins are LAN-store hot-tier
  headroom and transfer time, not the cloud bill.

Environment: cjxl v0.11.1 (apt), cwebp/dwebp 1.5.0 (upstream binaries), single-thread
per file × 20 workers via run-heavy; sources read from the `/mnt/v` set locations
recorded in each SET.md.

## Decode speed (MEASURED 2026-08-23, follow-up)

Serial single-process decodes of every file, interleaved per file across formats on an
idle box (load-gated <2.0); decoders `pngtopam` (netpbm 11.10.2, stdout→/dev/null) and
`djxl` v0.11.1 (`/dev/stdout --output_format ppm`); a second jxl pass adds
`--num_threads 1`. Per-file data: `decode_times{,_jxl1t}_2026-08-23.tsv`.

| set | PNG MP/s | oxipng MP/s | JXL 1-thread MP/s | JXL default (multithread) MP/s |
|---|--:|--:|--:|--:|
| cleanpicker-ladder11 | 29.3 | 31.3 | 8.5 | 18.1 |
| sdr-fps-1p5gp | 40.0 | 44.4 | 11.2 | 75.9 |
| hdr-grid-15scale (16-bit) | 23.9 | 26.5 | 5.9 | 38.2 |
| **total (10.3 GiB / ~4 GP)** | **29.7** (136.6 s) | **32.6** (124.4 s) | **7.9** (512.2 s) | **34.8** (116.4 s) |

- **Per core, lossless JXL decode is ~3.7× slower than PNG** on this corpus (3.4–4.5×
  by set; worst on 16-bit HDR). That is the real format cost of the 29% byte win over
  optimized PNG.
- **`djxl`'s default multithreading buys it all back and more** (34.8 vs 29.7 MP/s
  aggregate wall) — and PNG structurally cannot do this (DEFLATE is serial within a
  file), so intra-file parallel decode is a genuine JXL capability, at the price of
  occupying many cores per image.
- **oxipng'd PNGs decode ~5–10% FASTER than the as-rendered PNGs** (fewer compressed
  bytes to inflate) — optimization is a small decode win, not a cost.
- Process-spawn+init floors (50 reps, tiniest file): djxl ~3.9 ms vs pngtopam ~2.2 ms —
  inflates jxl's per-file medians on the thumbnail-heavy set; the MP/s columns are the
  comparable numbers.
- Tool caveat: these are the reference CLI decoders; in-process decoders (zenpng /
  zenjxl-decoder in the fleet path) avoid the spawn floor and will shift absolute
  numbers, not the ~4× single-thread ordering.

## oxipng losslessness — corpus-wide verification (MEASURED 2026-08-23, follow-up)

The earlier "verified" was a single-file probe; this is the census. Every one of the
7,119 pairs was re-encoded and checked three ways: decoded-pixel-stream hash
(`pngtopam | sha256`), IHDR depth/colortype/interlace diff, and full chunk-sequence
diff (`pngmeta_{orig,oxipng}_*_2026-08-23.tsv`).

**Verdict: colorimetrically lossless everywhere; NOT container-preserving in default
mode for 341 SDR files (4.8%).**

- **Pixel values: identical on all 7,119 pairs.** The 269 pixel-stream hash
  mismatches were representation-only (channel count); ImageMagick `compare -metric
  AE` on every flagged pair = **0 differing pixels, 341/341**.
- **HDR set: perfect container preservation** — 0/1,140 deviations of any kind;
  **cICP present on 1,140/1,140 outputs**; depth 16 everywhere; nothing stripped.
- **ICC profiles: preserved** — the 55 cleanpicker files carrying `iCCP` all still
  carry it (same file set before/after).
- **Container changes (default mode, SDR only):** oxipng's lossless reductions
  rewrote 341 files — RGB→grayscale (colortype 2→0) where R=G=B, and RGB→palette
  (2→3, `PLTE` added) where ≤256 colors. Decoded values are untouched, but channel
  count / color model changes are visible to anything that reads the container
  (zenanalyze's `channel_count`-class features, strict format assertions), so for
  dataset use this is drift, not noise.
- **The fix is free: `oxipng -o 4 --nx`** (reductions disabled, filter/deflate
  optimization only) is container-preserving by construction and costs almost
  nothing: total ratio **0.851 vs 0.849** (cleanpicker 0.897 vs 0.890, sdrfps 0.703
  vs 0.698, hdrgrid identical 0.875). Per-file sizes:
  `oxipng_nx_*_2026-08-23.tsv`.

**Standing rule for corpus/dataset PNGs: use `oxipng -o 4 --nx` (never default
reductions, never `--strip`).** The decode-speed and byte-ratio conclusions above
are unaffected (the two modes differ by ~0.2% of bytes).
