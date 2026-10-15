#!/usr/bin/env bash
# Render the v4 SDR PNG layers of every manifest image (EXPORT-PLAN.md, "Render v4").
#
#   scripts/render_v4_run.sh <originals-dir> <out-dir> [jobs] [--ids 1044,1214]
#
# Writes <out-dir>/png-p3/…, <out-dir>/png-srgb/…, and beside them:
#   build.log     the render-v4 build
#   list.tsv      render-v4's input (scripts/render_v4_list.py)
#   report.tsv    one row per written file (render-v4's report), sorted by id and layer
#   progress.log  render-v4's per-file progress
#   oracle.log    scripts/colour_oracle.py over every wide-gamut png-srgb file
#   RUN.meta      the imazen-26 commit, the crate commits (render-v4's Cargo.lock and
#                 tools/corpus-thumbs/zen-main/COMMITS.tsv), host, date and command
# Run tools/corpus-thumbs/sync-main.sh first to take the newest zencodec and ultrahdr mains.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
originals="$1"; out="$2"; jobs="${3:-8}"; shift $(( $# >= 3 ? 3 : $# ))
mkdir -p "$out"
if [ -e "$out/report.tsv" ]; then
  echo "refusing: $out/report.tsv exists" >&2
  exit 1
fi
# run-heavy (niced, memory-capped, logs peak RSS) where it exists; plain nice elsewhere.
heavy="${RUN_HEAVY:-$HOME/work/zen/scripts/run-heavy}"
run_heavy() {
  local jobs="$1" mem="$2"; shift 2
  if [ -x "$heavy" ]; then "$heavy" --jobs "$jobs" --mem "$mem" -- "$@"; else nice -n 19 "$@"; fi
}
(cd "$repo/tools/render-v4" && run_heavy 16 20G cargo build --release --locked) > "$out/build.log" 2>&1 \
  || { tail -n 20 "$out/build.log" >&2; exit 1; }
bin="${CARGO_TARGET_DIR:-$repo/tools/render-v4/target}/release/render-v4"
python3 "$repo/scripts/render_v4_list.py" "$originals" "$@" > "$out/list.tsv"
{
  echo "date	$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host	$(hostname)"
  tools="tools/render-v4 scripts/render_v4_list.py scripts/render_v4_run.sh scripts/colour_oracle.py"
  echo "tool_commit	$(git -C "$repo" log -1 --format=%H -- $tools)"
  echo "tool_dirty	$(git -C "$repo" status --porcelain -- $tools | wc -l)"
  echo "imazen26_head	$(git -C "$repo" rev-parse HEAD)"
  echo "manifests_sha256	$(cat "$repo"/manifests/{train,validate,test}.tsv | sha256sum | cut -d' ' -f1)"
  echo "render_v4_cargo_lock_sha256	$(sha256sum "$repo/tools/render-v4/Cargo.lock" | cut -d' ' -f1)"
  sed 's/^/zen_main_/' "$repo/tools/corpus-thumbs/zen-main/COMMITS.tsv"
  echo "originals	$originals"
  echo "list_rows	$(wc -l < "$out/list.tsv")"
  echo "command	render-v4 png-sdr --jobs $jobs list.tsv $out"
} > "$out/RUN.meta"
cp "$repo/tools/render-v4/Cargo.lock" "$out/render-v4.Cargo.lock"
status=0
run_heavy "$((jobs * 2))" 40G "$bin" png-sdr --jobs "$jobs" \
  "$out/list.tsv" "$out" > "$out/report.unsorted.tsv" 2> "$out/progress.log" || status=$?
{ head -n 1 "$out/report.unsorted.tsv"; tail -n +2 "$out/report.unsorted.tsv" | sort -t$'\t' -k1,1 -k2,2; } > "$out/report.tsv"
rm "$out/report.unsorted.tsv"
echo "exit	$status" >> "$out/RUN.meta"
grep -E '^run-heavy: done' "$out/progress.log" | sed 's/^/run_heavy	/' >> "$out/RUN.meta" || true
python3 "$repo/scripts/colour_oracle.py" "$out/report.tsv" "$out" "$originals" "$out/list.tsv" \
  > "$out/oracle.log" 2>&1 || status=$?
tail -n 1 "$out/oracle.log" | sed 's/^/oracle	/' >> "$out/RUN.meta"
echo "final_exit	$status" >> "$out/RUN.meta"
exit "$status"
