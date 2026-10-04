#!/bin/bash
# run_matrix.sh <fixtures_dir> <out_dir> [adapter ...]
# Sweeps every Docker adapter over every fixture. Writes
#   <out>/<adapter>/<fixture_id>.png|json  and  <out>/decode.tsv
# Expected-reader failures are data, not script failures.
#
# Checkpoint policy (round-8 H3): a cell is reused only when its JSON was
# written by the *same container image id*, the *same adapter bytes*, and
# the *same fixture bytes* — `image_id` + `adapter_sha` + `fixture_sha` are
# recorded in every JSON and compared on resume. `platform.txt` in the out
# dir records the image ids and adapter shas (generated, never handwritten).
#
# Format declarations (M-10): `n/a` is written only for (adapter, ext)
# pairs the matrix declares unsupported below. Any error on a declared-
# supported format is a counted failure, never auto-`n/a`.
set -u
FIXTURES="${1:?fixtures dir}"
OUT="${2:?output dir}"
shift 2
IMAGE="${IMAGE:-imazen26-compat:lts}"
BROWSERS_IMAGE="${BROWSERS_IMAGE:-imazen26-compat:browsers}"
ADAPTERS=("$@")
if [ ${#ADAPTERS[@]} -eq 0 ]; then
    ADAPTERS=(djpeg pngtopam dwebp heif-dec avifdec djxl imagemagick imagemagick-autorot graphicsmagick vips vips-raw ffmpeg pillow opencv gdkpixbuf qt ultrahdr_app)
fi

mkdir -p "$OUT"
TSV="$OUT/decode.tsv"
[ -f "$TSV" ] || printf 'adapter\tfixture\tstatus\tw\th\tms\tversion\terror\n' > "$TSV"

image_id() { docker image inspect -f '{{.Id}}' "$1" 2>/dev/null || echo "missing:$1"; }
IMGID=$(image_id "$IMAGE")
BWID=$(image_id "$BROWSERS_IMAGE")

# Declared format coverage (M-10). Single-purpose tools declare their one
# format; browsers declare what a web reader can reach; generic readers
# (imagemagick, vips, ffmpeg, ...) stay unlisted = all formats supported,
# so a missing delegate or decode error counts as a failure, not coverage.
declare -A FMT=(
    [djpeg]="jpg jpeg"            [ultrahdr_app]="jpg jpeg"
    [pngtopam]="png"              [dwebp]="webp"
    [avifdec]="avif"              [djxl]="jxl"             [djxl-best]="jxl"
    [heif-dec]="heic heif"
    [dcraw_emu]="dng nef cr2 cr3 arw orf rw2 raf pef"
    [pillow]="jpg jpeg png webp"
    [qt]="jpg jpeg png webp"
    [chromium]="jpg jpeg png webp avif"    [chromium-canvas]="jpg jpeg png webp avif"
    [firefox]="jpg jpeg png webp avif"     [firefox-canvas]="jpg jpeg png webp avif"
    [firefox-cm2]="jpg jpeg png webp avif" [firefox-cm2-canvas]="jpg jpeg png webp avif"
    # r13 M-3: the probe measured webkit + latest opencv decoding
    # `jxl-enum-srgb` ok on both images — JXL is declared so the cells
    # carry real verdicts instead of `n/a`. An image whose build lacks it
    # records errors, not coverage: declared coverage is the adapter's
    # contract; the probe sidecars record what each image actually did.
    [webkit]="jpg jpeg png webp avif jxl"  [webkit-canvas]="jpg jpeg png webp avif jxl"
    [opencv]="jpg jpeg png webp jxl"
)
fmt_ok() {
    local m="${FMT[$1]:-}"
    [ -z "$m" ] && return 0
    case " $m " in *" $2 "*) return 0;; esac
    return 1
}
is_browser() {
    case "$1" in
        chromium|firefox|webkit|*-canvas|firefox-cm2*) return 0;;
    esac
    return 1
}

# write a driver-declared `n/a` cell (adapter doesn't support this format)
write_na() {  # <json> <imgid> <asha> <fsha>
    printf '{"status":"n/a","w":0,"h":0,"ms":0,"version":"","image_id":"%s","adapter_sha":"%s","fixture_sha":"%s","error_head":"format not supported by adapter"}\n' \
        "$2" "$3" "$4" > "$1"
}

# per-adapter sha256 of the bytes inside each image (authoritative, not the
# host copy). Browsers: the adapter script + its decode .mjs.
declare -A ASHA
lts_ad=() bw_ad=()
for a in "${ADAPTERS[@]}"; do
    if is_browser "$a"; then bw_ad+=("$a"); else lts_ad+=("$a"); fi
