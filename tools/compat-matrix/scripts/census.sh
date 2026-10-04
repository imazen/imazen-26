#!/bin/bash
# census.sh <corpus_dir> <out_dir> [--jobs N]
# Decodes every corpus file through the reader set:
#   zen-reader (local binary), format reference decoder, vips, imagemagick,
#   pillow, chromium (jpeg/png only).
# Per (reader,file): <out>/<reader>/<basename>.png + .json; census.tsv grows
# incrementally. Re-running skips completed (reader,file) pairs.
# NOTE: zen-reader JSONs' orientation_reported is post-bake (the decode
# applies then reports 1). The file's *signalled* orientation lives in
# <out>/signalled/<basename>.json (probe --meta, header-level) aggregated
# to signalled.tsv — 207 rotated files, not the 3 the post-bake field shows.
set -u
CORPUS="${1:?corpus dir}"
OUT="${2:?out dir}"
JOBS=4
[ "${3:-}" = "--jobs" ] && JOBS="${4:-4}"

TOOL="$(cd "$(dirname "$0")/.." && pwd)"
PROBE="$TOOL/target/release/compat-matrix"
IMAGE_LTS=imazen26-compat:lts
IMAGE_BW=imazen26-compat:browsers
# M-3: every cell carries its producer identity — docker cells get
# CM_IMAGE_ID (lib.sh stamps image_id/adapter_sha), zen-reader cells get the
# probe binary sha256 stamped as image_id="host" + adapter_sha=binsha.
LTS_ID=$(docker image inspect -f '{{.Id}}' "$IMAGE_LTS" 2>/dev/null || echo "missing")
BW_ID=$(docker image inspect -f '{{.Id}}' "$IMAGE_BW" 2>/dev/null || echo "missing")
BINSHA=$(sha256sum "$PROBE" | cut -d' ' -f1)
# L-a: disk-backed container /tmp — one scratch dir per run under ~/tmp,
# bind-mounted over /tmp (no tmpfs).
CTRTMP=$(mktemp -d "${CM_TMPDIR:-$HOME/tmp}/cm-census-ctr.XXXXXX")
trap 'rm -rf "$CTRTMP"' EXIT
mkdir -p "$OUT"
TSV="$OUT/census.tsv"
[ -f "$TSV" ] || printf 'file\treader\tstatus\tw\th\tms\tmean_r\tmean_g\tmean_b\tstd_r\tstd_g\tstd_b\tversion\terror\n' > "$TSV"

export TOOL PROBE OUT TSV IMAGE_LTS IMAGE_BW LTS_ID BW_ID BINSHA CTRTMP

# one job: reader<TAB>absolute file path
run_one() {
    reader="$1"; f="$2"
    base="$(basename "$f")"
    png="$OUT/$reader/$base.png"; json="$OUT/$reader/$base.json"
    # checkpoint valid only if it was written by this producer identity
    # (image id for docker readers, binary sha for zen-reader)
    if [ -f "$json" ]; then
        want="$LTS_ID"
        [ "$reader" = zen-reader ] && want="host:$BINSHA"
        [ "$reader" = browser ] && want="$BW_ID"
        got=$(python3 -c "import json;d=json.load(open('$json'));print((d.get('image_id') or '')+(':'+d.get('adapter_sha','') if d.get('image_id')=='host' else ''))" 2>/dev/null)
        [ "$got" = "$want" ] && return 0
    fi
    mkdir -p "$OUT/$reader"
    fsha=$(sha256sum "$f" | cut -d' ' -f1)
    case "$reader" in
        zen-reader)
            timeout 300 "$PROBE" probe "$f" "$png" --json "$json" >/dev/null 2>&1 || true
            [ -f "$json" ] && python3 - "$json" "$BINSHA" "$f" <<'PY2'
