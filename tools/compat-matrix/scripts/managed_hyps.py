#!/usr/bin/env python3
"""Render hypothesis PNGs via lcms2 (Pillow ImageCms) from true-raw fixture
decodes — the round-2 colour fix.

Every hypothesis is grounded in the fixture's own *raw* decode (compat-matrix
probe --raw, which preserves stored code values), then:

  - orientation specs apply the EXIF transform to pixels
  - colour specs apply lcms2 profileToProfile(src_icc -> sRGB, relative
    colorimetric) where src_icc is the fixture's own embedded ICC when the
    hypothesis' interpretation equals the declared profile, else the
    equivalent bundled profile (Display-P3 v4 / Adobe RGB / sRGB)

Usage: managed_hyps.py <fixtures_dir> [--only <id>]

Requires the release `compat-matrix` binary (probe + dump-icc) on PATH or
via CM_BIN env var, and the icc/ profile set under the fixtures dir (run
`compat-matrix dump-profiles <fixtures>/icc` first).
"""

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageCms

CM_BIN = os.environ.get("CM_BIN", "compat-matrix")
# Reference-decoder image for corpus hypothesis bases (H-1): camera-raw reps
# render through LibRaw dcraw_emu, and `corpus:libheif-nclx` through
# libheif's heif-convert — never through zen.
REF_IMAGE = os.environ.get("CM_REF_IMAGE", "imazen26-compat:lts")
RAW_EXTS = (".dng", ".nef", ".cr2", ".cr3", ".arw", ".orf", ".rw2", ".raf",
            ".pef")

# EXIF orientation -> Pillow transpose op (display transform)
ORIENT = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,  # 90 CW
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,  # 90 CCW
}

# colour spec value -> equivalent ICC profile file (under <fixtures>/icc/)
EQUIV = {
    "p3": "display-p3-v4.icc",
    "p3-icc": "display-p3-v4.icc",
    "adobe": "adobe-rgb.icc",
    "conflict-nclx-srgb-vs-icc-p3": "display-p3-v4.icc",
    "srgb": "srgb.icc",
    "uncalibrated": "srgb.icc",
}


def load_tsv(path):
    rows = []
    with open(path) as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            rows.append(dict(zip(header, line.split("\t"))))
    return rows


def fsha(fixture_path):
    """Content key for the render caches — a fixture whose bytes changed must
    not reuse decodes/icc/pfm cached under the old bytes."""
    return hashlib.sha256(Path(fixture_path).read_bytes()).hexdigest()[:12]


_TOOL_KEY = None


def tool_key():
    """Cache-identity material for the render caches: the reference image's
    libraw/libheif package versions, the image id itself, and the probe
    binary's sha. Keying only on fixture bytes let round 10 re-score cells
    against round-9 renders produced by a different decode command (the
    `-t 0`/`heif-convert` fixes never reached cached outputs). One docker
    call per process."""
    global _TOOL_KEY
    if _TOOL_KEY is None:
        r = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--read-only",
             "--user", f"{os.getuid()}:{os.getgid()}",
             "--entrypoint", "bash", REF_IMAGE, "-c",
             "(dpkg-query -W 'libraw*' 'libheif*' 'libde265*' 2>/dev/null; "
             "pacman -Q 2>/dev/null | grep -iE 'libraw|libheif|libde265')"
             " | sort -u"],
            capture_output=True)
        img = subprocess.run(
            ["docker", "image", "inspect", "-f", "{{.Id}}", REF_IMAGE],
            capture_output=True)
        _TOOL_KEY = hashlib.sha256(
            r.stdout + img.stdout).hexdigest()[:10]
    return _TOOL_KEY


