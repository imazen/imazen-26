# Changelog

## [Unreleased]

### Changed
- Git LFS objects for `variant/png-v3` and `variant/pristine-8th` are served from R2 (`codec-corpus/lfs/imazen-26/<sha256>`) through imazen's git-lfs-s3-proxy instance at `imazen-lfs.pages.dev` instead of GitHub's LFS store; a clone needs no credentials and draws no GitHub LFS bandwidth (branch commits 0264d4d, 9a6cf7a)
- `corpus-guard` requires a credential-free `.lfsconfig` naming the proxy on `variant/*` branches
- README / STORAGE-MAP variant tables list both branches with current pointer counts

### Added
- `variant-sets/rdgap-train26@2026-07-02` and `variant-sets/lossless-bench-43@2026-06-10` — legacy imports of the selections zenavif and jxl-encoder built from this corpus, so their results cite a set id; 3 rdgap picks are validate under the family map
- `variant-sets/squintly-candidates@2026-09-22` — proposed squintly stimulus set: 148 train + 62 reserve-test images over 13 content strata, visually screened, one pick per stimulus family, families that straddle the canonical split excluded; generator `scripts/build_squintly_candidates.py` + `scripts/squintly_screening.py`
- `benchmarks/split_leak_audit_2026-09-22.md` — what the family split still misses: 11 byte-identical duplicate groups (7 span buckets), photo bursts (107 of 149 same-session pairs straddle), all 15 NOAA reports, and a derived corpus that re-buckets 217 of 349 copied images
- `scripts/lfs_r2_migrate.py` — plan, server-side copy, batch-API hash verification, and local-cache seeding for moving a branch's LFS objects onto R2
- ACCESS.md §7: the LFS object prefix and its direct URL form
- `.lfsconfig` on `main`, so branches created from it inherit the proxy; `main` still tracks nothing in LFS