import json,sys,hashlib
p,bs,src=sys.argv[1],sys.argv[2],sys.argv[3]
d=json.load(open(p))
d['image_id']='host'; d['adapter_sha']=bs
d['fixture_sha']=hashlib.sha256(open(src,'rb').read()).hexdigest()
json.dump(d,open(p,'w'))
PY2
            ;;
        browser)
            timeout 180 docker run --rm --network none --read-only -v "$CTRTMP:/tmp" -e HOME=/tmp --user "$(id -u):$(id -g)" -e CM_IMAGE_ID="$BW_ID" -e CM_FIXTURE_SHA="$fsha" --pids-limit 1024 --cpus 4 --memory 4g --entrypoint /usr/bin/nice \
                -v "$(dirname "$f"):/f:ro" -v "$OUT/$reader:/o" -w /f \
                "$IMAGE_BW" -n 19 /opt/adapters/browser "$base" "/o/$base.png" "/o/$base.json" chromium >/dev/null 2>&1 || true
            ;;
        *)
            timeout 300 docker run --rm --network none --read-only -v "$CTRTMP:/tmp" -e HOME=/tmp --user "$(id -u):$(id -g)" -e CM_IMAGE_ID="$LTS_ID" -e CM_FIXTURE_SHA="$fsha" --pids-limit 1024 --cpus 4 --memory 4g --entrypoint /usr/bin/nice \
                -v "$(dirname "$f"):/f:ro" -v "$OUT/$reader:/o" -w /f \
                "$IMAGE_LTS" -n 19 "/opt/adapters/$reader" "$base" "/o/$base.png" "/o/$base.json" >/dev/null 2>&1 || true
            ;;
    esac
    # renders budget: keep only the zen-reader render per file (canonical +
    # contact-sheet evidence); other readers' data lives in their JSON stats.
    if [ -f "$png" ]; then
        if [ "$reader" = "zen-reader" ]; then
            # <=1024px long side via the committed thumb path (zenresize +
            # zenpng — no third-party writer).
            "$PROBE" thumb "$png" "$png.t.png" >/dev/null 2>&1 \
                && mv "$png.t.png" "$png" || rm -f "$png"
        else
            rm -f "$png"
        fi
    fi
    if [ -f "$json" ]; then
        python3 -c "
import json
d=json.load(open('$json'))
m=d.get('mean',[0,0,0]); s=d.get('std',[0,0,0])
print('$base','$reader',d['status'],d['w'],d['h'],d['ms'],
      *m[:3],*s[:3],
      str(d.get('version','')).replace(chr(9),' ')[:50],
      str(d.get('error_head','')).replace(chr(9),' ')[:120], sep='\t', flush=True)
" >> "$TSV" 2>/dev/null || printf '%s\t%s\tjson-parse\t0\t0\t0\t0\t0\t0\t0\t0\t0\t\t\n' "$base" "$reader" >> "$TSV"
    else
        printf '%s\t%s\tcrash\t0\t0\t0\t0\t0\t0\t0\t0\t0\t\tno json\n' "$base" "$reader" >> "$TSV"
    fi
}
export -f run_one

# build job list
find "$CORPUS" -type f | sort | while read -r f; do
    ext="${f##*.}"; ext=$(tr 'A-Z' 'a-z' <<<"$ext")
    case "$ext" in
        jpg|jpeg) ref=djpeg;;
        png)      ref=pngtopam;;
        heic|heif) ref=heif-dec;;
        dng|nef|cr2|cr3|arw|orf|rw2|raf) ref=dcraw_emu;;
        *)        continue;;   # manifests, scripts, etc. are not corpus images
    esac
    printf 'zen-reader\t%s\n' "$f"
    printf '%s\t%s\n' "$ref" "$f"
    printf 'vips\t%s\nimagemagick\t%s\npillow\t%s\n' "$f" "$f" "$f"
    case "$ext" in jpg|jpeg|png) printf 'browser\t%s\n' "$f";; esac
done | nice -n 19 xargs -d '\n' -P "$JOBS" -n 1 \
    bash -c 'run_one "${1%%$'"'"'\t'"'"'*}" "${1#*$'"'"'\t'"'"'}"' _

# Reconcile: the incremental TSV append can lose rows when a resume skips a
# (reader,file) pair whose JSON was written by a crashed earlier pass. Rebuild
# census.tsv deterministically from every JSON on disk so the TSV always
# matches the checkpointed evidence.
python3 - "$OUT" "$TSV" <<'PYEOF'
import json, glob, os, sys, statistics
out, tsv = sys.argv[1], sys.argv[2]
os.chdir(out)
# only real reader dirs — census/signalled/ (meta pass) and any export dirs
# are not readers and must not become phantom census rows.
READERS = {'zen-reader','djpeg','pngtopam','heif-dec','dcraw_emu','vips',
           'imagemagick','pillow','browser'}
