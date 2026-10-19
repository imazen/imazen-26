#!/usr/bin/env bash
# Decode every file of a render v4 output with independent decoders and hash each decoded
# bitmap (EXPORT-PLAN.md, "Gates"); read every jhgm gain map back with each JPEG XL decoder.
#
#   scripts/render_v4_decode_check.sh <out-dir> [jobs]
#
# tools/jxl-decode-check decodes with zenpng, zenjxl and jxl-rs; its libjxl leg
# (tools/jxl-decode-check/libjxl) links the libjxl build at LIBJXL_BUILD (default
# ~/tmp/libjxl-v012-build; recipe in tools/jxl-decode-check/README.md). Writes under
# <out-dir>/decode-check/:
#   png.tsv          zenpng: every PNG of png-p3 and png-srgb, and every gain-maps/ PNG
#   jxl.tsv          zenjxl and jxl-rs: every JPEG XL file of jxl-p3 and jxl-srgb
#   jxl-libjxl.tsv   libjxl: the same files
#   gm/<decoder>/    each decoder's jhgm gain map (PGM) and ISO 21496-1 metadata
#   hdr.tsv          zenjxl's HDR reconstruction of each jhgm file against its 16-bit PQ render
#   report.tsv, gain-maps.tsv, summary.txt   scripts/render_v4_decode_report.py over them
# and <out-dir>/decoded-xxh3.tsv (every decoded bitmap's XXH3, one row per file and decoder),
# then appends the results to RUN.meta.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
out="$1"; jobs="${2:-8}"
libjxl="${LIBJXL_BUILD:-$HOME/tmp/libjxl-v012-build}"
for f in manifests/png-p3.tsv manifests/jxl-p3.tsv gain-maps-report.tsv hdr-report.tsv RUN.meta; do
  [ -e "$out/$f" ] || { echo "refusing: no $out/$f (run every pass and export_manifests.py first)" >&2; exit 1; }
done
[ -x "$libjxl/tools/djxl" ] || { echo "no libjxl build at $libjxl" >&2; exit 1; }
heavy="${RUN_HEAVY:-$HOME/work/zen/scripts/run-heavy}"
run_heavy() {
  local j="$1" mem="$2"; shift 2
  if [ -x "$heavy" ]; then "$heavy" --jobs "$j" --mem "$mem" -- "$@"; else nice -n 19 "$@"; fi
}
tool="$repo/tools/jxl-decode-check"
dc="$out/decode-check"
mkdir "$dc"
export TMPDIR="${TMPDIR:-$HOME/tmp}"
if [ -z "${DECODE_CHECK_BIN:-}" ]; then
  (cd "$tool" && run_heavy 8 20G cargo build --release --locked) > "$dc/build.log" 2>&1 \
    || { tail -n 20 "$dc/build.log" >&2; exit 1; }
fi
make -s -C "$tool/libjxl" LIBJXL_BUILD="$libjxl" >> "$dc/build.log" 2>&1 \
  || { tail -n 20 "$dc/build.log" >&2; exit 1; }
bin="${DECODE_CHECK_BIN:-$tool/target/release/jxl-decode-check}"
lock="${DECODE_CHECK_LOCK:-$tool/Cargo.lock}"
[ -x "$bin" ] && [ -f "$lock" ] || { echo "missing decoder binary or source lock" >&2; exit 1; }
lib="$tool/libjxl/libjxl_hash"
# The layers' files, from the manifests (paths are relative to the out-dir).
python3 - "$out" > "$dc/files.tsv" <<'EOF'
import csv, sys, os
out = sys.argv[1]
for layer in ("png-p3", "png-srgb", "jxl-p3", "jxl-srgb"):
    for r in csv.DictReader(open(os.path.join(out, "manifests", f"{layer}.tsv")), delimiter="\t"):
        print(f"{layer}\t{r['path']}")  # the path starts with the layer
for r in csv.DictReader(open(os.path.join(out, "gain-maps-report.tsv")), delimiter="\t"):
    if r["path"]:
        print(f"gain-maps\t{r['path']}")
