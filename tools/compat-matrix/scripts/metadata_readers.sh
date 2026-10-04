#!/bin/bash
# metadata_readers.sh <fixtures_dir> <out_dir> [image]
# The brief's metadata-reader table: what pure-inspection tools report per
# fixture — exiftool, exiv2, heif-info, avifdec --info, jxlinfo, webpinfo.
# Writes <out>/<tool>/<id>.txt (bounded) and aggregates structured fields into
# <out>/metadata.tsv:
#   fixture tool orient icc icc_desc exif_cs interop cicp_nclx irot imir
#   gainmap warnings note
# Not a render pass: tools that can't read the format record 'unsupported'.
set -u
FIXTURES="${1:?fixtures dir}"
OUT="${2:?output dir}"
IMAGE="${IMAGE:-imazen26-compat:lts}"
# L-a: disk-backed container /tmp under ~/tmp (no tmpfs).
CTRTMP=$(mktemp -d "${CM_TMPDIR:-$HOME/tmp}/cm-meta-ctr.XXXXXX")
trap 'rm -rf "$CTRTMP"' EXIT
mkdir -p "$OUT"
TSV="$OUT/metadata.tsv"

run_tool() {
    # tool <in> -> bounded stdout on /o/<id>.txt
    tool="$1"; id="$2"; file="$3"
    mkdir -p "$OUT/$tool"
    # checkpoint keyed to the container image id — a dump produced by an
    # older tool build is stale evidence (M-7)
    IMGID=$(docker image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null || echo "missing:$IMAGE")
    if [ -s "$OUT/$tool/$id.txt" ] && [ -f "$OUT/$tool/$id.imgid" ] \
       && [ "$(cat "$OUT/$tool/$id.imgid")" = "$IMGID" ]; then return 0; fi
    local bound=4000
    case "$tool" in
        exiftool)  cmd="exiftool -j -a -G1 -n '/f/$file'"; bound=12000 ;;
        exiv2)     cmd="( exiv2 -pa pr '/f/$file'; echo '--- pC ---'; exiv2 -pC '/f/$file' 2>&1 | head -30 )" ;;
        heif-info) cmd="heif-info '/f/$file'" ;;
        avifdec)   cmd="avifdec --info '/f/$file'" ;;
        jxlinfo)   cmd="jxlinfo -v '/f/$file'" ;;
        webpinfo)  cmd="webpinfo '/f/$file'" ;;
    esac
    timeout 60 docker run --rm --network none --read-only -v "$CTRTMP:/tmp" -e HOME=/tmp --user "$(id -u):$(id -g)" \
        --pids-limit 256 --cpus 2 --memory 1g --entrypoint /usr/bin/nice \
        -v "$FIXTURES:/f:ro" -v "$OUT/$tool:/o" \
        "$IMAGE" -n 19 bash -c "$cmd 2>&1 | head -c $bound > '/o/$id.txt'" >/dev/null 2>&1
    [ -f "$OUT/$tool/$id.txt" ] || echo "(no output)" > "$OUT/$tool/$id.txt"
    printf '%s' "$IMGID" > "$OUT/$tool/$id.imgid"
}

tail -n +2 "$FIXTURES/fixtures.tsv" | while IFS=$'\t' read -r id class file rest; do
    [ -n "${ONLY:-}" ] && [[ ! "$id" =~ $ONLY ]] && continue
    ext="${file##*.}"
    for tool in exiftool exiv2; do run_tool "$tool" "$id" "$file"; done
    case "$ext" in
        heic|heif) run_tool heif-info "$id" "$file" ;;&
        avif)      run_tool heif-info "$id" "$file"; run_tool avifdec "$id" "$file" ;;
        jxl)       run_tool jxlinfo "$id" "$file" ;;
        webp)      run_tool webpinfo "$id" "$file" ;;
    esac
done

python3 - "$OUT" "$TSV" "$FIXTURES" <<'PYEOF'
import glob, json, os, re, sys
out, tsv = sys.argv[1], sys.argv[2]
FIXDIR = sys.argv[3]
tools = sorted(d for d in os.listdir(out) if os.path.isdir(os.path.join(out, d)))
rows = ["fixture\ttool\torient\ticc\ticc_desc\texif_cs\tinterop\tcicp_nclx\tirot\timir\tgainmap\twarnings\tnote"]

