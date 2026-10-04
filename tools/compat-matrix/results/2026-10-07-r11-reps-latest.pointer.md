# 2026-10-07-r11-reps-latest (latest image, corpus representatives) — round 11

Archives live on block storage, not in git:

    /mnt/v/output/imazen-26-compat/2026-10-07-r11-reps-latest/results-export/

sha256 per archive:

    40b91d0dd450a9e960828acf08d2b3e105ef189d5c6c018724a58a2df768ccb4  hdr.tsv.gz
    0f1c64e2d7124828c0a179c2186fd81daa976488ea2621104ba037b627a28ddb  matrix-colour.tsv.gz
    6fde6ebb9c5d84d0e08fa9b4ba6376c5d03c29afe71ee1ad4d904e9eb5b8a83f  matrix-gainmap.tsv.gz
    56a9ab77c8d00cc528fd4f664fb9c0f986dab05bda32890bdc744a3b435c32ab  matrix-orientation.tsv.gz
    28865fe065c71694a09ca52d8bc6325795899cc8d68bd34b01f23bf8da1df58e  matrix-other.tsv.gz
    35e5630b73eb7bd9cffccc1a897dcdb565ced2eed666627a0e79d7054a3bceb9  matrix.tsv.gz

45 corpus representatives × 35 adapters. Non-zen renders are hash-pinned
(`output_sha` = full-resolution PNG sha at decode) then replaced on disk
by ≤1024 px thumbnails (`thumb_sha`); `--check` refuses a PNG that hashes
to neither. Zen/zen-raw renders stay full-resolution.

Round 11 re-scored the round-10 cells against regenerated hypotheses
(fixture-sha + decode-command + toolchain-keyed caches cleared and
re-rendered: HEIC reps via heif-convert/libde265 — iPhone reps whose
`auxid:2` depth aux libheif rejects are decoded from a depth-aux-dropped
remux, pixel payload verbatim; DNG via `dcraw_emu -w -t 0 -T -6`, so
`stored` is the sensor raster). The `fixtures/hyps/` archive differs
from `2026-10-07-r9*/fixtures/hyps/` (99 files changed).

Source data: /mnt/v/output/imazen-26-compat/2026-10-07-r11-reps-latest/{matrix,decode,hdr,versions,calibration}.tsv,
per-adapter JSONs, index.html contact sheet, SHA256SUMS, fixtures/
(45 corpus rep inputs + their hypothesis renders).

Build reproducibility (repo convention: tool Cargo.lock is not committed;
see tools/compat-matrix/.gitignore):

    /mnt/v/output/imazen-26-compat/2026-10-07-r11-reps-latest/compat-matrix.Cargo.lock
    sha256 d6afbef86fba12a18049815abfd22e5c667740e886712da3180b055352c49b84

Regenerate: scripts in tools/compat-matrix/scripts/ — corpus_reps.py
(rep selection), run_matrix.sh (sweeps; `nice -n 19` inside the
container), sweep_zen.sh (native zen columns), reps_thumbs.sh
(output_sha/thumb_sha stamping), hdr_table.py, export_results.sh.
Matrix aggregation / verification is `compat-matrix matrix [--check]`.