RAW_EXTS = ('.dng', '.nef', '.cr2', '.cr3', '.arw', '.orf', '.rw2', '.raf')
rows = ["file\treader\tstatus\tw\th\tms\tmean_r\tmean_g\tmean_b\tstd_r\tstd_g\tstd_b\tversion\terror\tcollapse"]
perfile = {}
for p in sorted(glob.glob('*/*.json')):
    reader, jf = p.split('/', 1)
    if reader not in READERS:
        continue
    base = jf[:-5]
    try:
        d = json.load(open(p))
    except Exception:
        d = {'status': 'json-parse', 'w': 0, 'h': 0, 'ms': 0}
    # missing stats stay missing — never substitute zeros (they'd both
    # fabricate a rendition and poison other readers' medians).
    m = [float(x) for x in d['mean'][:3]] if isinstance(d.get('mean'), list) else None
    s = [float(x) for x in d['std'][:3]] if isinstance(d.get('std'), list) else None
    perfile.setdefault(base, {})[reader] = (d, m, s)

# collapse flag (round-8 M3): a reader's channel means >=50/255 from a
# *consensus* — at least 2 OTHER ok+stats readers that agree with each
# other (within 50) — means a decode that technically 'ok'd but produced a
# different image. A bare leave-one-out median is not enough: with n=2
# disagreeing others the midpoint flags both correct readers (the old
# dcraw_emu/IM false positives). Rows without stats are 'no-stats' and are
# never flag candidates nor median inputs.
def cluster_median(others):
    """Median of the largest agreeing group, or None if no >=2 agree."""
    best = None
    for i, m in enumerate(others):
        group = [o for o in others if max(abs(o[c] - m[c]) for c in range(3)) < 50]
        if len(group) >= 2 and (best is None or len(group) > len(best)):
            best = group
    if best is None:
        return None
    return [statistics.median(g[i] for g in best) for i in range(3)]

for base, rd in sorted(perfile.items()):
    # explicit zen-vs-LibRaw pair flag on raw files (the review's DNG ask):
    # fires on the zen-reader row when the two pipelines diverge, and can
    # never flag the LibRaw readers themselves.
    zl = ''
    zb = rd.get('zen-reader'); db = rd.get('dcraw_emu')
    if (base.lower().endswith(RAW_EXTS) and zb and db
            and zb[1] is not None and db[1] is not None
            and zb[0].get('status') == 'ok' and db[0].get('status') == 'ok'
            and max(abs(zb[1][i] - db[1][i]) for i in range(3)) >= 50):
        zl = 'zen-vs-libraw'
    for reader, (d, m, s) in sorted(rd.items()):
        flag = ''
        if m is None or s is None:
            stats_cells = (m[:3] if m else ['no-stats'] * 3) + (s[:3] if s else ['no-stats'] * 3)
            if m is None and s is None:
                stats_cells = ['no-stats'] * 6
        else:
            stats_cells = m[:3] + s[:3]
            others = [v[1] for r2, v in rd.items()
                      if r2 != reader and v[0].get('status') == 'ok' and v[1] is not None]
            med = cluster_median(others)
            if d.get('status') == 'ok' and med is not None \
                    and max(abs(m[i] - med[i]) for i in range(3)) >= 50:
                flag = zl if (reader == 'zen-reader' and zl) else 'collapse'
        rows.append('\t'.join(map(str, [base, reader, d['status'], d['w'], d['h'], d['ms'],
            *stats_cells,
            str(d.get('version','')).replace('\t',' ')[:50],
            str(d.get('error_head','')).replace('\t',' ')[:120], flag])))
open(tsv, 'w').write('\n'.join(rows) + '\n')
n_coll = sum(1 for r in rows if r.rsplit('\t', 1)[-1] in ('collapse', 'zen-vs-libraw'))
print(f"{n_coll} collapse-flagged rows")
PYEOF
echo "census done -> $TSV"