def ref_decode(fixture_path, cache_dir, fid, script_tpl, tag):
    """Run `script_tpl` inside the reference image; it must write
    /out/{OUT}. Reference-decoder renders are dockered so zen never
    provides its own grading baseline (H-1). The cache key binds the
    command template AND the reference toolchain — a decode-command or
    image change must not reuse a stale render (round-10 M-1)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    ck = hashlib.sha256(script_tpl.encode() + tool_key().encode())
    key = f"{fid}.{fsha(fixture_path)}.{tag}.{ck.hexdigest()[:10]}"
    out = cache_dir / f"{key}.png"
    if not out.exists():
        script = script_tpl.replace("{OUT}", out.name)
        tmpbase = Path(os.environ.get("CM_TMPDIR") or (Path.home() / "tmp"))
        tmpbase.mkdir(parents=True, exist_ok=True)
        ctr_tmp = Path(tempfile.mkdtemp(prefix="cm-ref-", dir=str(tmpbase)))
        try:
            r = subprocess.run(
                ["docker", "run", "--rm", "--network", "none", "--read-only",
                 "--user", f"{os.getuid()}:{os.getgid()}",
                 "-v", f"{ctr_tmp}:/tmp", "-e", "HOME=/tmp",
                 "-v", f"{Path(fixture_path).resolve().parent}:/f:ro",
                 "-v", f"{out.parent.resolve()}:/out",
                 "--entrypoint", "/usr/bin/nice", REF_IMAGE,
                 "-n", "19", "bash", "-c", script],
                capture_output=True)
            if r.returncode != 0 or not out.exists():
                raise SystemExit(
                    f"{fid}: {tag} decode failed: "
                    f"{r.stderr.decode(errors='replace')[:300]}")
        finally:
            shutil.rmtree(ctr_tmp, ignore_errors=True)
    return Image.open(out).convert("RGBA")


def libraw_decode(fixture_path, cache_dir, fid):
    """Camera-raw hypothesis base: LibRaw `dcraw_emu -w -T -t 0 -6` (16-bit
    TIFF, camera white balance) converted through PIL — the same conversion
    the dcraw_emu adapter uses, so `stored`/`correct` grade against the
    format reference decoder. zen's own DNG decode is deliberately not the
    base: if zen collapses the RAW pipeline its cells read `other`, not
    `correct`."""
    name = Path(fixture_path).name
    script = (
        f"cp '/f/{name}' /tmp/in.raw && cd /tmp && "
        # `-t 0` disables LibRaw's auto-rotation: the base must be the
        # *stored* pixels — every orientation hyp applies its own EXIF
        # transform (as-signalled = stored + orient, exactly once). With
        # auto-rotate on, correct and orient-only would render identically.
        # `-6` keeps the TIFF 16-bit — the documented base precision.
        # dcraw_emu can exit nonzero on files it still rendered (LibRaw
        # "data corrupted" warnings) — the dcraw_emu adapter treats a
        # produced TIFF as success, so we do the same.
        "dcraw_emu -w -t 0 -T -6 in.raw </dev/null; "
        "T=$(ls *.tiff *.ppm 2>/dev/null | head -1) && test -n \"$T\" && "
        f"python3 -c 'import sys; from PIL import Image; "
        f"Image.open(sys.argv[1]).convert(\"RGB\").save(sys.argv[2])' "
        f"\"$T\" '/out/{{OUT}}'")
    return ref_decode(fixture_path, cache_dir, fid, script, "libraw")


def heif_convert_decode(fixture_path, cache_dir, fid, tag):
    """heif-convert the given HEIF file inside the reference image. When
    libheif rejects the container outright (real iPhone HEICs aux-link the
    depth map to both the photo and the tmap — libheif 1.17's depth path
    refuses), retry once on a remux that drops only the `auxid:2` items:
    the surviving pixel payload is verbatim, so the render remains the
    reference decoder's honest reading."""
    name = Path(fixture_path).name
    script = (
        f"cp '/f/{name}' /tmp/in.heic && "
        f"heif-convert /tmp/in.heic '/out/{{OUT}}'")
    try:
        return ref_decode(fixture_path, cache_dir, fid, script, tag)
    except SystemExit:
        pass
    repaired = Path(cache_dir) / f"{fsha(fixture_path)}.{bin_sha()}.dropped-depth.heic"
    if not repaired.exists():
        r = subprocess.run(
            [CM_BIN, "probe", str(fixture_path), "--remux", str(repaired),
             "--drop-depth"], capture_output=True)
        if r.returncode != 0 or not repaired.exists():
            raise SystemExit(
                f"{fid}: drop-depth remux failed: "
                f"{r.stderr.decode(errors='replace')[:200]}")
    sys.stderr.write(
        f"{fid}: heif-convert rejected the container — retried on a "
        "depth-aux-dropped remux (pixel payload verbatim)\n")
    script = (
        f"cp '/f/{repaired.name}' /tmp/in.heic && "
        f"heif-convert /tmp/in.heic '/out/{{OUT}}'")
    return ref_decode(repaired, cache_dir, fid, script, f"{tag}-dd")


def libheif_decode(fixture_path, cache_dir, fid):
    """nclx-honouring HEIF decode by the format reference decoder
    (`heif-convert` applies the declared colr incl. the range flag) — the
    `nclx-wins` hypothesis on the conflict fixtures, and on
    `heic-colr-conflict-range` the only render that exercises the declared
    limited range."""
    return heif_convert_decode(fixture_path, cache_dir, fid, "libheif")


