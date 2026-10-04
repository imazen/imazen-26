#!/bin/bash
# Shared helpers for compat-matrix reader adapters.
# Contract: adapter <in> <out.png> <out.json>
# Every adapter must: produce a PNG on success, always produce JSON,
# never write to stdout except via the JSON file (stdout = diagnostics).

# Adapter dir must NOT be on PATH for tool resolution: several adapter
# scripts share their tool's name (djpeg, dwebp, vips, ...) and would
# recursively exec themselves (fork bomb observed: 45k procs).
ADAPTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -vx "$ADAPTER_DIR" | paste -sd: -)"
# Lock tool resolution to system dirs: adapter scripts share tool names
# (djpeg, vips, ...) — bare names must resolve to absolute system binaries,
# never to sibling adapter scripts.
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

ADAPTER_VERSION="${ADAPTER_VERSION:-unknown}"

# Checkpoint identity: cells are reusable only when both the container image
# (CM_IMAGE_ID, passed by the sweep driver) and this adapter script are the
# same bytes that produced the JSON.
ADAPTER_SHA=$(sha256sum "$0" | cut -d' ' -f1)
CM_IMAGE_ID="${CM_IMAGE_ID:-}"
# sha256 of the fixture bytes under test — driver passes per cell so a cell
# can never be mistaken for output of a different fixture generation.
CM_FIXTURE_SHA="${CM_FIXTURE_SHA:-}"

ms_now() { date +%s%3N; }

# png_dims <file> -> "W H" — reads the 24-byte IHDR prefix via python3
png_dims() {
    python3 - "$1" <<'PY' 2>/dev/null || echo "0 0"
import struct, sys
d = open(sys.argv[1], 'rb').read(33)
if d[:8] != b'\x89PNG\r\n\x1a\n' or d[12:16] != b'IHDR':
    print("0 0"); raise SystemExit
w, h = struct.unpack('>II', d[16:24])
print(w, h)
PY
}

# channel_stats <png> -> '"mean":[..],"std":[..]' json fragment (or empty)
channel_stats() {
    python3 - "$1" <<'PY' 2>/dev/null
import sys, json
import numpy as np
from PIL import Image
a = np.asarray(Image.open(sys.argv[1]).convert('RGB'), dtype=np.float64)
m = a.reshape(-1, 3).mean(0); s = a.reshape(-1, 3).std(0)
print('"mean":' + json.dumps([round(float(x),2) for x in m]) +
      ',"std":' + json.dumps([round(float(x),2) for x in s]))
PY
}

# write_json <status> <out.png> <out.json> <ms> <error_head> [extra_json]
write_json() {
    local status="$1" png="$2" json="$3" ms="$4" err="$5" extra="${6:-}"
    local w=0 h=0 stats=""
    if [ "$status" = "ok" ] && [ -f "$png" ]; then
        read -r w h <<<"$(png_dims "$png")"
        stats=$(channel_stats "$png")
    fi
    err=$(head -c 2000 <<<"$err" | tr '\n' ' ' | sed 's/"/'"'"'/g')
    printf '{"status":"%s","w":%s,"h":%s,"ms":%.2f,"version":"%s","image_id":"%s","adapter_sha":"%s","fixture_sha":"%s","error_head":"%s"%s%s}\n' \
        "$status" "$w" "$h" "$ms" "$ADAPTER_VERSION" "$CM_IMAGE_ID" "$ADAPTER_SHA" "$CM_FIXTURE_SHA" "$err" \
        "${stats:+,$stats}" "${extra:+,$extra}" >"$json"
}

# run_adapter <out.png> <out.json> <cmd...>
# Executes cmd (which must produce $OUT), captures stderr, times it.
run_adapter() {
    local out="$1" json="$2"; shift 2
    local t0 t1 ms err
    t0=$(ms_now)
    if declare -F "$1" >/dev/null; then
        # shell function (pnm_to_png etc.) — timeout can't exec it directly
        err=$(timeout -k 5 90 nice -n 19 bash -c '"$@"' _ "$@" </dev/null 2>&1)
    else
        err=$(timeout -k 5 90 nice -n 19 "$@" </dev/null 2>&1)
    fi
    local rc=$?
    t1=$(ms_now); ms=$((t1 - t0))
    # complete stderr preserved beside the json — the TSV head is bounded but
    # diagnostics are never truncated to 480B.
    [ -n "$err" ] && printf '%s' "$err" >"$json.stderr"
    if [ $rc -eq 0 ] && [ -f "$out" ] && [ -s "$out" ]; then
        write_json ok "$out" "$json" "$ms" ""
    elif [ $rc -eq 124 ] || [ $rc -eq 137 ]; then
        rm -f "$out"
        write_json timeout "$out" "$json" "$ms" "killed after 90s: $err"
    else
        rm -f "$out"
        write_json error "$out" "$json" "$ms" "rc=$rc $err"
    fi
}

# pnm_to_png <in-pnm-file> <out-png>: netpbm conversion
pnm_to_png() { pnmtopng "$1" >"$2" 2>/dev/null || anytopnm_fallback "$1" "$2"; }
anytopnm_fallback() {
    # last resort: pillow (present in the image) converts any PNM/TIFF/BMP
    python3 - "$1" "$2" <<'PY'
import sys
from PIL import Image
Image.open(sys.argv[1]).save(sys.argv[2])
PY
}
export -f pnm_to_png anytopnm_fallback 2>/dev/null || true
