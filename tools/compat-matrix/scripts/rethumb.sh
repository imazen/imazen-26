#!/bin/bash
# rethumb.sh <run_dir> — re-derive every retained cell render's thumbnail
# and restamp `thumb_sha` in its json sidecar.
#
# Why this exists (r13 L-6 provenance): the matrix's thumbnail path once
# wrote bare pixels — thumbnails that dropped the full-res render's
# colour chunks mis-scored the tagged column's evidence chain. `thumb`
# now carries the colour chunks (iCCP/cICP/sRGB/gAMA/cHRM), so this script
# only re-encodes cells whose on-disk PNG predates that or whose
# `thumb_sha` no longer matches the bytes.
#
# A cell's `<id>.png` is the retained render: the full-resolution decode
# when `output_sha` matches it, or the published thumbnail once
# `thumb_sha` does. Re-thumbing an already-thumbed PNG is a safe no-op
# (thumb is idempotent below its max side); the stamp is refreshed either
# way. Cells whose recorded `output_sha` names a render that is no longer
# on disk (the r13 reps run re-decoded those through docker because
# pillow-best is not byte-deterministic — the deployed thumbs are
# pixel-identical to `output_sha`'s render but not byte-derived from it)
# keep both stamps; that provenance note lives in the run pointers.
set -u
OUT="${1:?run dir}"
TOOL="$(cd "$(dirname "$0")/.." && pwd)"
CM="${CM_BIN:-$TOOL/target/release/compat-matrix}"
[ -x "$CM" ] || { echo "no compat-matrix binary at $CM" >&2; exit 1; }

find "$OUT" -mindepth 2 -maxdepth 2 -name '*.json' | while read -r j; do
    png="${j%.json}.png"
    [ -f "$png" ] || continue
    case "$j" in */census/*|*/probe/*) continue;; esac
    ok=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status"))' "$j" 2>/dev/null)
    [ "$ok" = "ok" ] || continue
    want=$(python3 -c 'import json,sys,hashlib;
d=json.load(open(sys.argv[1])); p=sys.argv[2]
disk=hashlib.sha256(open(p,"rb").read()).hexdigest()
print("fresh" if disk in (d.get("output_sha"), d.get("thumb_sha")) else "rethumb")' "$j" "$png")
    [ "$want" = "rethumb" ] || continue
    # Re-encode the retained PNG through the tool's thumb path (colour
    # chunks copied) and restamp.
    if "$CM" thumb "$png" "$png.t.png" >/dev/null 2>&1 && [ -f "$png.t.png" ]; then
        mv "$png.t.png" "$png"
        python3 - "$j" "$png" <<'PY'
import json, sys, hashlib
j, p = sys.argv[1], sys.argv[2]
d = json.load(open(j))
d["thumb_sha"] = hashlib.sha256(open(p, "rb").read()).hexdigest()
json.dump(d, open(j, "w"))
PY
    else
        rm -f "$png.t.png"
        echo "rethumb: thumb failed for $png" >&2
    fi
done