def heif_primary_ispe(fixture_path):
    """(w, h) of the primary item's `ispe` via `probe demux` — the coded
    raster dims every transform-stripped base must produce."""
    r = subprocess.run([CM_BIN, "demux", str(fixture_path)],
                       capture_output=True, text=True)
    m = re.search(r"primary dims: Some\(\((\d+), (\d+)\)\)", r.stdout)
    if not m:
        raise SystemExit(f"{fixture_path}: no primary ispe in demux output")
    return int(m.group(1)), int(m.group(2))


def heif_base(fixture_path, cache_dir, fid, unmanaged):
    """HEIF stored-pixel base via the *reference* decoder (L-6): `probe
    --remux` rewrites the container — `unmanaged` strips every `colr`
    (the `corpus:stored` base = "reader honours no colour signalling"),
    `--no-icc` drops only `prof`/`rICC` so the nclx matrix decl still steers
    the base, and `--drop-transform` strips `irot`/`imir`/`clap` so
    heif-convert — which applies the display transform and has no flag to
    skip it — renders the coded raster, not the displayed image (r12 H-1:
    with the properties kept, `stored` was the irot/imir-applied render and
    every orientation verdict inverted). Guard: the render's dims must
    equal the primary's `ispe` — a transform leak flips them on rotated
    content. zen's raw path never grades itself, and its ICC-over-nclx
    precedence can't leak into `stored`."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"{fid}.{fsha(fixture_path)}.{bin_sha()}"
    tag = "unm" if unmanaged else "raw"
    stripped = cache_dir / f"{key}.{tag}.heic"
    if not stripped.exists():
        r = subprocess.run(
            [CM_BIN, "probe", str(fixture_path), "--remux", str(stripped)]
            + (["--unmanaged"] if unmanaged else ["--no-icc"])
            + ["--drop-transform"],
            capture_output=True)
        if r.returncode != 0 or not stripped.exists():
            raise SystemExit(
                f"{fid}: heif remux failed: "
                f"{r.stderr.decode(errors='replace')[:200]}")
    # Route through heif_convert_decode so the depth-aux retry applies to the
    # remuxed file too — colour stripping keeps the auxid:2 item, which
    # libheif still rejects.
    img = heif_convert_decode(stripped, cache_dir, fid, f"heif-{tag}")
    ispe = heif_primary_ispe(fixture_path)
    if img.size != ispe:
        raise SystemExit(
            f"{fid}: {tag} base {img.size} != primary ispe {ispe} — a "
            "display transform leaked into the stored-pixel base")
    # r13 L-7: the dims check only catches 90°/270° leaks — irot=2 and imir
    # preserve dims. Compare the base against zen-raw's stored-pixel decode
    # (probe --raw applies no display transform): a transform leak moves
    # whole pixels, far above the ≤8-level bound zen-vs-libde265 decode
    # noise measures at (same payload, both honest h265 paths). Scoped to
    # the colr-stripped (`unmanaged`) base: a no-icc `raw` base keeps nclx,
    # so libheif's declared-range expansion legitimately diverges from
    # zen-raw on conflict-range fixtures — not a transform leak.
    if unmanaged:
        ref = probe_raw_decode(fixture_path, cache_dir, fid).convert("RGBA")
        if ref.size != img.size:
            raise SystemExit(
                f"{fid}: zen-raw stored decode {ref.size} != {tag} base "
                f"{img.size}")
        worst = max(
            abs(a - b)
            for pa, pb in zip(img.getdata(), ref.getdata())
            for a, b in zip(pa[:3], pb[:3])
        )
        if worst > 8:
            raise SystemExit(
                f"{fid}: {tag} base differs from zen-raw stored decode by "
                f"{worst} levels — a display transform (irot=2/imir) "
                "leaked into the stored-pixel base")
    return img


def probe_raw_decode(fixture_path, cache_dir, fid):
    """`probe --raw` of any fixture — stored pixels, no display transform.
    Kept separate from raw_decode() so heif_base can call it without
    recursing into itself."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"{fid}.{fsha(fixture_path)}.{bin_sha()}"
    out = cache_dir / f"{key}.rawref.png"
    if not out.exists():
        r = subprocess.run(
            [CM_BIN, "probe", str(fixture_path), str(out), "--raw"],
            capture_output=True)
        if r.returncode != 0 or not out.exists():
            raise SystemExit(
                f"{fid}: probe --raw failed: "
                f"{r.stderr.decode(errors='replace')[:200]}")
    return Image.open(out)


_BIN_SHA = None


