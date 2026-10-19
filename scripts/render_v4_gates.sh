#!/usr/bin/env bash
# The whole-tree gates of a render v4 output (EXPORT-PLAN.md, "Gates"), run after every pass
# (render_v4_run.sh, any redo, render_v4_hdr.sh, render_v4_jxl.sh) on the same out-dir.
#
#   scripts/render_v4_gates.sh <out-dir> [jobs]
#
# Writes beside the layers:
#   readback.tsv         scripts/render_v4_readback.py: every PNG through Pillow, ImageMagick,
#                        netpbm and pngfix, and its chunk set
#   inventory.tsv        the unconsumed parts of every PNG and JXL file (zencodecs inventory)
#   inventory-gate.log   scripts/inventory_gate.py over it
#   byte-scan-<layer>.tsv  scripts/byte_scan.py over each PNG and JXL layer
# and appends the results to RUN.meta. The JXL read-back gate runs in render_v4_jxl.sh.
# The inventory CLI is zenpipe main; INVENTORY overrides its path.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
out="$1"; jobs="${2:-8}"
inventory="${INVENTORY:-$HOME/work/zen/zenpipe/target/release/zencodecs}"
for f in report.tsv hdr-report.tsv jxl-report.tsv RUN.meta; do
  [ -e "$out/$f" ] || { echo "refusing: no $out/$f (run every pass first)" >&2; exit 1; }
done
[ -x "$inventory" ] || { echo "no inventory CLI at $inventory" >&2; exit 1; }
heavy="${RUN_HEAVY:-$HOME/work/zen/scripts/run-heavy}"
run_heavy() {
  local j="$1" mem="$2"; shift 2
  if [ -x "$heavy" ]; then "$heavy" --jobs "$j" --mem "$mem" -- "$@"; else nice -n 19 "$@"; fi
}
layers=()
for l in png-p3 png-srgb jxl-p3 jxl-srgb; do
  [ -d "$out/$l" ] && layers+=("$out/$l")
done
status=0
run_heavy "$((jobs * 2))" 24G python3 "$repo/scripts/render_v4_readback.py" "$out" --jobs "$jobs" \
  > "$out/readback.log" 2>&1 || status=$?
run_heavy "$((jobs * 2))" 24G "$inventory" inventory --tsv --unconsumed "${layers[@]}" \
  > "$out/inventory.tsv" 2> "$out/inventory.err" || status=$?
python3 "$repo/scripts/inventory_gate.py" "$out/inventory.tsv" > "$out/inventory-gate.log" 2>&1 || status=$?
: > "$out/byte-scan.log"
for l in "${layers[@]}"; do
  name="$(basename "$l")"
  echo "$name: $(run_heavy 4 8G python3 "$repo/scripts/byte_scan.py" "$l" --out "$out/byte-scan-$name.tsv" 2>&1 \
    | grep -v '^run-heavy' | tail -n 1)" >> "$out/byte-scan.log" || status=$?
done
[ "$(grep -c " 0 with findings" "$out/byte-scan.log")" -eq "${#layers[@]}" ] || status=1
tools="scripts/render_v4_gates.sh scripts/render_v4_readback.py scripts/inventory_gate.py scripts/byte_scan.py manifests/inventory_allowlist.tsv manifests/byte_scan_allowlist.tsv"
{
  echo "gates_date	$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "gates_tool_commit	$(git -C "$repo" log -1 --format=%H -- $tools)"
  echo "gates_tool_dirty	$(git -C "$repo" status --porcelain -- $tools | wc -l)"
  echo "gates_inventory_cli_sha256	$(sha256sum "$inventory" | cut -d' ' -f1)"
  grep -E 'files pass;' "$out/readback.log" | tail -n 1 | sed 's/^/gates_readback	/'
  echo "gates_inventory	$(head -n 1 "$out/inventory-gate.log"); $(tail -n 1 "$out/inventory-gate.log")"
  sed 's/^/gates_byte_scan	/' "$out/byte-scan.log"
  echo "gates_exit	$status"
} >> "$out/RUN.meta"
exit "$status"