EOF
awk -F'\t' -v o="$out" '$1 !~ /^jxl/ {print o "/" $2}' "$dc/files.tsv" > "$dc/png.list"
awk -F'\t' -v o="$out" '$1 ~ /^jxl/ {print o "/" $2}' "$dc/files.tsv" > "$dc/jxl.list"
status=0
# A new decode-check directory preserves all earlier dumps and reports.
run_heavy "$((jobs * 2))" 24G "$bin" png --jobs "$jobs" < "$dc/png.list" > "$dc/png.tsv" 2> "$dc/png.log" || status=$?
run_heavy "$((jobs * 2))" 24G "$bin" jxl --jobs "$jobs" --gainmap-dir "$dc/gm" < "$dc/jxl.list" \
  > "$dc/jxl.tsv" 2> "$dc/jxl.log" || status=$?
# libjxl: one single-threaded process per slice of the list.
mkdir -p "$dc/gm/libjxl" "$dc/libjxl-parts"
split -n "r/$jobs" -d "$dc/jxl.list" "$dc/libjxl-parts/part-"
run_heavy "$((jobs * 2))" 24G bash -c '
  pids=""
  for p in "$1"/libjxl-parts/part-*; do
    "$2" --gainmap-dir "$1/gm/libjxl" < "$p" > "$p.tsv" 2> "$p.log" &
    pids="$pids $!"
  done
  status=0
  for pid in $pids; do wait "$pid" || status=$?; done
  exit "$status"' _ "$dc" "$lib" > "$dc/libjxl.log" 2>&1 || status=$?
{ head -n 1 "$(ls "$dc"/libjxl-parts/part-*.tsv | head -n 1)"; for f in "$dc"/libjxl-parts/part-*.tsv; do tail -n +2 "$f"; done; } \
  > "$dc/jxl-libjxl.tsv"
# Keep per-process tables and logs as verification evidence.
# zenjxl's HDR reconstruction of each jhgm file against the PQ render of the same id.
python3 - "$out" > "$dc/hdr-pairs.tsv" <<'EOF'
import csv, sys, os
out = sys.argv[1]
hdr = {r["id"]: r["path"] for r in csv.DictReader(open(os.path.join(out, "manifests", "png-p3.tsv")), delimiter="\t")
       if r["form"] == "hdr-pq"}
for r in csv.DictReader(open(os.path.join(out, "manifests", "jxl-p3.tsv")), delimiter="\t"):
    if r["form"].endswith("+jhgm"):
        print(f"{out}/{r['path']}\t{out}/{hdr[r['id']]}")
EOF
run_heavy "$((jobs * 2))" 24G "$bin" hdr --jobs "$jobs" < "$dc/hdr-pairs.tsv" > "$dc/hdr.tsv" 2> "$dc/hdr.log" || status=$?
python3 "$repo/scripts/render_v4_decode_report.py" "$out" > "$dc/summary.txt" 2>&1 || status=$?
tools="tools/jxl-decode-check scripts/render_v4_decode_check.sh scripts/render_v4_decode_report.py"
{
  echo "decode_check_date	$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "decode_check_tool_commit	$(git -C "$repo" log -1 --format=%H -- $tools)"
  echo "decode_check_tool_dirty	$(git -C "$repo" status --porcelain -- $tools | wc -l)"
  echo "decode_check_binary_sha256	$(sha256sum "$bin" | cut -d' ' -f1)"
  echo "decode_check_cargo_lock_sha256	$(sha256sum "$lock" | cut -d' ' -f1)"
  echo "decode_check_jxl_rs	$(awk '/^name = "jxl"$/ {getline; print; exit}' "$lock" | cut -d'"' -f2)"
  echo "decode_check_libjxl	$("$libjxl/tools/djxl" --version 2>&1 | head -n 1)"
  grep -h -E '^run-heavy: done' "$dc"/png.log "$dc"/jxl.log "$dc"/libjxl.log "$dc"/hdr.log | sed 's/^/decode_check_run_heavy	/' || true
  sed 's/^/decode_check_summary	/' "$dc/summary.txt"
  echo "decode_check_exit	$status"
} >> "$out/RUN.meta"
exit "$status"
