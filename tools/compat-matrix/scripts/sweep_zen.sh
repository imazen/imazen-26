#!/bin/bash
# sweep_zen.sh <fixtures_dir> <out_dir>
# Native zen-reader sweep — the `zen`/`zen-raw` matrix columns no docker
# image can provide. Emits the adapter contract per fixture:
#   <out>/zen/<id>.png + .json     viewer semantics (probe)
#   <out>/zen-raw/<id>.png + .json stored semantics (probe --raw)
# Appends rows to <out>/decode.tsv like run_matrix.sh does.
set -u
FIXTURES="${1:?fixtures dir}"
OUT="${2:?output dir}"
TOOL="$(cd "$(dirname "$0")/.." && pwd)"
PROBE="$TOOL/target/release/compat-matrix"
[ -x "$PROBE" ] || { echo "build release first: cargo build --release" >&2; exit 1; }

mkdir -p "$OUT/zen" "$OUT/zen-raw"
TSV="$OUT/decode.tsv"
[ -f "$TSV" ] || printf 'adapter\tfixture\tstatus\tw\th\tms\tversion\terror\n' > "$TSV"

VER=$("$PROBE" probe --version 2>/dev/null || echo "compat-matrix $(cd "$TOOL" && git rev-parse --short HEAD 2>/dev/null || echo local)")
# Provenance parity with docker cells: the probe binary IS the adapter
# (adapter_sha = binary sha256) and there is no image (image_id = "host").
BINSHA=$(sha256sum "$PROBE" | cut -d' ' -f1)

# L-1: host cells are admissible only when the run's platform block lists
# the producing adapter with this sha — bare `adapter=` lines (no `#`
# header) extend the last run_matrix block, which is the record `matrix`
# checks against.
# r13 L-2: `host_adapter=` is the positive marker `matrix` requires for
# image_id=host cells — a host cell on an adapter not listed here (or
# listed as container_adapter) is refused.
if [ -f "$OUT/platform.txt" ]; then
    # `matrix` reads only the LAST `# ` block as authoritative — markers
    # must land there, so the guards test that tail block, not the file
    # (a later run_matrix append would otherwise shadow them).
    last_block() { awk '/^# /{buf=""} {buf=buf $0 "\n"} END{printf "%s", buf}' "$OUT/platform.txt"; }
    last_block | grep -q "^adapter=zen sha256=$BINSHA\$" \
        || printf 'adapter=zen sha256=%s\nadapter=zen-raw sha256=%s\n' "$BINSHA" "$BINSHA" >> "$OUT/platform.txt"
    # host_adapter markers are idempotent — add even when adapter= lines
    # already exist (r12 platform files predate the positive rule).
    last_block | grep -q "^host_adapter=zen\$" \
        || printf 'host_adapter=zen\nhost_adapter=zen-raw\n' >> "$OUT/platform.txt"
fi

tail -n +2 "$FIXTURES/fixtures.tsv" | while IFS=$'\t' read -r id class file rest; do
    [ -n "${ONLY:-}" ] && [[ ! "$id" =~ $ONLY ]] && continue
    fsha=$(sha256sum "$FIXTURES/$file" | cut -d' ' -f1)
    for mode in zen zen-raw; do
        png="$OUT/$mode/$id.png"; json="$OUT/$mode/$id.json"
        # checkpoint reuse only when provenance matches this fixture+binary
        if [ -f "$json" ] && python3 -c "
import json,sys
d=json.load(open('$json'))
sys.exit(0 if d.get('image_id')=='host' and d.get('adapter_sha')=='$BINSHA'
         and d.get('fixture_sha')=='$fsha' else 1)" 2>/dev/null; then continue; fi
        rm -f "$png" "$json"
        raw=""; [ "$mode" = "zen-raw" ] && raw="--raw"
        timeout 120 "$PROBE" probe "$FIXTURES/$file" "$png" --json "$json" $raw >/dev/null 2>&1 || true
        if [ ! -f "$json" ]; then
            printf '{"status":"crash","w":0,"h":0,"ms":0,"version":"%s","error_head":"probe produced no json"}' "$VER" > "$json"
        fi
        python3 -c "
import json
p='$json'; d=json.load(open(p))
d['image_id']='host'; d['adapter_sha']='$BINSHA'; d['fixture_sha']='$fsha'
import os
if d.get('status')=='ok' and os.path.exists('$png'):
    import hashlib
    d['output_sha']=hashlib.sha256(open('$png','rb').read()).hexdigest()
json.dump(d, open(p,'w'))"
        python3 -c "
import json,sys
d=json.load(open('$json'))
print('$mode','$id',d['status'],d['w'],d['h'],d['ms'],
      d.get('version','').replace(chr(9),' ')[:60],
      d.get('error_head','').replace(chr(9),' ')[:120], sep='\t')
" >> "$TSV"
    done
done
echo "zen sweep done -> $OUT/{zen,zen-raw}"