def bin_sha():
    """Probe-binary identity — probe-derived caches (raw decodes, remuxed
    containers, extracted ICCs, PFM reconstructions) must not survive a
    binary change any more than ref_decode renders may."""
    global _BIN_SHA
    if _BIN_SHA is None:
        probe = shutil.which(CM_BIN) or CM_BIN
        _BIN_SHA = hashlib.sha256(Path(probe).read_bytes()).hexdigest()[:12]
    return _BIN_SHA


def raw_decode(fixture_path, cache_dir, fid, unmanaged=False):
    """Raw (stored code values) decode via compat-matrix probe --raw.

    Camera-raw extensions route to LibRaw instead (H-1): rep hypotheses for
    raw formats are graded against the format reference decoder, not zen.
    HEIF likewise routes to libheif (L-6): zen never supplies its own
    grading baseline."""
    if Path(fixture_path).suffix.lower() in RAW_EXTS:
        return libraw_decode(fixture_path, cache_dir, fid)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if str(fixture_path).lower().endswith((".heic", ".heif")):
        return heif_base(fixture_path, cache_dir, fid, unmanaged)
    key = f"{fid}.{fsha(fixture_path)}.{bin_sha()}"
    out = cache_dir / (f"{key}.unm.png" if unmanaged else f"{key}.png")
    if not out.exists():
        r = subprocess.run(
            [CM_BIN, "probe", str(fixture_path), str(out), "--raw"],
            capture_output=True,
        )
        # Loud failure: hypotheses must render from the same stored pixels
        # every time — silently switching decode paths makes them incomparable.
        if r.returncode != 0 or not out.exists():
            raise SystemExit(
                f"{fid}: raw decode failed: {r.stderr.decode(errors='replace')[:200]}"
            )
    return Image.open(out).convert("RGBA")