done
if ((${#lts_ad[@]})); then
    while read -r sha p; do ASHA["$(basename "$p")"]="$sha"; done < <(
        docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
            --entrypoint sha256sum "$IMAGE" \
            "${lts_ad[@]/#//opt/adapters/}" 2>/dev/null)
fi
if ((${#bw_ad[@]})); then
    bsha=$(docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
        --entrypoint sha256sum "$BROWSERS_IMAGE" \
        /opt/adapters/browser /opt/adapters/browser_decode.mjs 2>/dev/null | sha256sum | cut -d' ' -f1)
    for a in "${bw_ad[@]}"; do ASHA["$a"]="$bsha"; done
fi

{
    echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ) run_matrix platform"
    echo "image=$IMAGE id=$IMGID"
    echo "browsers_image=$BROWSERS_IMAGE id=$BWID"
    echo "fixtures=$FIXTURES"
    for a in "${ADAPTERS[@]}"; do
        echo "adapter=$a sha256=${ASHA[$a]:-missing}"
        # r12 L-2: mark this run's container adapters so `matrix --check`
        # can refuse an image_id=host cell on any of them — a host cell is
        # admissible only for adapters with no image class (zen columns,
        # coordinator platform tools).
        echo "container_adapter=$a"
    done
} >> "$OUT/platform.txt"

# H6 preflight: icc-claiming fixtures must embed a profile that is
# *functionally* the reference (relcol+perceptual identity on an RGB grid),
# not merely the right bytes. Skippable via CM_ICC_CHECK=0.
if [ "${CM_ICC_CHECK:-1}" = "1" ]; then
    SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
    CM_BIN_RES="${CM_BIN:-$(command -v compat-matrix || echo "$SCRIPT_DIR/../target/release/compat-matrix")}"
    # icc_identity_check's own self-test first: the independent reference
    # must fail on a deliberately-perturbed profile (H-3 negative gate).
    CM_BIN="$CM_BIN_RES" python3 "$SCRIPT_DIR/icc_identity_check.py" --selftest || {
        echo "icc identity check selftest failed — refusing to sweep" >&2; exit 1; }
    icc_fail=0
    while IFS=$'\t' read -r id _class file _rest; do
        ref=""
        case "$id" in
            jxl-*) continue;;  # JXL colour lives inside the compressed codestream (no extractable ICC bytes)
            *icc-srgb*|*iccp-srgb*|*conflict-iccp-srgb*|*conflict-icc-srgb*) ref=srgbv4;;
            *icc-p3-v2*|*iccp-p3-v2*) ref=p3v2;;
            *icc-p3*|*iccp-p3*|png16-p3|*iccp-p3*|*icc-p3*|*colr-conflict*) ref=p3v4;;
            *icc-adobe*) ref=adobe;;
            # heic-remux-base / heic-tile-base carry the donor's own camera
            # ICC — signalling-under-test is the donor's, not a generated
            # canonical profile, so no independent-identity claim is made.
            *) continue;;
        esac
        CM_BIN="$CM_BIN_RES" python3 "$SCRIPT_DIR/icc_identity_check.py" \
            "$FIXTURES/$file" "$ref" || icc_fail=1
    done < <(tail -n +2 "$FIXTURES/fixtures.tsv")
    if [ "$icc_fail" != 0 ]; then
        echo "icc identity check failed — refusing to sweep" >&2
        exit 1
    fi
fi

# cell_current <json> <image_id> <adapter_sha> <fixture_sha> — exit 0 iff the
# checkpoint was written by this image+adapter+fixture triple.
cell_current() {
    [ -f "$1" ] || return 1
    python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
sys.exit(0 if (d.get('image_id') == sys.argv[2]
               and d.get('adapter_sha') == sys.argv[3]
               and d.get('fixture_sha') == sys.argv[4]) else 1)
PY
}

# Named containers so a killed timeout / client can't leave orphans behind.
# Disk-backed /tmp: one scratch dir per run under ~/tmp, mounted over /tmp
# (tmpfs is forbidden — brief requires disk-backed container temp).
CNAME_PFX="cm-$$-$RANDOM-"
TMPBASE="${CM_TMPDIR:-$HOME/tmp}"
mkdir -p "$TMPBASE"
CTR_TMP=$(mktemp -d "$TMPBASE/cm-ctr.XXXXXX")
cleanup() {
    docker ps -aq --filter "name=$CNAME_PFX" 2>/dev/null | xargs -r docker rm -f >/dev/null 2>&1
    rm -rf "$CTR_TMP"
}
trap cleanup EXIT

