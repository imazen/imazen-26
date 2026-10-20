# Minimal v4 publication — 2026.10.19

The owner approved these four repositories, their image binaries, family-preserving
branches, R2-backed XL Git LFS, and dataset releases. All four are public with the
tag `v2026.10.19`. Tags and `main` contain documentation and the catalogue; image
files are on `train`, `validate` and `test`. Each main tree's `BRANCHES.tsv` pins
the data commits and manifest hashes.

| Repository and release | IDs | Files | Encoded bytes | Tagged main commit |
|---|---:|---:|---:|---|
| [Originals](https://github.com/imazen/imazen-26-originals/releases/tag/v2026.10.19) | 2,109 | 2,109 | 4,838,631,909 | `e5027f415b7b1c7a50838480679528b8c331766d` |
| [JXL source colour](https://github.com/imazen/imazen-26-jxl-p3/releases/tag/v2026.10.19) | 2,109 | 2,183 | 6,297,804,440 | `df5ff569eedd455fb4040c0b7a3a6e3a8d4ff84b` |
| [JXL sRGB](https://github.com/imazen/imazen-26-jxl-srgb/releases/tag/v2026.10.19) | 2,109 | 2,109 | 4,903,867,897 | `ee2fa8af3963d56ea84d63aa9443436edac55016` |
| [XL](https://github.com/imazen/imazen-xl-26/releases/tag/v2026.10.19) | 6 | 22 | 1,174,235,176 | `a2ad2b075a88935d7ad6dc9618614af471422b38` |

Total: 6,423 file records and 17,214,539,422 encoded bytes. These are payload
totals, not measured Git pack sizes. The three ordinary ID sets are identical;
XL is disjoint and includes all three DNGs. Ordinary PNG repositories are deferred;
XL includes the public PNG twins of its size-limit images. IMI remains private.

## Verification

- Read and SHA-256-verified every approved source file before uploading.
- Checked every remote branch SHA and committed manifest hash. Streamed all
  6,401 ordinary image blobs from Git and checked the 22 committed LFS pointers.
  Checked every reachable commit for paths absent from its manifest and explicit
  documentation list. These checks cover all twelve data branches.
- Downloaded all 22 XL file records through the public LFS endpoint and verified
  their complete bytes. The fresh Git LFS client fetched 20 distinct objects.
- Created fresh consumer repositories: complete test checkouts for originals
  (401 files), JXL source colour (421), and JXL sRGB (401), plus the XL train
  pointer checkout and all XL LFS objects. Anonymous HTTPS manifests match the
  approved hashes. These checkouts complement the full Git-tree verification.
- Main's metadata validator passed on Linux, Windows ARM and macOS ARM in each
  repository. These CI jobs validate catalogues and the absence of image files
  on main; the full data-byte checks above ran separately.
- After CI and consumer checks passed, created each tag and release. Read back
  the remote tag SHA, public release status and anonymous tagged README bytes.
  Every tag points to the main commit in the table.

CI: [originals](https://github.com/imazen/imazen-26-originals/actions/runs/39352505408),
[JXL source colour](https://github.com/imazen/imazen-26-jxl-p3/actions/runs/39352536493),
[JXL sRGB](https://github.com/imazen/imazen-26-jxl-srgb/actions/runs/39352600126),
[XL](https://github.com/imazen/imazen-xl-26/actions/runs/39352605922).

The publication copied existing approved bytes; it did not re-encode them.
Codec readback evidence is in the [current-main recheck](current_main_recheck_2026-10-19.pointer.md).
Publisher: `scripts/publish_corpus.py`, source `9fdd55ee`; recipes in
`tools/render-v4/justfile`. A rejected upload was retried without rewriting any
remote history; the path and ancestry gates are recorded in `CLAUDE.md`.

## Evidence location

Checked from dev on 2026-10-20 UTC:

`/mnt/tower/output/imazen-26-git-publication-2026-10-19/`

`receipts/` holds input, LFS, branch, committed-byte, public-consumer, CI and
release evidence. `logs/` retains the full publication logs. Existing local upload
and consumer repositories are retained under `repos/` and `consumer-checks/`.
`publication-evidence.json` hashes the receipts; its SHA-256 is
`c483327a1107877516c9ee2473bbc121a58df1bf1cff5b8be9f24c0a60828d05`.

Resource record for fresh public consumer checks:
`run-heavy: done rc=0 550s | peak-RSS 1.35GiB | min-avail 44682MiB | peak-load 7.32`.
Release and remote proof:
`run-heavy: done rc=0 21s | peak-RSS 0.04GiB | min-avail 48551MiB | peak-load 3.56`.
