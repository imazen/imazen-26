# 2026-10-07-r9-reps-latest (latest image) results — round 9

Archives live on block storage, not in git:

    /mnt/v/output/imazen-26-compat/2026-10-07-r9-reps-latest/results-export/

sha256 per archive:

    3f99ef7800410e4ed8492753d57f231e829e848421c168fec75237b8c37ff9c5  hdr.tsv.gz
    bb1cccb746a34596eac6b36617d8c2d13ec5673c65aca25924d22ed51a9f84f8  matrix-colour.tsv.gz
    c34e5ad9f8e24015e932db9e0d0a382861d3915d402afb6d7e2688d93e3ed64b  matrix-gainmap.tsv.gz
    5d70b442b1ebae2f8e673c9c7fb531134551867a285d6b3fa110eda38367afcb  matrix-orientation.tsv.gz
    4aa796d344b8f63e3652edff7128eead438c13a30d64fe6bbca3f2217ad44fe6  matrix-other.tsv.gz
    2dc6942929ada0a6e97a64c0f534da942dc59b8e8ed970fb534122e36be5374b  matrix.tsv.gz

Source data: /mnt/v/output/imazen-26-compat/2026-10-07-r9-reps-latest/{matrix,decode,hdr,versions,calibration}.tsv,
per-adapter JSONs, index.html contact sheet, SHA256SUMS
(covers every tsv/gz/json in the run dir),
fixtures/ (fixtures.tsv, hypotheses.tsv, calibration.tsv, hyps/ renders,
the fixture files themselves — the inputs the run was measured on).

Build reproducibility (repo convention: tool Cargo.lock is not committed;
see tools/compat-matrix/.gitignore):

    /mnt/v/output/imazen-26-compat/2026-10-07-r9-reps-latest/compat-matrix.Cargo.lock
    sha256 d6afbef86fba12a18049815abfd22e5c667740e886712da3180b055352c49b84

Regenerate: scripts in tools/compat-matrix/scripts/ — run_matrix.sh
(decode sweeps + matrix aggregation; checkpoint cells keyed on
image_id + adapter_sha + fixture sha), sweep_zen.sh (native zen/zen-raw
columns), census.sh (full-corpus census + reconcile), signalled_pass.sh
(header-level orientation), metadata_readers.sh (metadata table),
hdr_table.py (HDR/gain-map table), export_results.sh (this archive).
