# Changelog

## [Unreleased]

### Changed
- Git LFS objects for `variant/png-v3` and `variant/pristine-8th` are served from R2 (`codec-corpus/lfs/imazen-26/<sha256>`) through imazen's git-lfs-s3-proxy instance at `imazen-lfs.pages.dev` instead of GitHub's LFS store; a clone needs no credentials and draws no GitHub LFS bandwidth (branch commits 0264d4d, 9a6cf7a)
- `corpus-guard` requires a credential-free `.lfsconfig` naming the proxy on `variant/*` branches
- README / STORAGE-MAP variant tables list both branches with current pointer counts

### Added
- `scripts/lfs_r2_migrate.py` — plan, server-side copy, batch-API hash verification, and local-cache seeding for moving a branch's LFS objects onto R2
- ACCESS.md §7: the LFS object prefix and its direct URL form
