#!/usr/bin/env bash
# Rewrite every JPEG XL file of a finished render_v4_jxl.sh pass (and its redos) into libjxl's box
# order without encoding it again: render-v4 jxl-remux (tools/render-v4/src/remux.rs). The codestreams
# stay byte for byte; render-v4 jxl at the same commit writes the same files (2026-10-17: 431 of 431
# files compared, every kind).
#
#   scripts/render_v4_jxl_remux.sh <out-dir> <jobs>
#
# Moves jxl-p3 and jxl-srgb to <out-dir>/before-box-order/ (unless they are there already) and writes
# the rewritten layers in their place. The pass is recorded as the next JXL redo, for all ids:
# jxl-redo-<n>-report.tsv and jxl-redo-<n>-hdr-report.tsv hold the new files' rows (each old row with
# the new file's size and sha256); jxl-report.tsv and jxl-hdr-report.tsv take them (the old reports
# kept as *.before-jxl-redo-<n>.tsv); scripts/render_v4_jxl_check.py checks every file, its box order
# included, into jxl-redo-<n>-check.tsv; RUN.meta records the pass.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
out="$1"; jobs="$2"
for f in jxl-report.tsv jxl-hdr-report.tsv list.tsv RUN.meta; do
  [ -e "$out/$f" ] || { echo "refusing: no $out/$f (run render_v4_jxl.sh first)" >&2; exit 1; }
done
old="$out/before-box-order"
mkdir -p "$old"
for l in jxl-p3 jxl-srgb; do
  if [ -d "$old/$l" ]; then
    [ ! -e "$out/$l" ] || { echo "refusing: both $out/$l and $old/$l exist" >&2; exit 1; }
  else
    mv "$out/$l" "$old/$l"
  fi
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
ids=$(cut -f1 "$out/list.tsv" | sort -u | paste -sd,)
cp "$out/list.tsv" "$out/jxl-redo-$n-list.tsv"
status=0
run_heavy "$jobs" 16G "$bin" jxl-remux --from "$old" --jobs "$jobs" "$out/jxl-redo-$n-list.tsv" "$out" \
  > "$out/jxl-redo-$n-all.tsv" 2> "$out/jxl-redo-$n-progress.log" || status=$?
# The HDR files' rows go to the HDR report, as render-v4 jxl-hdr writes them.
awk -F'\t' 'NR == 1 || $2 != "jxl-p3-hdr"' "$out/jxl-redo-$n-all.tsv" > "$out/jxl-redo-$n-report.tsv"
awk -F'\t' 'NR == 1 || $2 == "jxl-p3-hdr"' "$out/jxl-redo-$n-all.tsv" > "$out/jxl-redo-$n-hdr-report.tsv"
rm "$out/jxl-redo-$n-all.tsv"
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
kept = [r for r in rows[1:] if r.split("\t")[0] not in drop]
if len(fresh) - 1 != len(rows) - 1 - len(kept):
    sys.exit(f"refusing: {len(fresh) - 1} new rows for {len(rows) - 1 - len(kept)} old ones")
body = kept + fresh[1:]
body.sort(key=lambda r: (r.split("\t")[0], r.split("\t")[1]))
open(dst, "w").write("\n".join([rows[0]] + body) + "\n")
EOF
}
merge jxl-report.tsv "$out/jxl-redo-$n-report.tsv" || status=$?
merge jxl-hdr-report.tsv "$out/jxl-redo-$n-hdr-report.tsv" || status=$?
python3 "$repo/scripts/render_v4_jxl_check.py" "$out" --jobs "$jobs" --ids "$ids" \
  --out "$out/jxl-redo-$n-check.tsv" > "$out/jxl-redo-$n-check.log" 2>&1 || status=$?
tools="tools/render-v4 scripts/render_v4_jxl_remux.sh scripts/render_v4_jxl_check.py"
{
  echo "jxl_redo_${n}_date	$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "jxl_redo_${n}_kind	remux: every file rewritten into libjxl's box order by render-v4 jxl-remux, codestreams kept"
  echo "jxl_redo_${n}_ids	all $(cut -f1 "$out/list.tsv" | sort -u | wc -l) ids of list.tsv"
  echo "jxl_redo_${n}_tool_commit	$(git -C "$repo" log -1 --format=%H -- $tools)"
  echo "jxl_redo_${n}_tool_dirty	$(git -C "$repo" status --porcelain -- $tools | wc -l)"
  echo "jxl_redo_${n}_render_v4_cargo_lock_sha256	$(sha256sum "$repo/tools/render-v4/Cargo.lock" | cut -d' ' -f1)"
  sed "s/^/jxl_redo_${n}_zen_main_/" "$repo/tools/corpus-thumbs/zen-main/COMMITS.tsv"
  grep -E '^run-heavy: done' "$out/jxl-redo-$n-progress.log" | sed "s/^/jxl_redo_${n}_run_heavy	/" || true
  tail -n 1 "$out/jxl-redo-$n-check.log" | sed "s/^/jxl_redo_${n}_check	/"
  echo "jxl_redo_${n}_exit	$status"
} >> "$out/RUN.meta"
exit "$status"
