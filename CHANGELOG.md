# Changelog

## [Unreleased]

### Changed
- Git LFS objects for `variant/png-v3` and `variant/pristine-8th` are served from R2 (`codec-corpus/lfs/imazen-26/<sha256>`) through imazen's git-lfs-s3-proxy instance at `imazen-lfs.pages.dev` instead of GitHub's LFS store; a clone needs no credentials and draws no GitHub LFS bandwidth (branch commits 0264d4d, 9a6cf7a)
- `corpus-guard` requires a credential-free `.lfsconfig` naming the proxy on `variant/*` branches
- README / STORAGE-MAP variant tables list both branches with current pointer counts

### Added
- `tools/corpus-thumbs` — renders oriented, sRGB thumbnail sprite sheets of every source through zencodecs, zenpixels-convert and zenresize; used for the corpus contact sheet (output on block storage)
- `benchmarks/layer_repos_2026-09-25.md` — proposal for `imazen-26-originals` plus `-png-srgb`, `-png-p3`, `-jxl-srgb`, `-jxl-p3` repositories with train/validate/test branches (sizes, GitHub fit, rendering rules; HDR only in the P3 layers); measured: progressive→sequential re-encoding is coefficient- and pixel-exact on all 417 JPEGs and makes all 417 JPEG-in-JXL rebuilds exact; coefficient-domain rotation is clean for only 2 of 134 rotated JPEGs (the rest trim 8–12 rows and differ up to 20 levels at the new edge); zenjpeg rotation bugs filed as zenjpeg#204/#205
- `tools/jpeg-lossless-check` — the measurement tool
- `benchmarks/signal_index_2026-09-24.md` — orientation, ICC, CICP and HDR signalling of all 2,160 sources by file type: 207 rotated, 365 with ICC (275 Display P3), 0 with CICP, 43 with gain maps (76 once the JPEG ones are restored), no PQ/HLG sources; 42 HEICs carry colour only on their tiles; 210 png-v3 renders are tagged sRGB although the source is wide-gamut; normalization rules and repositories-by-file-type sizing
- `tools/corpus-signal-probe` — the indexer: zencodecs' effective view plus each codec crate's signalled view
- `scripts/restore_uhdr_gainmaps.py` — builds verified restore candidates for the 33 UltraHDR JPEGs that lost their gain maps (canonical Exif/ICC/image data + the original's gain-map pieces, no location metadata); candidates live on block storage, the canonical files are unchanged
- `benchmarks/jpeg_in_jxl_validation_2026-09-22.md` — lossless JPEG→JXL transcode of all 417 JPEG sources: 0.824× the JPEG (a lossless JXL render is 2.40×), ICC carried byte-exact, 384/417 rebuild byte-exact at unpublished HEAD revisions (267/350 with the published crates); the transcoder drops EXIF orientation (134 files), 21 trailing-RST and 12 progressive files don't rebuild exactly, gain maps aren't exposed as `jhgm`; the canonical corpus's 33 UltraHDR JPEGs lost their gain maps in the metadata rewrite
- `tools/jxl-transcode-check` — the validation tool, buildable against the published crates or the HEAD revisions
- `benchmarks/split_branches_design_2026-09-22.md` — proposal for `train`/`validate`/`test` branches (LFS on R2), PNG + JXL lossless twins with decoded-pixel hashes, a raw-git conformance repo and a v4 render pass; measured: lossless JXL (jxl-encoder `cjxl-rs`) is 0.533× PNG for SDR and 0.646× for HDR over all 2,233 renders, no JXL over 100 MB
- `benchmarks/color_orientation_audit_2026-09-22.md` and `benchmarks/subset_adoption_review_2026-09-22.md` — ~165 Display-P3 photos labelled BT.709 in png-v3, orientation differs between png-v3 and pristine-8th; what the zen repos built to test better and what to adopt
- `variant-sets/rdgap-train26@2026-07-02` and `variant-sets/lossless-bench-43@2026-06-10` — legacy imports of the selections zenavif and jxl-encoder built from this corpus, so their results cite a set id; 3 rdgap picks are validate under the family map
- `variant-sets/squintly-candidates@2026-09-22` — proposed squintly stimulus set: 148 train + 62 reserve-test images over 13 content strata, visually screened, one pick per stimulus family, families that straddle the canonical split excluded; generator `scripts/build_squintly_candidates.py` + `scripts/squintly_screening.py`
- `benchmarks/split_leak_audit_2026-09-22.md` — what the family split still misses: 11 byte-identical duplicate groups (7 span buckets), photo bursts (107 of 149 same-session pairs straddle), all 15 NOAA reports, and a derived corpus that re-buckets 217 of 349 copied images
- `scripts/lfs_r2_migrate.py` — plan, server-side copy, batch-API hash verification, and local-cache seeding for moving a branch's LFS objects onto R2
- ACCESS.md §7: the LFS object prefix and its direct URL form
- `.lfsconfig` on `main`, so branches created from it inherit the proxy; `main` still tracks nothing in LFS

### Fixed
- `color_orientation_audit_2026-09-22.md` §2: the "Linear Gray" profile on 3 iPhone HEICs sits on the primary image, not the gain map, and the other 19 of the 22 are Adaptive HDR files with an SDR base; png-v3's wide-gamut mislabels number 210, not ~165