SCRIPT_DIR_S=$(cd "$(dirname "$0")" && pwd)
CM_BIN_S="${CM_BIN:-$(command -v compat-matrix || echo "$SCRIPT_DIR_S/../target/release/compat-matrix")}"

# decode_cell <adapter> <file> <id> <fsha> [target_dir] — decode one cell
# into <target_dir:-$OUT/$a>/$id.{png,json} via the adapter's image.
# Phase-1 probes pass a scratch dir so capability attempts never touch a
# phase-2 cell (r13 M-1).
decode_cell() {
    local a="$1" file="$2" id="$3" fsha="$4" odir="${5:-$OUT/$a}"
    local imgid entry bimg tmo
    if is_browser "$a"; then
        imgid="$BWID"; entry=/opt/adapters/browser; bimg="$BROWSERS_IMAGE"; tmo=180
    else
        imgid="$IMGID"; entry="/opt/adapters/$a"; bimg="$IMAGE"; tmo=120
    fi
    mkdir -p "$odir"
    rm -f "$odir/$id.png" "$odir/$id.json" "$odir/$id.json.stderr" "$odir/$id.json.decode.stderr"
    if is_browser "$a"; then
        local eng="${a%%-*}" mode="screenshot" ffenv=()
        case "$a" in
            firefox-cm2*) eng="firefox"; mode="screenshot"; ffenv=(-e FF_MODE=2)
                [[ "$a" == *canvas ]] && mode="canvas";;
            *-canvas) mode="canvas";;
        esac
        timeout $tmo docker run --name "$CNAME_PFX$a-$id" --rm --network none --read-only \
            -v "$CTR_TMP:/tmp" -e HOME=/tmp --user "$(id -u):$(id -g)" \
            --pids-limit 1024 --cpus 4 --memory 4g \
            -e CM_IMAGE_ID="$imgid" -e CM_FIXTURE_SHA="$fsha" "${ffenv[@]}" \
            --entrypoint /usr/bin/nice \
            -v "$FIXTURES:/f:ro" -v "$odir:/o" -w /f \
            "$bimg" -n 19 "$entry" "$file" "/o/$id.png" "/o/$id.json" "$eng" "$mode" >/dev/null 2>&1
    else
        timeout $tmo docker run --name "$CNAME_PFX$a-$id" --rm --network none --read-only \
            -v "$CTR_TMP:/tmp" -e HOME=/tmp --user "$(id -u):$(id -g)" \
            --pids-limit 1024 --cpus 4 --memory 4g \
            -e CM_IMAGE_ID="$imgid" -e CM_FIXTURE_SHA="$fsha" \
            --entrypoint /usr/bin/nice \
            -v "$FIXTURES:/f:ro" -v "$odir:/o" -w /f \
            "$bimg" -n 19 "$entry" "$file" "/o/$id.png" "/o/$id.json" >/dev/null 2>&1
    fi
}

# emit_record <adapter> <id> [json_path] — append the cell's decode.tsv
# line. Probe cells pass their scratch json so the attempt is logged.
emit_record() {
    local a="$1" id="$2" json="${3:-$OUT/$1/$2.json}"
    if [ -f "$json" ]; then
        python3 -c "
import json,sys
d=json.load(open('$json'))
print('$a','$id',d['status'],d['w'],d['h'],d['ms'],
      d.get('version','').replace(chr(9),' ')[:60],
      d.get('error_head','').replace(chr(9),' ')[:120], sep='\t')
" >> "$TSV"
    else
        printf '%s\t%s\t%s\t0\t0\t0\t%s\t%s\n' "$a" "$id" crash "adapter-no-json" "adapter produced no json" >> "$TSV"
    fi
}