EXIV2_MN = {'top, left': '1', 'top, right': '2', 'bottom, right': '3',
            'bottom, left': '4', 'left, top': '5', 'right, top': '6',
            'right, bottom': '7', 'left, bottom': '8'}
CS_NAME = {1: 'sRGB', 0xFFFF: 'uncalibrated', 2: 'adobe-rgb'}

def warn_lines(txt):
    # L-2: skip negated/benign lines — "No error detected.", "0 errors",
    # "no warnings" are not warnings; counting them prints noise in the
    # warnings column and would contradict a "no errors" summary line.
    benign = re.compile(
        r'(?i)(no error|no warning|0 errors|0 warnings|without errors|'
        r'error:? none|warning:? none|success)')
    # L-3: filename/path-valued metadata keys are not diagnostics — a
    # fixture named `*-corrupt.heic` or a `FileName` field must not score
    # as a warning. Drop the whole key line before keyword matching.
    namekey = re.compile(
        r'(?i)^\s*"?(?:[\w-]+:)?(?:SourceFile|FileName|Directory|MIMEType)'
        r'"?\s*:')
    hits = []
    for ln in txt.splitlines():
        if namekey.match(ln):
            continue
        if re.search(r'(?i)\b(warning|error|corrupt|invalid|truncat|cannot|fail)', ln) \
                and not benign.search(ln):
            hits.append(ln.strip()[:120])
    return '; '.join(hits[:4])[:300]

