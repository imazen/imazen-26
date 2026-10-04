# 2026-10-07-r12-reps-latest (latest image, corpus representatives) — round 12

Archives live on block storage, not in git:

    /mnt/v/output/imazen-26-compat/2026-10-07-r12-reps-latest/results-export/

sha256 per archive:

    40b91d0dd450a9e960828acf08d2b3e105ef189d5c6c018724a58a2df768ccb4  hdr.tsv.gz
    6f863a5c0983d7c5edd147e859db5fba914227afefcd4be52ec67fe25e24fa73  matrix-colour.tsv.gz
    e9ebd27968df5db216af99b1a35bec47d58276f0655597eb1ffa32ac355eadf3  matrix-gainmap.tsv.gz
    937a8867c5ae245bd30316dfc96ed92dc8a427ff16e06bd8bd3545a8bb1ceaa0  matrix-orientation.tsv.gz
    2b81661531200a7ab76f15441368892696a646f2a6eaa8dbde4c141054283b0f  matrix-other.tsv.gz
    67d87d8a9a31a66137d4eecc96ab8cac261e508dd9083ee6ebfde120a68b3764  matrix.tsv.gz

45 corpus representatives × 35 adapters. Non-zen renders are hash-pinned
(`output_sha` = full-resolution PNG sha at decode) then replaced on disk
by ≤1024 px thumbnails (`thumb_sha`); `--check` refuses a PNG that hashes
to neither. Zen/zen-raw renders stay full-resolution.

Round 12 re-scored the round-11 cells against regenerated hypotheses:
HEIC `stored` bases are now decoded by heif-convert (libde265) from a
remux that drops `irot`/`imir`/`clap` (`probe --remux
--drop-transform`), each `stored` render asserted against the primary
item's `ispe` dims; iPhone reps whose `auxid:2` depth aux libheif
rejects decode via a depth-dropped remux, pixel payload verbatim. The
r11 bases carried the display transforms applied — every HEIC
orientation verdict in r11 was inverted by that (see the doc's
withdrawn-claims section). All 21 rep HEIC hypotheses were re-rendered;
the `fixtures/hyps/` archive differs from
`2026-10-07-r11-reps*/fixtures/hyps/` on every HEIC row. Also new:
webkit-canvas all-zero readbacks are `flaky` (excluded from error
counts and LTS-vs-latest comparisons); corpus-bucket calibration folds
in the macOS reps platform decoders (imageio-raw, sips) via
`CM_CALIBRATE_EXTRA`, named in calibration.tsv's `decoders` column;
output PNGs carrying iCCP/cICP/sRGB are converted to sRGB (relative
colorimetric) before scoring (`out_profile` column).

Source data: /mnt/v/output/imazen-26-compat/2026-10-07-r12-reps-latest/{matrix,decode,hdr,versions,calibration}.tsv,
per-adapter JSONs, index.html contact sheet, SHA256SUMS, fixtures/
(45 corpus rep inputs + their hypothesis renders).

Build reproducibility (repo convention: tool Cargo.lock is not committed;
see tools/compat-matrix/.gitignore):

    /mnt/v/output/imazen-26-compat/2026-10-07-r12-reps-latest/compat-matrix.Cargo.lock
    sha256 d6afbef86fba12a18049815abfd22e5c667740e886712da3180b055352c49b84

Regenerate: scripts in tools/compat-matrix/scripts/ — corpus_reps.py
(rep selection), run_matrix.sh (sweeps; phase 1 is a per-format
capability probe — `PHASE1_ONLY=1` runs it standalone — recording
`n/a` for unsupported formats; `nice -n 19` inside the container),
sweep_zen.sh (native zen columns; appends `adapter=<name>
sha256=<sha>` platform lines), reps_thumbs.sh
(output_sha/thumb_sha stamping), hdr_table.py (niced container runs),
export_results.sh.
Matrix aggregation / verification is `compat-matrix matrix [--check]`.
