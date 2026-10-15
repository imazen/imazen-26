#!/usr/bin/env bash
# Re-render some rows of a finished render_v4_run.sh output, with the current tools.
#
#   scripts/render_v4_redo.sh <originals-dir> <out-dir> <jobs> <export ids, comma-separated>
#
# The list is regenerated (scripts/render_v4_list.py) and may only lose rows relative to
# <out-dir>/list.tsv (say, rows the list now leaves out); any changed or added row is refused.
# The given ids are rendered again into <out-dir>; report.tsv drops the rows of those ids and of
# the removed ones and takes the new rows; list.tsv becomes the regenerated list (the old one is
# kept as list.before-redo-<n>.tsv); the colour oracle checks the new rows; RUN.meta records the
# redo: ids, removed ids, tool commit, Cargo.lock hash, the zen-main commits and the results.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
originals="$1"; out="$2"; jobs="$3"; ids="$4"
for f in report.tsv list.tsv RUN.meta; do
  [ -e "$out/$f" ] || { echo "refusing: no $out/$f" >&2; exit 1; }
done
heavy="${RUN_HEAVY:-$HOME/work/zen/scripts/run-heavy}"
run_heavy() {
  local j="$1" mem="$2"; shift 2
  if [ -x "$heavy" ]; then "$heavy" --jobs "$j" --mem "$mem" -- "$@"; else nice -n 19 "$@"; fi
}
n=1
while [ -e "$out/list.before-redo-$n.tsv" ]; do n=$((n + 1)); done
(cd "$repo/tools/render-v4" && run_heavy 16 20G cargo build --release --locked) > "$out/redo-$n-build.log" 2>&1 \
  || { tail -n 20 "$out/redo-$n-build.log" >&2; exit 1; }
bin="${CARGO_TARGET_DIR:-$repo/tools/render-v4/target}/release/render-v4"
python3 "$repo/scripts/render_v4_list.py" "$originals" > "$out/list.redo-$n.tsv"
removed=$(python3 - "$out/list.tsv" "$out/list.redo-$n.tsv" "$ids" <<'EOF'
import sys
old = {l.split("\t")[0]: l for l in open(sys.argv[1]) if l.strip()}
new = {l.split("\t")[0]: l for l in open(sys.argv[2]) if l.strip()}
changed = [i for i in new if i not in old or old[i] != new[i]]
if changed:
    sys.exit(f"refusing: the regenerated list changes or adds rows: {changed[:10]}")
missing = [i for i in sys.argv[3].split(",") if i not in new]
if missing:
    sys.exit(f"refusing: ids not in the regenerated list: {missing}")
print(",".join(sorted(set(old) - set(new))))
EOF
)
awk -F'\t' -v ids="$ids" 'BEGIN { n = split(ids, a, ","); for (i = 1; i <= n; i++) keep[a[i]] = 1 } keep[$1]' \
  "$out/list.redo-$n.tsv" > "$out/redo-$n-list.tsv"
status=0
run_heavy "$((jobs * 2))" 40G "$bin" png-sdr --jobs "$jobs" \
  "$out/redo-$n-list.tsv" "$out" > "$out/redo-$n-report.tsv" 2> "$out/redo-$n-progress.log" || status=$?
cp "$out/list.tsv" "$out/list.before-redo-$n.tsv"
cp "$out/report.tsv" "$out/report.before-redo-$n.tsv"
python3 - "$out/report.before-redo-$n.tsv" "$out/redo-$n-report.tsv" "$ids,$removed" "$out/report.tsv" <<'EOF'
import sys
old, new, drop, dst = sys.argv[1:]
drop = set(x for x in drop.split(",") if x)
rows = open(old).read().splitlines()
fresh = open(new).read().splitlines()
if rows[0] != fresh[0]:
    sys.exit("refusing: the report columns changed")
body = [r for r in rows[1:] if r.split("\t")[0] not in drop] + fresh[1:]
body.sort(key=lambda r: (r.split("\t")[0], r.split("\t")[1]))
open(dst, "w").write("\n".join([rows[0]] + body) + "\n")
EOF
mv "$out/list.redo-$n.tsv" "$out/list.tsv"
python3 "$repo/scripts/colour_oracle.py" "$out/report.tsv" "$out" "$originals" "$out/list.tsv" --ids "$ids" \
  > "$out/redo-$n-oracle.log" 2>&1 || status=$?
tools="tools/render-v4 scripts/render_v4_list.py scripts/render_v4_run.sh scripts/render_v4_redo.sh scripts/colour_oracle.py"
{
  echo "redo_${n}_date	$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "redo_${n}_ids	$ids"
  echo "redo_${n}_removed	$removed"
  echo "redo_${n}_tool_commit	$(git -C "$repo" log -1 --format=%H -- $tools)"
  echo "redo_${n}_tool_dirty	$(git -C "$repo" status --porcelain -- $tools | wc -l)"
  echo "redo_${n}_render_v4_cargo_lock_sha256	$(sha256sum "$repo/tools/render-v4/Cargo.lock" | cut -d' ' -f1)"
  sed "s/^/redo_${n}_zen_main_/" "$repo/tools/corpus-thumbs/zen-main/COMMITS.tsv"
  grep -E '^run-heavy: done' "$out/redo-$n-progress.log" | sed "s/^/redo_${n}_run_heavy	/" || true
  tail -n 1 "$out/redo-$n-oracle.log" | sed "s/^/redo_${n}_oracle	/"
  echo "redo_${n}_exit	$status"
} >> "$out/RUN.meta"
cp "$repo/tools/render-v4/Cargo.lock" "$out/render-v4.redo-$n.Cargo.lock"
exit "$status"
