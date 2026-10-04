#!/bin/bash
# unm_cells.sh <fixtures_dir> <out_dir>
#
# Produces the `.unm` calibration cells (r13 M-2 / r14 M-3): for every
# HEIC rep in the manifest, build the drop-transform + unmanaged remux
# (`probe --remux --drop-transform --unmanaged` — the same bytes the
# `corpus:stored` base renders from, so no reader is its own reference)
# and decode it through the run's own HEIC-capable decoders:
#
#   <out>/zen/<id>.unm.png|.json      probe on the remux
#   <out>/zen-raw/<id>.unm.png|.json  probe --raw on the remux
#   <out>/ffmpeg/<id>.unm.png|.json   ffmpeg's *native* hevc path (docker
#                                   image named by IMAGE — only ffmpeg
#                                   builds with the decoder produce ok
#                                   cells; lts ffmpeg lacks it)
#
# `calibrate` then measures each cell against the rep's `stored`
# (libde265) hypothesis — the honest cross-decoder HEIC render-noise
# bound, uncontaminated by display transforms or colour management.
# `.unm` files sit beside ordinary cells but never become rows: matrix
# iterates manifest ids, and no rep id carries the `.unm` suffix.
set -u
FIXTURES="${1:?fixtures dir}"
OUT="${2:?output dir}"
IMAGE="${IMAGE:-imazen26-compat:latest}"

TOOL="$(cd "$(dirname "$0")/.." && pwd)"
PROBE="$TOOL/target/release/compat-matrix"
[ -x "$PROBE" ] || { echo "build release first: cargo build --release" >&2; exit 1; }
BINSHA=$(sha256sum "$PROBE" | cut -d' ' -f1)
IMGID=$(docker image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null || echo "missing:$IMAGE")
# disk-backed container scratch under ~/tmp — never /tmp (L-a).
CTRTMP=$(mktemp -d "${CM_TMPDIR:-$HOME/tmp}/cm-unm-ctr.XXXXXX")
UNM=$(mktemp -d "${CM_TMPDIR:-$HOME/tmp}/cm-unm-remux.XXXXXX")
trap 'rm -rf "$CTRTMP" "$UNM"' EXIT

stamp() { # <json> <png-or-empty> <fsha> <imgid> <asha>
    python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import json, sys, os, hashlib
j, png, fsha, imgid, asha = sys.argv[1:6]
if not os.path.exists(j):
    sys.exit(0)
d = json.load(open(j))
d['image_id'] = imgid
d['adapter_sha'] = asha
d['fixture_sha'] = fsha
if d.get('status') == 'ok' and png and os.path.exists(png):
    d['output_sha'] = hashlib.sha256(open(png, 'rb').read()).hexdigest()
json.dump(d, open(j, 'w'))
PY
}

tail -n +2 "$FIXTURES/fixtures.tsv" | while IFS=$'\t' read -r id _cls file _rest; do
    case "$file" in *.heic|*.heif) ;; *) continue;; esac
    fsha=$(sha256sum "$FIXTURES/$file" | cut -d' ' -f1)
    remux="$UNM/$id.unm.heic"
    "$PROBE" probe "$FIXTURES/$file" --remux "$remux" --unmanaged --drop-transform \
        >/dev/null 2>&1 || { echo "unm: remux failed for $id" >&2; continue; }
    # zen / zen-raw host cells
    for mode in zen zen-raw; do
        png="$OUT/$mode/$id.unm.png"; json="$OUT/$mode/$id.unm.json"
        mkdir -p "$OUT/$mode"
        rm -f "$png" "$json"
        raw=""; [ "$mode" = "zen-raw" ] && raw="--raw"
        timeout 300 "$PROBE" probe "$remux" "$png" --json "$json" $raw >/dev/null 2>&1 || true
        stamp "$json" "$png" "$fsha" "host" "$BINSHA"
    done
    # ffmpeg via the run's image — native hevc only (no libheif delegate).
    png="$OUT/ffmpeg/$id.unm.png"; json="$OUT/ffmpeg/$id.unm.json"
    mkdir -p "$OUT/ffmpeg"
    rm -f "$png" "$json"
    timeout 300 docker run --rm --network none --read-only \
        -v "$CTRTMP:/tmp" -e HOME=/tmp --user "$(id -u):$(id -g)" \
        --pids-limit 1024 --cpus 4 --memory 4g \
        --entrypoint /usr/bin/nice \
        -v "$UNM:/f:ro" -v "$OUT/ffmpeg:/o" -w /f \
        "$IMAGE" -n 19 /opt/adapters/ffmpeg "$id.unm.heic" "/o/$id.unm.png" "/o/$id.unm.json" \
        >/dev/null 2>&1 || true
    stamp "$json" "$png" "$fsha" "$IMGID" "$(sha256sum "$TOOL/adapters/ffmpeg" | cut -d' ' -f1)"
done
echo "unm cells done -> $OUT/{zen,zen-raw,ffmpeg}/*.unm.*"