def embedded_icc(fixture_path, cache_dir, fid):
    """The fixture's own embedded ICC, or None."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{fid}.{fsha(fixture_path)}.{bin_sha()}.icc"
    if not out.exists():
        subprocess.run(
            [CM_BIN, "dump-icc", str(fixture_path), str(out)],
            check=True,
            capture_output=True,
        )
    data = out.read_bytes()
    return data if data else None


def kvs(spec, head):
    """Parse 'head:k=v;...' -> dict."""
    rest = spec[len(head) + 1:] if spec.startswith(head + ":") else ""
    d = {}
    for kv in rest.split(";"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            d[k] = v
    return d


def apply_orient(img, o):
    o = int(o)
    return img.transpose(ORIENT[o]) if o in ORIENT else img


def apply_icc(img, icc_bytes):
    """lcms2 relative-colorimetric transform of the colour channels.

    Picks the PIL input mode from the source profile's colour space
    (GRAY profiles on grayscale-signalled files, else RGB)."""
    src = ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))
    dst = ImageCms.createProfile("sRGB")
    try:
        gray = getattr(src.profile, "xcolor_space", "") == "GRAY"
    except Exception:
        gray = False
    if gray:
        out = ImageCms.profileToProfile(
            img.convert("L"), src, dst, outputMode="RGB",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        )
    else:
        out = ImageCms.profileToProfile(
            img.convert("RGB"), src, dst, outputMode="RGB",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
        )
    if img.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(img.getchannel("A"))
    return out


def src_icc_for(spec_color, embedded, icc_dir):
    """ICC bytes for the interpretation the hypothesis names."""
    # `srgb` is NOT an identity shortcut: the hypothesis "reader interprets
    # as sRGB" must round-trip through the real generated sRGB profile so a
    # malformed or wrong embedded profile can't masquerade as managed-sRGB.
    if spec_color in ("untagged", "none", "uncalibrated"):
        return None  # reader applies no transform — raw pixels out
    if spec_color == "embedded":
        return embedded  # fixture's own embedded profile or nothing
    # Always resolve by the NAMED interpretation — even when this hyp is
    # marked correct. A conflict fixture's correct hyp declares the winning
    # signal (e.g. cICP sRGB over iCCP P3); rendering it through the embedded
    # profile would make it identical to the losing interpretation.
    return (icc_dir / EQUIV[spec_color]).read_bytes()


def avif_mc_decode(fixture_path, cache_dir, fid, mc):
    """AVIF decoded through an explicit YCbCr matrix — the `mc=601`/`mc=709`
    hypothesis renders (r13 §2). ffmpeg dumps the coded YUV planes
    (matrix-agnostic — the seq-header/nclx matrix only enters at YUV→RGB),
    then the conversion applies the named matrix at the file's signalled
    range. Both hypotheses share the upsampler (chroma replicate) so the
    pair differs only in the matrix — a clean A/B measurement. ffmpeg is
    the reference decoder here; zen's own read never grades itself."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = Path(fixture_path).name
    # ffprobe reports the coded pix_fmt + signalled range; the rawvideo
    # dump carries the planes untouched (no -pix_fmt override).
    script = (
        f"cp '/f/{name}' /tmp/in.avif && "
        "ffprobe -v error -select_streams v:0 "
        "-show_entries stream=pix_fmt,color_range,width,height "
        "-of json /tmp/in.avif > '/out/{OUT}.yuv.json' && "
        "ffmpeg -y -v error -i /tmp/in.avif -f rawvideo "
        "'/out/{OUT}.yuv'")
    ck = hashlib.sha256(script.encode() + tool_key().encode())
    key = f"{fid}.{fsha(fixture_path)}.{ck.hexdigest()[:10]}"
    yuv = cache_dir / f"{key}.yuv"
    meta = cache_dir / f"{key}.yuv.json"
    if not (yuv.exists() and meta.exists()):
        tmpbase = Path(os.environ.get("CM_TMPDIR") or (Path.home() / "tmp"))
        tmpbase.mkdir(parents=True, exist_ok=True)
        ctr_tmp = Path(tempfile.mkdtemp(prefix="cm-ref-", dir=str(tmpbase)))
        try:
            r = subprocess.run(
                ["docker", "run", "--rm", "--network", "none",
                 "--read-only",
                 "--user", f"{os.getuid()}:{os.getgid()}",
                 "-v", f"{ctr_tmp}:/tmp", "-e", "HOME=/tmp",
                 "-v", f"{Path(fixture_path).resolve().parent}:/f:ro",
                 "-v", f"{yuv.parent.resolve()}:/out",
                 "--entrypoint", "/usr/bin/nice", REF_IMAGE,
                 "-n", "19", "bash", "-c",
                 script.replace("{OUT}", key)],
                capture_output=True)
            if r.returncode != 0 or not yuv.exists():
                raise SystemExit(
                    f"{fid}: yuv dump failed: "
                    f"{r.stderr.decode(errors='replace')[:300]}")
        finally:
            shutil.rmtree(ctr_tmp, ignore_errors=True)
    import json as _json
    m = _json.loads(meta.read_text())["streams"][0]
    w, h = int(m["width"]), int(m["height"])
    fmt = m.get("pix_fmt", "")
    limited = m.get("color_range") == "tv"
    data = yuv.read_bytes()
    if fmt == "yuv420p":
        depth, ss = 8, 2
    elif fmt == "yuv444p":
        depth, ss = 8, 1
    elif fmt == "yuv420p10le":
        depth, ss = 10, 2
    elif fmt == "yuv444p10le":
        depth, ss = 10, 1
    else:
        raise SystemExit(f"{fid}: unsupported yuv pix_fmt {fmt}")
    full = 255 if depth == 8 else 1023
    if depth == 8:
        yv = list(data[:w * h])
        cw, ch = (w + ss - 1) // ss, (h + ss - 1) // ss
        uv = list(data[w * h:w * h + cw * ch])
        vv = list(data[w * h + cw * ch:w * h + 2 * cw * ch])
    else:
        import array as _arr
        px = _arr.array("H")
        px.frombytes(data)
        if sys.byteorder == "big":
            px.byteswap()
        cw, ch = (w + ss - 1) // ss, (h + ss - 1) // ss
        yv = px[:w * h]
        uv = px[w * h:w * h + cw * ch]
        vv = px[w * h + cw * ch:w * h + 2 * cw * ch]
    # H.273 coefficients — spec value accepts the CICP code or the name.
    kr, kb = (0.2126, 0.0722) if mc in (1, 709) else (0.299, 0.114)
    if limited:
        ymin, ymax = (16, 235) if depth == 8 else (64, 940)
        cmin, cmax = (16, 240) if depth == 8 else (64, 960)
        ys, cs = ymax - ymin, cmax - cmin
    else:
        ymin, cmin, ys, cs = 0, 0, full, full
    img = Image.new("RGB", (w, h))
    out = img.load()
    for y in range(h):
        cy = y // ss
        for x in range(w):
            yn = (yv[y * w + x] - ymin) / ys
            un = (uv[cy * cw + x // ss] - cmin) / cs - 0.5
            vn = (vv[cy * cw + x // ss] - cmin) / cs - 0.5
            rr = yn + 2 * (1 - kr) * vn
            bb = yn + 2 * (1 - kb) * un
            gg = (yn - kr * rr - kb * bb) / (1 - kr - kb)
            out[x, y] = (
                min(255, max(0, round(rr * 255))),
                min(255, max(0, round(gg * 255))),
                min(255, max(0, round(bb * 255))),
            )
    return img.convert("RGBA")


def hdr_reconstruct(fixture_path, cache_dir, fid):
    """Linear HDR PFM via `probe --hdr` (zen gain-map reconstruction)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"{fid}.{fsha(fixture_path)}.{bin_sha()}"
    pfm = cache_dir / f"{key}.pfm"
    if not pfm.exists():
        subprocess.run(
            [CM_BIN, "probe", str(fixture_path), str(cache_dir / f"{key}.raw.png"),
             "--hdr", str(pfm)],
            check=True, capture_output=True,
        )
    data = pfm.read_bytes()
    # PFM: "PF\n<w> <h>\n<scale>\n<binary f32 RGB, bottom-up rows>"
    hdr_end = data.index(b"\n", data.index(b"\n", data.index(b"\n") + 1) + 1) + 1
    parts = data[:hdr_end].split()
    w, h = int(parts[1]), int(parts[2])
    import array
    px = array.array("f")
    px.frombytes(data[hdr_end:])
    img = Image.new("RGB", (w, h))
    # "gainmap-applied" SDR rendition (round-8 M7): gain map applied in
    # linear light on the base (the PFM is that product), then SDR-clipped
    # to 1.0 and encoded through the sRGB OETF — the output of a pipeline
    # that applies the map but has no HDR headroom.
    def oetf(v):
        v = max(0.0, min(1.0, v))
        return 12.92 * v if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055
    out = img.load()
    n = w * h
    for i in range(n):
        x, y = i % w, h - 1 - i // w  # PFM rows are bottom-up
        r, g, b = px[3 * i], px[3 * i + 1], px[3 * i + 2]
        out[x, y] = (
            min(255, round(255 * oetf(r))),
            min(255, round(255 * oetf(g))),
            min(255, round(255 * oetf(b))),
        )
    return img.convert("RGBA")


def _primaries_matrix(wx, wy, rx, ry, gx, gy, bx, by):
    """RGB->XYZ matrix from xy chromaticities (columns R, G, B), adapted
    to the sRGB D65 white by Bradford CAT when the declared white differs."""

    def col(x, y):
        return (x / y, 1.0, (1.0 - x - y) / y)

    def mat_mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
                for i in range(3)]

    def mat_vec(a, v):
        return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]

    def inv3(m):
        a, b, c = m[0]
        d, e, f = m[1]
        g, h, i = m[2]
        det = (a * (e * i - f * h) - b * (d * i - f * g)
               + c * (d * h - e * g))
        return [[(e * i - f * h) / det, (c * h - b * i) / det,
                 (b * f - c * e) / det],
                [(f * g - d * i) / det, (a * i - c * g) / det,
                 (c * d - a * f) / det],
                [(d * h - e * g) / det, (b * g - a * h) / det,
                 (a * e - b * d) / det]]

    rc, gc, bc = col(rx, ry), col(gx, gy), col(bx, by)
    m = [[rc[0], gc[0], bc[0]], [rc[1], gc[1], bc[1]],
         [rc[2], gc[2], bc[2]]]
    w = col(wx, wy)
    s = mat_vec(inv3(m), w)
    m = [[m[i][j] * s[j] for j in range(3)] for i in range(3)]
    d65 = col(0.3127, 0.3290)
    if abs(wx - 0.3127) > 0.001 or abs(wy - 0.3290) > 0.001:
        # Bradford CAT src-white -> D65
        brad = [[0.8951, 0.2664, -0.1614],
                [-0.7502, 1.7135, 0.0367],
                [0.0389, -0.0685, 1.0296]]
        ib = inv3(brad)
        ls, ms_, ss = mat_vec(brad, w)
        ld, md, sd = mat_vec(brad, d65)
        cat = mat_mul(ib, [[ld / ls, 0, 0], [0, md / ms_, 0],
                           [0, 0, sd / ss]])
        cat = mat_mul(cat, brad)
        m = mat_mul(cat, m)
    return m


# sRGB D65 primaries -> XYZ, inverse of the canonical XYZ->sRGB matrix.
_SRGB_TO_XYZ = [[0.4124, 0.3576, 0.1805],
                [0.2126, 0.7152, 0.0722],
                [0.0193, 0.1192, 0.9505]]
_XYZ_TO_SRGB = [[3.2406, -1.5372, -0.4986],
                [-0.9689, 1.8758, 0.0415],
                [0.0557, -0.2040, 1.0570]]


def png_gama_chrm_srgb(img, fixture_path):
    """The declared interpretation of a gAMA+cHRM-tagged fixture (r13 §1b):
    linearize the stored code values with the declared image gamma, move
    the declared-primaries RGB to sRGB primaries (D65), re-encode with the
    sRGB OETF. The declaration is read from the fixture's own chunks — the
    hypothesis is "honour what the file says", not a hardcoded profile."""
    import struct as _st
    data = open(fixture_path, "rb").read()
    gama = chrm = None
    i = 8
    while i + 12 <= len(data):
        ln, ty = _st.unpack(">I4s", data[i:i + 8])
        body = data[i + 8:i + 8 + ln]
        if ty == b"gAMA":
            gama = _st.unpack(">I", body)[0] / 100000.0
        elif ty == b"cHRM":
            v = _st.unpack(">8I", body)
            chrm = [x / 100000.0 for x in v]
        i += 12 + ln
    if gama is None or chrm is None:
        raise SystemExit(f"tag=gama-chrm: {fixture_path} lacks gAMA/cHRM")
    wx, wy, rx, ry, gx, gy, bx, by = chrm
    m = _primaries_matrix(wx, wy, rx, ry, gx, gy, bx, by)
    conv = [[sum(_XYZ_TO_SRGB[i][k] * m[k][j] for k in range(3))
             for j in range(3)] for i in range(3)]
    inv_g = 1.0 / gama

    def srgb_oetf(c):
        return (12.92 * c if c <= 0.0031308
                else 1.055 * (c ** (1 / 2.4)) - 0.055)

    src = img.convert("RGB")
    out = Image.new("RGB", src.size)
    spx, opx = src.load(), out.load()
    w, h = src.size
    for y in range(h):
        for x in range(w):
            r, g, b = spx[x, y]
            rl = (r / 255.0) ** inv_g
            gl = (g / 255.0) ** inv_g
            bl = (b / 255.0) ** inv_g
            sl = [max(0.0, min(1.0,
                               conv[i][0] * rl + conv[i][1] * gl
                               + conv[i][2] * bl)) for i in range(3)]
            opx[x, y] = tuple(
                min(255, round(255 * srgb_oetf(c))) for c in sl)
    if img.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(img.getchannel("A"))
    return out


def render_hyp(img, spec, embedded, icc_dir, expect_orient, colour_field,
               fixture_path=None, cache_dir=None, fid=None, stored_base=None):
    """Apply a hypothesis spec's transforms to the raw decode."""
    if spec in ("synth:stored", "synth:palette", "corpus:stored"):
        return stored_base if stored_base is not None else img
    if spec.endswith("tonemap=ultrahdr-hdr"):
        # "gain map applied" = HDR reconstruction clipped through the sRGB
        # OETF (the SDR-headed rendition — M7). Distinct from the SDR base:
        # the mid-tone boost band clips to 255.
        return hdr_reconstruct(fixture_path, cache_dir, fid)
    # tonemap=ultrahdr-sdr renders the stored SDR base — the raw decode,
    # which IS the same image as `stored` (documented collapse pair).
    if spec == "corpus:icc-range-ignored":
        # zen's measured reading on heic-colr-conflict-range (M-4): the
        # embedded prof is honoured but the nclx *range flag* is dropped —
        # the profile applies over the unexpanded (fully-unmanaged) base.
        if stored_base is None:
            raise SystemExit("icc-range-ignored requires the unmanaged base")
        icc = embedded or (
            icc_dir / EQUIV["conflict-nclx-srgb-vs-icc-p3"]).read_bytes()
        return apply_icc(stored_base, icc) if icc else stored_base
    if spec == "corpus:libheif-nclx":
        # "reader honours the declared nclx" — rendered by libheif itself so
        # the range flag is exercised honestly (the `corpus:color=srgb`
        # model is decode-neutral and can't express a limited-range decl).
        return libheif_decode(fixture_path, cache_dir, fid)
    if spec == "corpus:as-signalled":
        o = int(expect_orient)
        im = apply_orient(img, o) if o != 1 else img
        if colour_field in ("p3", "adobe", "embedded"):
            icc = embedded or (
                (icc_dir / EQUIV[colour_field]).read_bytes()
                if colour_field in EQUIV else None)
            return apply_icc(im, icc) if icc else im
        return im
    if spec.startswith("synth-baked:"):
        d = kvs(spec, "synth-baked")
        # stored pixels already carry bake `o`; the tag applies `orient`
        return apply_orient(img, d.get("orient", "1"))
    if spec.startswith("synth:") or spec.startswith("corpus:"):
        d = kvs(spec, "synth" if spec.startswith("synth:") else "corpus")
        if "mc" in d:
            # mc=601/709: decode through the named YCbCr matrix instead of
            # the fixture's signalled one — the base is the explicit ffmpeg
            # plane dump + matrix math, not the `raw` decode.
            img = avif_mc_decode(fixture_path, cache_dir, fid, int(d["mc"]))
        im = apply_orient(img, d.get("orient", "1"))
        if d.get("tag") == "gama-chrm":
            # honour the fixture's own gAMA+cHRM declaration (r13 §1b) —
            # a power-law gamma plus primaries the ICC path can't express
            # (Display P3 v4 carries the parametric sRGB TRC, not the
            # declared power curve — that reading is `p3-as-displayp3`).
            im = png_gama_chrm_srgb(im, fixture_path)
        c = d.get("color")
        if c:
            icc = src_icc_for(c, embedded, icc_dir)
            if icc:
                im = apply_icc(im, icc)
        a = d.get("alpha")
        if a == "ramp":
            im = im.convert("RGBA")
            w, h = im.size
            alpha = im.getchannel("A")
            px = alpha.load()
            for y in range(h):
                for x in range(w):
                    px[x, y] = (x * 255 // w) if y > h * 3 // 4 else 255
            im.putalpha(alpha)
        elif a == "flatten":
            # reader dropped alpha: RGB kept, opaque channel
            im = im.convert("RGB").convert("RGBA")
        return im
    raise ValueError(f"unknown spec: {spec}")


def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        i = args.index("--only")
        only = args[i + 1]
        args = args[:i] + args[i + 2:]
    fix = args[0]
    icc_dir = Path(fix) / "icc"
    cache = Path(fix) / "hyps" / ".cache"

    fixtures = {r["fixture"]: r for r in load_tsv(os.path.join(fix, "fixtures.tsv"))}
    hyps = load_tsv(os.path.join(fix, "hypotheses.tsv"))
    by_fx = {}
    for h in hyps:
        by_fx.setdefault(h["fixture"], []).append(h)

    n = 0
    for fid, frow in fixtures.items():
        if only and fid != only:
            continue
        fpath = os.path.join(fix, frow["file"])
        emb = embedded_icc(fpath, cache, fid)
        raw = None
        hyp_dir = os.path.join(fix, "hyps", fid)
        os.makedirs(hyp_dir, exist_ok=True)
        for h in by_fx.get(fid, []):
            if raw is None:
                # Loud: a stale or substituted render is worse than none —
                # the classifier trusts these files to be honest.
                raw = raw_decode(fpath, cache, fid)
            # `corpus:stored`/`corpus:icc-range-ignored` need the
            # fully-unmanaged base on heic (nclx and prof both stripped);
            # for everything else it equals `raw`.
            stored_base = raw
            is_heif = str(fpath).lower().endswith((".heic", ".heif"))
            if is_heif and any(
                h["spec"].split(":")[-1] in ("stored", "icc-range-ignored")
                for h in by_fx.get(fid, [])
            ):
                stored_base = raw_decode(fpath, cache, fid, unmanaged=True)
            # UltraHDR `gainmap-applied`: the generator emits the true
            # applied rendition (its own linear HDR buffer, clipped + OETF)
            # into hyps/<fid>/ — probe --hdr can't parse ISO 21496-1 APP2
            # params and would render boost=1.0 there. The generator's asset
            # is the decoder-independent ground truth; load it verbatim.
            asset = os.path.join(fix, "hyps", fid, h["hypothesis"] + ".png")
            if h["spec"].endswith("tonemap=ultrahdr-hdr") and os.path.exists(asset):
                im = Image.open(asset).convert("RGBA")
                im.save(asset)
                n += 1
                continue
            try:
                im = render_hyp(
                    raw, h["spec"], emb, icc_dir,
                    frow["expect_orient"], frow["colour"],
                    fixture_path=fpath, cache_dir=cache, fid=fid,
                    stored_base=stored_base,
                )
            except Exception as e:
                raise SystemExit(f"{fid}/{h['hypothesis']}: render failed: {e}")
            im.save(os.path.join(hyp_dir, h["hypothesis"] + ".png"))
            n += 1
        print(f"{fid}: {len(by_fx.get(fid, []))} hyps")
    print(f"rendered {n} hypothesis PNGs")


if __name__ == "__main__":
    main()
