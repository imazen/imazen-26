# 2026-10-07-r10-reps-latest (corpus representatives, latest image) — round 10

Archives live on block storage, not in git:

    /mnt/v/output/imazen-26-compat/2026-10-07-r10-reps-latest/results-export/

sha256 per archive:

    40b91d0dd450a9e960828acf08d2b3e105ef189d5c6c018724a58a2df768ccb4  hdr.tsv.gz
    0175f68ff872c4f2b7655984e0b1c38abcc03288fad6df4fc2fa3261fd912b13  matrix-colour.tsv.gz
    2de75859c251c752c5ed29060ae2ded08a4215e3aa488004dd8a84c232f38e6b  matrix-gainmap.tsv.gz
    af1f7c3787befc56a9fe485677365a626e558dc6c418fa8b9608a8d0d3a74fd2  matrix-orientation.tsv.gz
    141a5c6e4c5147f41465a59ae69f78d7eaf622bc5a5e607de0e62357ed08aa86  matrix-other.tsv.gz
    c30513c20158a55fe4cd85f3365c2948aded080205b3340a43f7fec31588377e  matrix.tsv.gz

Source data: /mnt/v/output/imazen-26-compat/2026-10-07-r10-reps-latest/{matrix,decode,hdr,versions,calibration}.tsv,
per-adapter JSONs, index.html contact sheet, SHA256SUMS (covers every
tsv/gz/json in the run dir), fixtures/ (corpus_reps.tsv, hypotheses.tsv,
the 45 sha256-asserted corpus rep files + hyps/ renders — the inputs the
run was measured on). Non-zen cell PNGs are <=1024px thumbnails of the
recorded full-resolution renders (each cell JSON's output_sha records the
full-res sha; zen/zen-raw keep full resolution).

Build reproducibility (repo convention: tool Cargo.lock is not committed;
see tools/compat-matrix/.gitignore):

    /mnt/v/output/imazen-26-compat/2026-10-07-r10-reps-latest/compat-matrix.Cargo.lock
    sha256 d6afbef86fba12a18049815abfd22e5c667740e886712da3180b055352c49b84

Regenerate: scripts in tools/compat-matrix/scripts/ — run_matrix.sh,
sweep_zen.sh, reps_thumbs.sh (output_sha stamping + box-chain
thumbnail pass), corpus_reps.py, hdr_table.py, export_results.sh.
