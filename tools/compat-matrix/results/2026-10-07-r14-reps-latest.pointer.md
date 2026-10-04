# 2026-10-07-r14-reps-latest (real-camera corpus, latest image) results — round 14

Archives live on block storage, not in git:

    /mnt/v/output/imazen-26-compat/2026-10-07-r14-reps-latest/results-export/

sha256 per archive:

    40b91d0dd450a9e960828acf08d2b3e105ef189d5c6c018724a58a2df768ccb4  hdr.tsv.gz
    42f13fd7919a95b29a7d1f91252a9c57415a71510e3cda19455c97f1ee614521  matrix-colour.tsv.gz
    0bfab8657e1c5d120551fcddab6f23603e270d5378f415b9f0ef3c219f07f2e5  matrix-gainmap.tsv.gz
    3a371bbaff5dd8faf30cf50c5692b3022694230a538ccf8bd71e2f73e7fa6fa2  matrix-orientation.tsv.gz
    98f497f4e4ebc2daceca26e53d5b1c56ba731afe4afa71119ae63e2823c85de6  matrix-other.tsv.gz
    1f90f3c77680ba0059728f811b44d62f3b544b4956733d7790bbd572ae9b2fff  matrix.tsv.gz

Same round-14 corrections as `2026-10-07-r14-reps.pointer.md`. Shape on
the latest image: 1,575 cells — 608 `n/a`, 100 `error`, 2 `flaky`, 865
`ok`; among `ok`: 454 `not-measurable`, 196 `stored`, 106
`orient-only`, 71 `correct`, 35 `other`, 3 `colour-only`. Reps→latest
diff: 123 differing cells — 93 `error→ok`, 27 `ok` verdict flips, 30
`ok→ok` rows, 3 flaky cells excluded from move tallies. gm-best opens
8/8 orient6 HEICs here (vs 6/6 on LTS), all `other`. The `.unm` corpus
fold reaches T=4 with the `imageio-raw`+`sips` host columns; the
native-ffmpeg `.unm` cells (n9.0.1, real HEIF demuxer) sit at 8–14 vs
the libde265 base and are folded in.

Source data: /mnt/v/output/imazen-26-compat/2026-10-07-r14-reps-latest/
{matrix,decode,hdr,versions,summary,calibration,calibration-detail}.tsv,
probe/<adapter>.json, per-adapter cell JSONs (incl. `.unm.*` cells),
index.html, SHA256SUMS + SHA256SUMS.fixtures, tool.txt, fixtures/.

The calibration.tsv in this run is byte-identical to the r14-reps LTS
copy and to `fixtures/calibration.tsv` — the fold pools both siblings'
cells (`CM_CALIBRATE_POOL`), so one canonical T covers the whole judged
population.
