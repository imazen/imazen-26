#!/bin/bash
# export_results.sh <out_dir> <fixtures_dir> — reproducible results packaging:
#   results-export/matrix.tsv.gz  (full adapter x fixture verdict table)
#   results-export/colour.tsv.gz / metadata.tsv.gz / gainmap.tsv.gz (class slices)
#   results-export/hdr.tsv.gz     (when hdr.tsv exists)
#   SHA256SUMS over every tsv/gz/json in the run dir
#   pivots.md + index.html (contact sheet) when the scripts' inputs exist.
set -u
OUT="${1:?out dir}"
FIXTURES="${2:?fixtures dir}"
TOOL="$(cd "$(dirname "$0")/.." && pwd)"
cd "$OUT"

mkdir -p results-export
[ -f matrix.tsv ] && gzip -9c matrix.tsv > results-export/matrix.tsv.gz
for cls in colour gainmap orientation other; do
    # r14 L-5: slice on the class column ($3) itself — a verdict or
    # tagged-verdict of `other` must not leak into the class slice.
    [ -f matrix.tsv ] && awk -F'\t' -v c="$cls" 'NR==1 || $3==c' matrix.tsv \
        | gzip -9 > "results-export/matrix-$cls.tsv.gz"
done
[ -f hdr.tsv ] && gzip -9c hdr.tsv > results-export/hdr.tsv.gz
[ -f census/census.tsv ] && gzip -9c census/census.tsv > results-export/census.tsv.gz
[ -f census/signalled/signalled.tsv ] && gzip -9c census/signalled/signalled.tsv > results-export/signalled.tsv.gz
[ -f metadata/metadata.tsv ] && gzip -9c metadata/metadata.tsv > results-export/metadata.tsv.gz

# L1: archive the inputs the run was measured on — fixtures, hypothesis
# renders and calibration — under <run>/fixtures/ so the result dirs are
# self-contained (the scratch fixture dirs are not durable).
mkdir -p fixtures
[ -f "$FIXTURES/fixtures.tsv" ] && rsync -a --exclude 'hyps/.cache' \
    "$FIXTURES/" fixtures/ 2>/dev/null || {
    cp -a "$FIXTURES/fixtures.tsv" "$FIXTURES/hypotheses.tsv" fixtures/ 2>/dev/null
    for d in jpeg png webp avif jxl heic dng icc hyps; do
        [ -d "$FIXTURES/$d" ] && cp -a "$FIXTURES/$d" "fixtures/$d"
    done
}
[ -d fixtures/hyps/.cache ] && rm -rf fixtures/hyps/.cache

# Review-7 §8: hypothesis cache keys name the probe binary by sha256 — record
# the binary that produced this run so a cache key can be traced to a build.
# r14 L-3: the commit recorded is the stack head the binary was built
# from (`--ignore-working-copy` so an export never snapshots the
# workspace — @- is the last committed change); `built_at` is the
# binary's own mtime, not the export time.
{
    b="$TOOL/target/release/compat-matrix"
    [ -f "$b" ] && echo "binary_sha256=$(sha256sum "$b" | cut -d' ' -f1)"
    echo "binary_commit=$(cd "$TOOL" && jj --ignore-working-copy log -r @- --no-graph -T 'commit_id' 2>/dev/null || git rev-parse HEAD)"
    echo "rustc=$(rustc -V 2>/dev/null || echo unknown)"
    [ -f "$b" ] && echo "built_at=$(date -u -d "@$(stat -c %Y "$b")" +%Y-%m-%dT%H:%M:%SZ)"
} > tool.txt

# checksums over everything a reader might re-verify
find . -maxdepth 3 -type f \( -name '*.tsv' -o -name '*.tsv.gz' -o -name '*.json' -o -name '*.txt' \) \
    ! -name '.*' ! -path './fixtures/*' | sort | xargs sha256sum > SHA256SUMS
[ -d fixtures ] && find fixtures -type f ! -name '.*' | sort \
    | xargs sha256sum > SHA256SUMS.fixtures

[ -f matrix.tsv ] && python3 "$TOOL/scripts/pivots.py" "$OUT" > pivots.md
[ -f matrix.tsv ] && python3 "$TOOL/scripts/index_html.py" "$OUT" "$FIXTURES" 2>/dev/null || true
echo "export done -> $OUT/results-export + SHA256SUMS"