def exiftool_fields(txt):
    f = dict(orient='', icc='', icc_desc='', exif_cs='', interop='',
             cicp_nclx='', irot='', imir='', gainmap='', note='')
    try:
        d = json.loads(txt)[0] if txt.lstrip().startswith('[') else {}
    except Exception:
        d = {}
    if d:
        if 'IFD0:Orientation' in d:
            f['orient'] = str(d['IFD0:Orientation'])
        cs = d.get('ExifIFD:ColorSpace') or d.get('IFD0:ColorSpace')
        if cs is not None:
            f['exif_cs'] = CS_NAME.get(cs, str(cs))
        ii = d.get('InteropIFD:InteropIndex')
        if ii:
            f['interop'] = str(ii)
        icc_d = (d.get('ICC_Profile:ProfileDescription')
                 or d.get('ICC-header:ProfileDescription')
                 or d.get('ProfileCMMType') and d.get('ICC_Profile:ProfileDescription'))
        if icc_d:
            f['icc'] = 'icc'; f['icc_desc'] = str(icc_d)
        # QuickTime:* is exiftool's mapping of colr nclx / cICP code points
        cp, tp, mc, rng = (d.get('QuickTime:ColorPrimaries'),
                           d.get('QuickTime:TransferCharacteristics'),
                           d.get('QuickTime:MatrixCoefficients'),
                           d.get('QuickTime:VideoFullRangeFlag'))
        if cp is not None or mc is not None:
            f['cicp_nclx'] = '{}/{}/{}/{}'.format(
                cp if cp is not None else '?',
                tp if tp is not None else '?',
                mc if mc is not None else '?',
                'full' if rng == 1 else 'limited' if rng == 0 else '?')
        # PNG cICP chunk -> the same code-point tuple (PNG-cICP:* group)
        pcp, ptp, pmc, prng = (d.get('PNG-cICP:ColorPrimaries'),
                             d.get('PNG-cICP:TransferCharacteristics'),
                             d.get('PNG-cICP:MatrixCoefficients'),
                             d.get('PNG-cICP:VideoFullRangeFlag'))
        if pcp is not None:
            f['cicp_nclx'] = 'cicp {}/{}/{}/{}'.format(
                pcp, ptp, pmc,
                'full' if prng == 1 else 'limited' if prng == 0 else '?')
        # QuickTime:Rotation is exiftool's name for the HEIF irot box
        # (270 deg shown for irot=3)
        rot = d.get('QuickTime:Rotation')
        if rot is not None:
            try: f['irot'] = str((int(rot) // 90) % 4)
            except (TypeError, ValueError): f['irot'] = str(rot)
        g = []
        if d.get('XMP-hdrgm:Version'): g.append('hdrgm')
        if str(d.get('MPF0:NumberOfImages', '0')) not in ('0', '1', ''): g.append('mpf')
        if 'GainMap' in str(d.get('XMP-Container:DirectoryItemSemantic', '')): g.append('container:GainMap')
        f['_ext_g'] = g
    return f

def exiv2_fields(txt):
    f = dict(orient='', icc='', icc_desc='', exif_cs='', interop='',
             cicp_nclx='', irot='', imir='', gainmap='', note='')
    m = re.search(r'Exif\.Image\.Orientation\s+\w+\s+\d+\s+(.+)', txt)
    if m:
        mn = m.group(1).strip()
        f['orient'] = EXIV2_MN.get(mn, mn)
    m = re.search(r'Exif\.Photo\.ColorSpace\s+\w+\s+\d+\s+(.+)', txt)
    if m: f['exif_cs'] = m.group(1).strip()
    m = re.search(r'InteroperabilityIndex\s+\w+\s+\d+\s+(\S+)', txt)
    if m: f['interop'] = m.group(1)
    # ICC: -pa doesn't print it; the appended `-pC` tail dumps the raw
    # profile bytes (acsp/mntr markers) when one exists — empty otherwise.
    pc = txt.split('--- pC ---', 1)
    if len(pc) == 2 and re.search(r'\S', pc[1]):
        f['icc'] = 'icc'
    return f

def heifinfo_fields(txt):
    f = dict(orient='', icc='', icc_desc='', exif_cs='', interop='',
             cicp_nclx='', irot='', imir='', gainmap='', note='')
    m = re.search(r'angle \(ccw\):\s*(\d+)', txt)
    if m: f['irot'] = str(int(m.group(1)) // 90)
    m = re.search(r'(?i)mirror(?:ing)?\s*:\s*(\w+)', txt)
    if m: f['imir'] = m.group(1)
    m = re.search(r'color profile:\s*(\S+)', txt)
    if m:
        k = m.group(1)
        if k in ('prof', 'rICC'): f['icc'] = 'icc:' + k
        elif k == 'nclx':
            f['cicp_nclx'] = 'nclx'
    if re.search(r'(?m)^main brand: tmap|\btmap\b', txt): f['gainmap'] = 'tmap'
    if re.search(r'(?m)^\s*Exif:', txt): f['note'] = 'exif-item'
    if re.search(r'(?m)^\s*(mime|uri )', txt):
        f['note'] = (f['note'] + '+mime-item').strip('+')
    return f

def avifdec_fields(txt):
    f = dict(orient='', icc='', icc_desc='', exif_cs='', interop='',
             cicp_nclx='', irot='', imir='', gainmap='', note='')
    m = re.search(r'irot \(Rotation\)\s*:\s*(\d)', txt)
    if m: f['irot'] = m.group(1)
    m = re.search(r'imir \(Mirror\)\s*:\s*(\d)', txt)
    if m: f['imir'] = m.group(1)
    cp = re.search(r'Color Primaries\s*:\s*(\d+)', txt)
    tc = re.search(r'Transfer Char\.\s*:\s*(\d+)', txt)
    mc = re.search(r'Matrix Coeffs\.\s*:\s*(\d+)', txt)
    rg = re.search(r'Range\s*:\s*(\w+)', txt)
    if cp and tc and mc:
        f['cicp_nclx'] = f"{cp.group(1)}/{tc.group(1)}/{mc.group(1)}/{rg.group(1).lower() if rg else '?'}"
    # `ICC Profile : Absent` must NOT flag (the old regex did)
    m = re.search(r'ICC Profile\s*:\s*(\w+)', txt)
    if m and m.group(1).lower() == 'present': f['icc'] = 'icc'
    if re.search(r'Exif Metadata\s*:\s*Present', txt): f['note'] = 'exif-item'
    if re.search(r'XMP Metadata\s*:\s*Present', txt):
        f['note'] = (f['note'] + '+xmp').strip('+')
    return f

def jxlinfo_fields(txt):
    f = dict(orient='', icc='', icc_desc='', exif_cs='', interop='',
             cicp_nclx='', irot='', imir='', gainmap='', note='')
    m = re.search(r'Orientation:\s*(\d+)', txt)
    if m: f['orient'] = m.group(1)
    m = re.search(r'Color space:\s*(.+)', txt)
    if m: f['cicp_nclx'] = 'enum:' + re.sub(r'[,;]', '/', m.group(1).strip())[:60]
    if re.search(r'box: type: "jhgm"', txt): f['gainmap'] = 'jhgm'
    if re.search(r'box: type: "Exif"', txt): f['note'] = 'exif-box'
    if re.search(r'(?i)icc profile', txt): f['icc'] = 'icc'
    return f

def webpinfo_fields(txt):
    f = dict(orient='', icc='', icc_desc='', exif_cs='', interop='',
             cicp_nclx='', irot='', imir='', gainmap='', note='')
    m = re.search(r'(?m)^\s*ICCP:\s*(\d+)', txt)
    if m and m.group(1) != '0': f['icc'] = 'icc'
    elif re.search(r'(?m)Chunk ICCP at offset', txt): f['icc'] = 'icc'
    if re.search(r'(?m)^\s*EXIF:\s*1', txt): f['note'] = 'exif-chunk'
    return f

PARSERS = {'exiftool': exiftool_fields, 'exiv2': exiv2_fields,
           'heif-info': heifinfo_fields, 'avifdec': avifdec_fields,
           'jxlinfo': jxlinfo_fields, 'webpinfo': webpinfo_fields}

# Byte-level signalling markers no metadata tool names: the ISO 21496-1
# APP2 urn and the GContainer DirectoryItem Semantic=GainMap. Merged into
# the exiftool row's gainmap field with a `markers-byte-scan` note.
filescan = {}
try:
    for ln in open(os.path.join(FIXDIR, 'fixtures.tsv')).read().splitlines()[1:]:
        p = ln.split('\t')
        if len(p) < 3:
            continue
        fx_file = os.path.join(FIXDIR, p[2])
        try:
            d = open(fx_file, 'rb').read()
        except OSError:
            continue
        toks = []
        if b'urn:iso:std:iso:ts:21496' in d:
            toks.append('iso21496')
        if re.search(rb'(?i)semantic[=>"]{1,2}\s*"?GainMap', d):
            toks.append('container:GainMap')
        if toks:
            filescan[p[0]] = '+'.join(toks)
except OSError:
    pass

for tool in tools:
    parse = PARSERS.get(tool)
    for p in sorted(glob.glob(os.path.join(out, tool, '*.txt'))):
        fid = os.path.basename(p)[:-4]
        txt = open(p, errors='replace').read()
        f = parse(txt) if parse else dict.fromkeys(
            ('orient','icc','icc_desc','exif_cs','interop','cicp_nclx','irot','imir','gainmap','note'), '')
        note = f.get('note', '')
        # merge exiftool's mechanism list with byte-level markers the tool
        # does not name (ISO 21496 APP2, GContainer GainMap directory item)
        if tool == 'exiftool' and f.get('_ext_g') is not None:
            f['gainmap'] = '+'.join(dict.fromkeys(f.pop('_ext_g')))
            bs = filescan.get(fid)
            if bs:
                for tok in bs.split('+'):
                    if tok not in f['gainmap'].split('+'):
                        f['gainmap'] = (f['gainmap'] + '+' + tok).strip('+')
                note = (note + '+markers-byte-scan').strip('+')
        if 'unsupported' in txt.lower() or 'not a valid' in txt.lower():
            note = (note + '+unsupported').strip('+')
        elif txt.strip() == '(no output)':
            note = (note + '+no-output').strip('+')
        rows.append('\t'.join([fid, tool, f['orient'], f['icc'], f['icc_desc'],
                               f['exif_cs'], f['interop'], f['cicp_nclx'],
                               f['irot'], f['imir'], f['gainmap'],
                               warn_lines(txt), note]))
open(tsv, 'w').write('\n'.join(rows) + '\n')
print(f"{len(rows)-1} rows -> {tsv}")
PYEOF
