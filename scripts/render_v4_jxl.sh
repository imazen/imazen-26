#!/usr/bin/env bash
# The JPEG XL pass of render v4 (EXPORT-PLAN.md, "JPEG XL"): jxl-p3 and jxl-srgb beside the PNG
# layers. Run it after scripts/render_v4_run.sh (and any redo), on the same out-dir.
#
#   scripts/render_v4_jxl.sh <out-dir> <effort> [jobs]
#
# Renders every row of <out-dir>/list.tsv and writes beside them:
#   jxl-report.tsv     one row per JXL file (render-v4 jxl), sorted by id and layer
#   jxl-progress.log   per-file progress
#   jxl-check.tsv      scripts/render_v4_jxl_check.py: twins, colour and libjxl read-back
# and appends the JXL pass's commits and results to RUN.meta.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
out="$1"; effort="$2"; jobs="${3:-8}"
for f in report.tsv list.tsv RUN.meta; do
  [ -e "$out/$f" ] || { echo "refusing: no $out/$f (run render_v4_run.sh first)" >&2; exit 1; }
done
if [ -e "$out/jxl-report.tsv" ]; then
  echo "refusing: $out/jxl-report.tsv exists" >&2
  exit 1
fi
heavy="${RUN_HEAVY:-$HOME/work/zen/scripts/run-heavy}"
run_heavy() {
  local j="$1" mem="$2"; shift 2
  if [ -x "$heavy" ]; then "$heavy" --jobs "$j" --mem "$mem" -- "$@"; else nice -n 19 "$@"; fi
}
(cd "$repo/tools/render-v4" && run_heavy 16 20G cargo build --release --locked) > "$out/jxl-build.log" 2>&1 \
  || { tail -n 20 "$out/jxl-build.log" >&2; exit 1; }
bin="${CARGO_TARGET_DIR:-$repo/tools/render-v4/target}/release/render-v4"
status=0
run_heavy "$((jobs * 2))" 40G "$bin" jxl --effort "$effort" --jobs "$jobs" "$out/list.tsv" "$out" \
  > "$out/jxl-report.unsorted.tsv" 2> "$out/jxl-progress.log" || status=$?
{ head -n 1 "$out/jxl-report.unsorted.tsv"; tail -n +2 "$out/jxl-report.unsorted.tsv" | sort -t$'\t' -k1,1 -k2,2; } \
  > "$out/jxl-report.tsv"
rm "$out/jxl-report.unsorted.tsv"
python3 "$repo/scripts/render_v4_jxl_check.py" "$out" --jobs "$jobs" > "$out/jxl-check.log" 2>&1 || status=$?
tools="tools/render-v4 scripts/render_v4_jxl.sh scripts/render_v4_jxl_check.py"
{
  echo "jxl_date	$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "jxl_effort	$effort"
  echo "jxl_tool_commit	$(git -C "$repo" log -1 --format=%H -- $tools)"
  echo "jxl_tool_dirty	$(git -C "$repo" status --porcelain -- $tools | wc -l)"
  echo "jxl_render_v4_cargo_lock_sha256	$(sha256sum "$repo/tools/render-v4/Cargo.lock" | cut -d' ' -f1)"
  sed 's/^/jxl_zen_main_/' "$repo/tools/corpus-thumbs/zen-main/COMMITS.tsv"
  grep -E '^run-heavy: done' "$out/jxl-progress.log" | sed 's/^/jxl_run_heavy	/' || true
  tail -n 1 "$out/jxl-check.log" | sed 's/^/jxl_check	/'
  echo "jxl_exit	$status"
} >> "$out/RUN.meta"
exit "$status"
