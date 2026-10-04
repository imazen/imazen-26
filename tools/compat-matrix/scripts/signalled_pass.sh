#!/bin/bash
# signalled_pass.sh <corpus_dir> <out_dir> [--jobs N]
# Header-level signalled-orientation census: `probe --meta` parses the
# container header only (~0.1 ms/file) and reports the tag as signalled —
# no bake. Writes <out>/<basename>.json + <out>/signalled.tsv. This is the
# pass that produced census/signalled/ (207 rotated files); the census
# decode pass reports post-bake orientation instead.
set -u
CORPUS="${1:?corpus dir}"
OUT="${2:?out dir}"
JOBS=4
[ "${3:-}" = "--jobs" ] && JOBS="${4:-4}"
TOOL="$(cd "$(dirname "$0")/.." && pwd)"
PROBE="$TOOL/target/release/compat-matrix"
[ -x "$PROBE" ] || { echo "build release first" >&2; exit 1; }
mkdir -p "$OUT"
TSV="$OUT/signalled.tsv"

export PROBE OUT
BINSHA=$(sha256sum "$PROBE" | cut -d' ' -f1)
export BINSHA
meta_one() {
    f="$1"; base="$(basename "$f")"; json="$OUT/$base.json"
    fsha=$(sha256sum "$f" | cut -d' ' -f1)
    # checkpoint reuse only when producer + input provenance match
    if [ -f "$json" ] && python3 -c "
import json,sys
d=json.load(open('$json'))
sys.exit(0 if d.get('image_id')=='host' and d.get('adapter_sha')=='$BINSHA'
         and d.get('fixture_sha')=='$fsha' else 1)" 2>/dev/null; then return 0; fi
    timeout 30 "$PROBE" probe "$f" "$OUT/$base.png" --meta --json "$json" >/dev/null 2>&1 || true
    rm -f "$OUT/$base.png"   # meta mode writes no pixels anyway
    [ -f "$json" ] && python3 -c "
import json
d=json.load(open('$json'))
d['image_id']='host'; d['adapter_sha']='$BINSHA'; d['fixture_sha']='$fsha'
json.dump(d,open('$json','w'))"
}
export -f meta_one

find "$CORPUS" -type f | sort | nice -n 19 xargs -d '\n' -P "$JOBS" -n 1 -I{} bash -c 'meta_one "$1"' _ {}

python3 - "$OUT" "$TSV" <<'PYEOF'
import glob, json, os, sys
out, tsv = sys.argv[1], sys.argv[2]
os.chdir(out)
rows = ["file\torientation\tw\th\tsource_color\tstatus"]
for p in sorted(glob.glob('*.json')):
    try:
        d = json.load(open(p))
    except Exception:
        rows.append(f"{p[:-5]}\t\t0\t0\t\tno-json")
        continue
    rows.append('\t'.join(map(str, [p[:-5], d.get('orientation_reported', ''),
        d.get('w', 0), d.get('h', 0),
        str(d.get('source_color', '')).replace('\t', ' ')[:80],
        d.get('status', '')])))
open(tsv, 'w').write('\n'.join(rows) + '\n')
non1 = [r for r in rows[1:] if r.split('\t')[1] not in ('', '1')]
print(f"{len(rows)-1} files, {len(non1)} signalled orientation != 1 -> {tsv}")
PYEOF
