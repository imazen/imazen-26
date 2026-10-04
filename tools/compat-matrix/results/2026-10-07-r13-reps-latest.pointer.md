# 2026-10-07-r13-reps-latest (corpus representatives, latest image) — round 13

Archives live on block storage, not in git:

    /mnt/v/output/imazen-26-compat/2026-10-07-r13-reps-latest/results-export/

sha256 per archive:

    40b91d0dd450a9e960828acf08d2b3e105ef189d5c6c018724a58a2df768ccb4  hdr.tsv.gz
    2265281187e07ef728c1758a7dfeea01cb73043f5f9e29ddcfb5bc25d02f85b6  matrix-colour.tsv.gz
    f7151f3367cfbb1b0342667a27ab5de28a7a7dc623f1691b9a35f2bc4ae4d43a  matrix-gainmap.tsv.gz
    c713540ce9784a8310cd69593eb9932600b0edee9434e2e20698e835d161ebc4  matrix-orientation.tsv.gz
    d85201fa7cdb48105c7aec6eab340cf7262411484d6f9b612f0b58d8539e23e8  matrix-other.tsv.gz
    1ba37bb9a64267f1c8010d4616f974ce33cdc6f84e8c69cfc729018052d3f3fb  matrix.tsv.gz

Same 45 corpus reps decoded under `imazen26-compat:latest`. reps→
reps-latest diff (mechanical, `scripts/diff_runs.py`, flaky cells
excluded): 121 cell diffs — 93 `error→ok` (libheif 1.23.2 decodes the
iPhone-16/17 reps 1.17.6 rejected), 25 `ok→ok` verdict moves. Latest
verdict shape: 608 n/a, 100 error + 2 flaky, 471 not-measurable / 200
stored / 106 orient-only / 75 correct / 10 other / 3 colour-only of
865 ok cells; corpus T=25. `hdr-output` names the 24 cells whose
readers emit HDR-declared output on tmap gain-map reps (graphicsmagick
+ heif-dec rows); `mis-tagged:*` covers 34 cells.

Source data: /mnt/v/output/imazen-26-compat/2026-10-07-r13-reps-latest/{matrix,
decode,hdr,versions,summary,calibration,calibration-detail}.tsv,
per-adapter cell JSONs, index.html, SHA256SUMS + SHA256SUMS.fixtures,
tool.txt, fixtures/ (corpus reps + hypothesis renders).

Build reproducibility:

    /mnt/v/output/imazen-26-compat/2026-10-07-r13-reps-latest/compat-matrix.Cargo.lock
    sha256 d6afbef86fba12a18049815abfd22e5c667740e886712da3180b055352c49b84
