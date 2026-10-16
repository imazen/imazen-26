#!/usr/bin/env bash
# Re-render some ids of a finished render_v4_jxl.sh pass with the current tools.
#
#   scripts/render_v4_jxl_redo.sh <out-dir> <effort> <jobs> <export ids, comma-separated>
#
# Renders the ids' rows of <out-dir>/list.tsv again (render-v4 jxl), and their .hdr.jxl twins
# (render-v4 jxl-hdr) for ids in hdr-report.tsv; jxl-report.tsv and jxl-hdr-report.tsv drop
# those ids' rows and take the new ones (the old reports are kept as *.before-jxl-redo-<n>.tsv);
# scripts/render_v4_jxl_check.py checks the new files into jxl-redo-<n>-check.tsv; RUN.meta
# records the redo: ids, tool commit, Cargo.lock hash, the zen-main commits and the results.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
out="$1"; effort="$2"; jobs="$3"; ids="$4"
for f in jxl-report.tsv list.tsv RUN.meta; do
  [ -e "$out/$f" ] || { echo "refusing: no $out/$f (run render_v4_jxl.sh first)" >&2; exit 1; }
done
heavy="${RUN_HEAVY:-$HOME/work/zen/scripts/run-heavy}"
run_heavy() {
  local j="$1" mem="$2"; shift 2
  if [ -x "$heavy" ]; then "$heavy" --jobs "$j" --mem "$mem" -- "$@"; else nice -n 19 "$@"; fi
}
n=1
while [ -e "$out/jxl-redo-$n-report.tsv" ]; do n=$((n + 1)); done
(cd "$repo/tools/render-v4" && run_heavy 16 20G cargo build --release --locked) > "$out/jxl-redo-$n-build.log" 2>&1 \
  || { tail -n 20 "$out/jxl-redo-$n-build.log" >&2; exit 1; }
bin="${CARGO_TARGET_DIR:-$repo/tools/render-v4/target}/release/render-v4"
keep() { awk -F'\t' -v ids="$ids" 'BEGIN { n = split(ids, a, ","); for (i = 1; i <= n; i++) k[a[i]] = 1 } k[$1]' "$@"; }
keep "$out/list.tsv" > "$out/jxl-redo-$n-list.tsv"
[ "$(wc -l < "$out/jxl-redo-$n-list.tsv")" -eq "$(echo "$ids" | tr ',' '\n' | sort -u | wc -l)" ] \
  || { echo "refusing: not every id is in list.tsv" >&2; exit 1; }
status=0
run_heavy "$((jobs * 2))" 40G "$bin" jxl --effort "$effort" --jobs "$jobs" "$out/jxl-redo-$n-list.tsv" "$out" \
  > "$out/jxl-redo-$n-report.tsv" 2> "$out/jxl-redo-$n-progress.log" || status=$?
hdr_ids=""
if [ -e "$out/hdr-report.tsv" ]; then
  hdr_ids=$(awk -F'\t' 'NR > 1 && $NF == "" { print $1 }' "$out/hdr-report.tsv" | keep /dev/stdin | sort -u | paste -sd,)
fi
merge() {  # merge <report> <new rows>: drop the redone ids' rows, add the new ones, sort
  cp "$out/$1" "$out/${1%.tsv}.before-jxl-redo-$n.tsv"
  python3 - "$out/${1%.tsv}.before-jxl-redo-$n.tsv" "$2" "$ids" "$out/$1" <<'EOF'
import sys
old, new, drop, dst = sys.argv[1:]
drop = set(drop.split(","))
rows = open(old).read().splitlines()
fresh = open(new).read().splitlines()
if rows[0] != fresh[0]:
    sys.exit("refusing: the report columns changed")
body = [r for r in rows[1:] if r.split("\t")[0] not in drop] + fresh[1:]
body.sort(key=lambda r: (r.split("\t")[0], r.split("\t")[1]))
open(dst, "w").write("\n".join([rows[0]] + body) + "\n")
EOF
}
merge jxl-report.tsv "$out/jxl-redo-$n-report.tsv"
if [ -n "$hdr_ids" ] && [ -e "$out/jxl-hdr-report.tsv" ]; then
  awk -F'\t' -v ids="$hdr_ids" 'BEGIN { n = split(ids, a, ","); for (i = 1; i <= n; i++) k[a[i]] = 1 } k[$1]' \
    "$out/list.tsv" > "$out/jxl-redo-$n-hdr-list.tsv"
  run_heavy "$((jobs * 2))" 40G "$bin" jxl-hdr --effort "$effort" --jobs "$jobs" "$out/jxl-redo-$n-hdr-list.tsv" "$out" \
    > "$out/jxl-redo-$n-hdr-report.tsv" 2>> "$out/jxl-redo-$n-progress.log" || status=$?
  merge jxl-hdr-report.tsv "$out/jxl-redo-$n-hdr-report.tsv"
fi
python3 "$repo/scripts/render_v4_jxl_check.py" "$out" --jobs "$jobs" --ids "$ids" \
  --out "$out/jxl-redo-$n-check.tsv" > "$out/jxl-redo-$n-check.log" 2>&1 || status=$?
tools="tools/render-v4 scripts/render_v4_jxl.sh scripts/render_v4_jxl_redo.sh scripts/render_v4_jxl_check.py"
{
  echo "jxl_redo_${n}_date	$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "jxl_redo_${n}_ids	$ids"
  echo "jxl_redo_${n}_effort	$effort"
  echo "jxl_redo_${n}_tool_commit	$(git -C "$repo" log -1 --format=%H -- $tools)"
  echo "jxl_redo_${n}_tool_dirty	$(git -C "$repo" status --porcelain -- $tools | wc -l)"
  echo "jxl_redo_${n}_render_v4_cargo_lock_sha256	$(sha256sum "$repo/tools/render-v4/Cargo.lock" | cut -d' ' -f1)"
  sed "s/^/jxl_redo_${n}_zen_main_/" "$repo/tools/corpus-thumbs/zen-main/COMMITS.tsv"
  grep -E '^run-heavy: done' "$out/jxl-redo-$n-progress.log" | sed "s/^/jxl_redo_${n}_run_heavy	/" || true
  tail -n 1 "$out/jxl-redo-$n-check.log" | sed "s/^/jxl_redo_${n}_check	/"
  echo "jxl_redo_${n}_exit	$status"
} >> "$out/RUN.meta"
exit "$status"