# ---- phase 1: baseline capability probe + gate (L-8, r13 M-1) --------------
# Phase 1 runs BEFORE the main sweep as a capability probe: every adapter
# attempts every format baseline the fixture set carries into a SCRATCH dir
# — never the cell dir — and the outcome lands in $OUT/probe/<adapter>.json.
# The phase-2 sweep then decodes every declared-supported cell for real: a
# probe failure can no longer launder a baseline error into `n/a` (r12
# M-1: mark_probe_na overwrote the phase-2 checkpoint).
# The gate fails ONLY when an adapter produces an `ok` baseline decode that
# does not classify `correct` within T (or a `not-measurable` whose collapse
# includes the correct hyp): wrong pixels on a trivially-signalled baseline
# mean the adapter's signalling claims can't be trusted.
# Fixture sets without a format's baseline row skip that format (reps sets
# are structurally exempt). DNG has no baseline — camera-raw stays
# reps-only by design. ultrahdr_app's jpg coverage is gainmap-JPEG only
# (libultrahdr refuses plain JPEGs), so its jpg baseline is the gainmap
# fixture — its plain-jpeg error cells still count as failures under the
# supported-format rule.
declare -A FMT_BASE=(
    [jpg]=jpeg-exif-o1 [jpeg]=jpeg-exif-o1
    [png]=png-untagged [webp]=webp-untagged
    [avif]=avif-untagged [jxl]=jxl-enum-srgb
    [heic]=heic-nocolr [heif]=heic-nocolr
)
declare -A GATE_BASE=([ultrahdr_app]="jpeg-ultrahdr")

PROBE_DIR="$OUT/probe"
PROBE_SCRATCH="$CTR_TMP/probe-cells"
mkdir -p "$PROBE_DIR" "$PROBE_SCRATCH"

# probe_current <adapter> — exit 0 iff the probe sidecar names this run's
# image + adapter bytes (fixture shas are checked per-format below).
probe_current() {
    local p="$PROBE_DIR/$1.json"
    [ -f "$p" ] || return 1
    python3 - "$p" "$IMGID" "$BWID" "${ASHA[$1]:-x}" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
sys.exit(0 if (d.get('image_id') in (sys.argv[2], sys.argv[3])
               and d.get('adapter_sha') == sys.argv[4]) else 1)
PY
}

gate_fail=0
for a in "${ADAPTERS[@]}"; do
    pfile="$PROBE_DIR/$a.json"
    if is_browser "$a"; then a_imgid="$BWID"; else a_imgid="$IMGID"; fi
    if probe_current "$a"; then
        # sidecar from this image+adapter already records the outcomes —
        # still gate-check it so a fresh binary can't skip the gate.
        gate_bad=$(python3 - "$pfile" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
bad = [f for f, r in d.get('results', {}).items() if r.get('gate') == 'fail']
print(' '.join(bad))
PY
)
        if [ -n "$gate_bad" ]; then
            echo "baseline gate: $a probe sidecar records failed verdicts: $gate_bad" >&2
            gate_fail=1
        fi
        continue
    fi
    results="{}"
    seen_bases=" "
    # every adapter decodes every format baseline — FMT-declared coverage
    # scopes phase 2 only; the probe records what the adapter actually did.
    for f in jpg jpeg png webp avif jxl heic heif; do
        g_bid="${FMT_BASE[$f]:-}"
        [ -n "${GATE_BASE[$a]:-}" ] && case "$f" in jpg|jpeg) g_bid="${GATE_BASE[$a]}";; esac
        [ -n "$g_bid" ] || continue          # no baseline for this format
        case "$seen_bases" in *" $g_bid "*) continue;; esac
        seen_bases="$seen_bases$g_bid "
        g_row=$(grep -P "^$g_bid\t" "$FIXTURES/fixtures.tsv" || true)
        [ -n "$g_row" ] || continue          # fixture set lacks this baseline
        g_file=$(printf '%s' "$g_row" | cut -f3)
        g_fsha=$(printf '%s' "$g_row" | cut -f9)
        podir="$PROBE_SCRATCH/$a"
        decode_cell "$a" "$g_file" "$g_bid" "$g_fsha" "$podir"
        pj="$podir/$g_bid.json"; pp="$podir/$g_bid.png"
        status="crash"; verdict=""; correct="false"; gate=""
        if [ -f "$pj" ]; then
            status=$(python3 -c "import json;print(json.load(open('$pj')).get('status','crash'))" 2>/dev/null)
            eh=$(python3 -c "import json;print(json.load(open('$pj')).get('error_head',''))" 2>/dev/null)
        else
            eh="probe: adapter produced no json"
        fi
        if [ "$status" = "ok" ] && [ -f "$pp" ]; then
            c=$("$CM_BIN_S" classify "$pp" "$FIXTURES" "$g_bid" 2>/dev/null)
            cv=$(printf '%s' "$c" | cut -f1); cc=$(printf '%s' "$c" | cut -f2)
            cn=$(printf '%s' "$c" | cut -f3)
            verdict="$cv"
            if [ "$cc" = "1" ] || { [ "$cv" = "not-measurable" ] && case "$cn" in *"includes correct"*) true;; *) false;; esac; }; then
                correct="true"; gate="pass"
            else
                gate="fail"
                echo "baseline gate: $a decoded $g_bid but classified $cv (expected correct)" >&2
                gate_fail=1
            fi
        fi
        results=$(python3 - "$results" "$f" "$g_bid" "$g_fsha" "$status" "$verdict" "$correct" "$gate" "$eh" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
r[sys.argv[2]] = {"fixture": sys.argv[3], "fixture_sha": sys.argv[4],
                  "status": sys.argv[5], "verdict": sys.argv[6],
                  "correct": sys.argv[7] == "true"}
if sys.argv[8]:
    r[sys.argv[2]]["gate"] = sys.argv[8]
if sys.argv[9]:
    r[sys.argv[2]]["error_head"] = sys.argv[9][:200]
print(json.dumps(r))
PY
)
        emit_record "$a" "$g_bid" "$pj"
    done
    python3 - "$pfile" "$a" "$a_imgid" "${ASHA[$a]:-x}" "$results" <<'PY'
