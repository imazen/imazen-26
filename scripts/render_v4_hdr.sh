#!/usr/bin/env bash
# The HDR pass of render v4 (EXPORT-PLAN.md, "HDR"): a 16-bit PQ render of every gain-map
# source, written as png-p3/<stem>_<W>x<H>.hdr.png beside its SDR file. Run it after
# scripts/render_v4_run.sh, on the same out-dir.
#
#   scripts/render_v4_hdr.sh <originals-dir> <out-dir> [jobs]
#
# Takes the gain-map sources from <out-dir>/report.tsv and their rows from <out-dir>/list.tsv,
# and writes beside them:
#   hdr-list.tsv       the gain-map rows of list.tsv
#   hdr-info.tsv       render-v4 hdr-info: orientation, gain-map size and placement, parameters
#   hdr-report.tsv     one row per HDR file (render-v4 png-hdr), sorted by id
#   hdr-progress.log   per-file progress
#   hdr-oracle.log     scripts/hdr_oracle.py: every file rebuilt from third-party decodes
# and appends the HDR pass's commits and results to RUN.meta.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
originals="$1"; out="$2"; jobs="${3:-6}"
for f in report.tsv list.tsv RUN.meta; do
  [ -e "$out/$f" ] || { echo "refusing: no $out/$f (run render_v4_run.sh first)" >&2; exit 1; }
done
if [ -e "$out/hdr-report.tsv" ]; then
  echo "refusing: $out/hdr-report.tsv exists" >&2
  exit 1
fi
heavy="${RUN_HEAVY:-$HOME/work/zen/scripts/run-heavy}"
run_heavy() {
  local j="$1" mem="$2"; shift 2
  if [ -x "$heavy" ]; then "$heavy" --jobs "$j" --mem "$mem" -- "$@"; else nice -n 19 "$@"; fi
}
(cd "$repo/tools/render-v4" && run_heavy 16 20G cargo build --release --locked) > "$out/hdr-build.log" 2>&1 \
  || { tail -n 20 "$out/hdr-build.log" >&2; exit 1; }
bin="$repo/tools/render-v4/target/release/render-v4"
awk -F'\t' 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == "gain_map") c = i; next }
            c && $c != "" { print $1 }' "$out/report.tsv" | sort -u > "$out/hdr-ids.txt"
awk -F'\t' 'NR == FNR { keep[$1] = 1; next } keep[$1]' "$out/hdr-ids.txt" "$out/list.tsv" > "$out/hdr-list.tsv"
status=0
run_heavy "$((jobs * 2))" 40G "$bin" hdr-info --jobs "$jobs" "$out/hdr-list.tsv" "$out" \
  > "$out/hdr-info.tsv" 2> "$out/hdr-progress.log" || status=$?
run_heavy "$((jobs * 2))" 40G "$bin" png-hdr --jobs "$jobs" "$out/hdr-list.tsv" "$out" \
  > "$out/hdr-report.unsorted.tsv" 2>> "$out/hdr-progress.log" || status=$?
{ head -n 1 "$out/hdr-report.unsorted.tsv"; tail -n +2 "$out/hdr-report.unsorted.tsv" | sort -t$'\t' -k1,1; } \
  > "$out/hdr-report.tsv"
rm "$out/hdr-report.unsorted.tsv"
python3 "$repo/scripts/hdr_oracle.py" "$out/hdr-report.tsv" "$out" "$out/hdr-list.tsv" "$out/hdr-info.tsv" \
  > "$out/hdr-oracle.log" 2>&1 || status=$?
tools="tools/render-v4 scripts/render_v4_hdr.sh scripts/hdr_oracle.py"
{
  echo "hdr_date	$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hdr_tool_commit	$(git -C "$repo" log -1 --format=%H -- $tools)"
  echo "hdr_tool_dirty	$(git -C "$repo" status --porcelain -- $tools | wc -l)"
  echo "hdr_render_v4_cargo_lock_sha256	$(sha256sum "$repo/tools/render-v4/Cargo.lock" | cut -d' ' -f1)"
  echo "hdr_rows	$(wc -l < "$out/hdr-list.tsv")"
  grep -E '^run-heavy: done' "$out/hdr-progress.log" | sed 's/^/hdr_run_heavy	/' || true
  tail -n 1 "$out/hdr-oracle.log" | sed 's/^/hdr_oracle	/'
  echo "hdr_exit	$status"
} >> "$out/RUN.meta"
exit "$status"
