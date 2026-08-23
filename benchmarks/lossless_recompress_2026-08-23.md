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
