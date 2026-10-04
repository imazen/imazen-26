#!/bin/bash
# reps_thumbs.sh <run_dir> — M-6 disk discipline for reps runs.
#
# 1. Records `output_sha` (sha256 of the current full-resolution render)
#    into every ok-status cell JSON that lacks it.
# 2. Replaces every non-zen render PNG with `compat-matrix thumb`
#    (<=1024px long side). The zen/zen-raw columns keep full resolution.
#
# `matrix --check` then verifies: full-res PNGs on disk must hash to the
# recorded output_sha; <=1024px PNGs are thumbnails of the recorded render.
set -u
OUT="${1:?usage: reps_thumbs.sh <run_dir>}"
CM_BIN="${CM_BIN:-$HOME/work/zen/imazen-26--compat-matrix/tools/compat-matrix/target/release/compat-matrix}"

python3 - "$OUT" <<'PY'
import json, hashlib, struct, sys
from pathlib import Path
out = Path(sys.argv[1])

def png_long(p):
    b = p.read_bytes()[:24]
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return 0
    return max(struct.unpack(">II", b[16:24]))

n = 0
for j in sorted(out.glob("*/*.json")):
    p = j.with_suffix(".png")
    if not p.exists():
        continue
    d = json.loads(j.read_text())
    if d.get("status") != "ok":
        continue
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    # output_sha records the FULL-RES render. >1024 on disk = a render:
    # stamp/refresh. <=1024 = already-derived thumb (or a small render):
    # stamp only when missing — never overwrite a full-res record with
    # its own thumbnail's sha.
    fullres = png_long(p) > 1024
    if d.get("output_sha") is None or (fullres and d["output_sha"] != sha):
        d["output_sha"] = sha
        j.write_text(json.dumps(d))
        n += 1
print(f"reps_thumbs: stamped output_sha on {n} cells")
PY

n=0
while IFS= read -r p; do
    case "$p" in */zen/*|*/zen-raw/*) continue;; esac
    # skip files already <=1024 long-side (thumb would be a rewrite anyway,
    # but skip the resample cost — python/PIL-free dim probe via thumb's
    # own no-op is fine, use `file` which reports PNG dims)
    dims=$(file -b "$p" | grep -o '[0-9]* x [0-9]*' | head -1)
    w=${dims%% x*}; h=${dims##* x}
    if [ "${w:-0}" -le 1024 ] && [ "${h:-0}" -le 1024 ]; then continue; fi
    "$CM_BIN" thumb "$p" "$p.__t" && mv "$p.__t" "$p"
    n=$((n+1))
done < <(find "$OUT" -mindepth 2 -maxdepth 2 -name '*.png' | sort)
echo "reps_thumbs: thumbnailed $n renders (zen/zen-raw kept full-res)"

python3 - "$OUT" <<'PY'
import json, hashlib, sys
from pathlib import Path
out = Path(sys.argv[1])
n = 0
# thumb_sha (M-2) binds the bytes that survive on disk — stamped only
# where they differ from the recorded full-res output_sha (a thumbed
# cell). Never-thumbed small renders stay bound by output_sha alone.
for j in sorted(out.glob("*/*.json")):
    p = j.with_suffix(".png")
    if not p.exists():
        continue
    d = json.loads(j.read_text())
    if d.get("status") != "ok" or not d.get("output_sha"):
        continue
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    if sha != d["output_sha"] and d.get("thumb_sha") != sha:
        d["thumb_sha"] = sha
        j.write_text(json.dumps(d))
        n += 1
print(f"reps_thumbs: stamped thumb_sha on {n} thumbed cells")
PY