import json, sys
doc = {"adapter": sys.argv[2], "image_id": sys.argv[3],
       "adapter_sha": sys.argv[4], "results": json.loads(sys.argv[5])}
json.dump(doc, open(sys.argv[1], "w"), indent=1, sort_keys=True)
PY
done
if [ "$gate_fail" != 0 ]; then
    echo "baseline gate failed before phase 2 — sweep results not trustworthy" >&2
    exit 1
fi
# PHASE1_ONLY=1 stops after the capability probe — the M-1 gate is exercised
# without re-running the whole sweep.
[ "${PHASE1_ONLY:-0}" = 1 ] && { echo "phase-1 capability probe complete (PHASE1_ONLY)" >&2; exit 0; }

# ---- phase 2: full sweep ---------------------------------------------------
tail -n +2 "$FIXTURES/fixtures.tsv" | while IFS=$'\t' read -r id class file _w _h _eo _colour _gm fsha _rest; do
    # optional ONLY=<ere> env limits the sweep to matching fixture ids
    [ -n "${ONLY:-}" ] && [[ ! "$id" =~ $ONLY ]] && continue
    ext="${file##*.}"
    for a in "${ADAPTERS[@]}"; do
        if is_browser "$a"; then imgid="$BWID"; else imgid="$IMGID"; fi
        if ! fmt_ok "$a" "$ext"; then
            # declared-unsupported: a driver-written n/a cell, not an error.
            # An existing cell is reused only while it names this fixture's
            # sha AND is itself a driver n/a — a changed fixture invalidates
            # it, and a real ok/error cell is never overwritten by a
            # declaration.
            mkdir -p "$OUT/$a"
            if [ -f "$OUT/$a/$id.json" ]; then
                python3 - "$OUT/$a/$id.json" "$fsha" <<'PY' && continue
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
sys.exit(0 if (d.get("fixture_sha") == sys.argv[2]
               and d.get("status") == "n/a") else 1)
PY
            fi
            write_na "$OUT/$a/$id.json" "$imgid" "${ASHA[$a]:-x}" "$fsha"
            continue
        fi
        # r14 M-2: a checkpoint whose identity triple matches is reused —
        # except a driver-written `n/a`, which only ever meant "the adapter
        # declared this format unsupported". FMT admitting the format
        # revokes it, so the cell gets a real decode instead of persisting
        # stale (the 48 webkit/opencv JXL `n/a`s per r13 image).
        if cell_current "$OUT/$a/$id.json" "$imgid" "${ASHA[$a]:-x}" "$fsha" \
           && [ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status"))' \
                     "$OUT/$a/$id.json" 2>/dev/null)" != "n/a" ]; then continue; fi
        decode_cell "$a" "$file" "$id" "$fsha"
        # M-6 render provenance: the PNG on disk is the adapter's render —
        # stamp output_sha at decode time so the cell binds the bytes that
        # produced the verdict (thumb_sha takes over once thumbed).
        if [ -f "$OUT/$a/$id.json" ] && [ -f "$OUT/$a/$id.png" ]; then
            python3 - "$OUT/$a/$id.json" "$OUT/$a/$id.png" <<'PY'
import hashlib, json, sys
d = json.load(open(sys.argv[1]))
if d.get("status") == "ok":
    d["output_sha"] = hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
    json.dump(d, open(sys.argv[1], "w"))
PY
        fi
        emit_record "$a" "$id"
    done
done
echo "done -> $TSV"
