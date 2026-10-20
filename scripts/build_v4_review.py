#!/usr/bin/env python3
"""Build the imazen-26 v4 Review page (an artifact page) from a render v4 output.

    build_v4_review.py images <render-dir> <stage-dir> [--jobs N]
        Thumbnail sheets and previews up to 1600 px (quality 80) of every SDR image's png-srgb file
        (sRGB, orientation baked), and full-resolution WebPs (quality 75) of the images larger
        than that, with tools/corpus-thumbs (zen crates only): <stage>/work/sheets/, work/medium/,
        work/full/.
    build_v4_review.py fullpacks <render-dir> <stage-dir>
        The full-resolution WebPs concatenated into packs of about 8 MiB for the artifact's
        asset store (1 GiB, 5,000 files): <stage>/work/fullpacks/fp_NNN.webp and fullpacks.tsv
        (id, pack, offset, length, width, height).
    build_v4_review.py data <render-dir> <stage-dir> [--fullpack-urls TSV] [--hash-urls TSV]
        The page and its data: v4-review.html (scripts/v4_review_page.html), data/index.json,
        data/dNN.json (details, 100 images each), thumbs/sheet_NN.webp, packs/pack_NN.webp
        (the medium previews concatenated; the index gives each one's offset and length) and
        hashes/decoded-xxh3-NN.txt (the hash file in parts of at most 12 MB). --fullpack-urls
        maps each full-resolution pack to the asset URL its Artifact upload returned
        (fp_NNN.webp<TAB>url); --hash-urls does the same for the hash parts, with each part's
        sha256 (decoded-xxh3-NN.txt<TAB>sha256<TAB>url), and the build stops if a part changed.
    build_v4_review.py site <render-dir> <stage-dir> <site-dir> [--no-census]
        The same page as a static site for any web host (scripts/deploy_v4_review_site.sh puts it
        on Cloudflare Pages): <site>/index.html (the page, with the artifact runtime replaced:
        marks read-only, the hash download saved by the browser), data/, thumbs/, packs/, hashes/
        and the full-resolution packs as fullpacks/fp_NNN.webp, all under relative paths. Run
        `images` and `fullpacks` first.
    build_v4_review.py census <render-dir> png|jxl
        The reader census's verdicts for one format, counted per reader and outcome, with an
        example of each unexplained one.

The details join the render's reports: manifests/, list.tsv (provenance), readback.tsv,
jxl-check.tsv, byte-scan-<layer>.tsv, inventory-full.tsv (every part of every file),
decode-check/ (render_v4_decode_check.sh), decoded-xxh3.tsv, compat-census/
(render_v4_compat_census.py) and imi-check.tsv (status only), plus the repository's
manifests for the originals.
"""
import argparse
import collections
import csv
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THUMBS = os.path.join(REPO, "tools", "corpus-thumbs", "target", "release", "corpus-thumbs")
CELL, COLS, PER_SHEET, CHUNK = 256, 10, 100, 100


def tsv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader((l for l in f if not l.startswith("#")), delimiter="\t"))


def sdr_rows(render):
    """The png-srgb SDR file of every rendered image, in id order."""
    rows = [r for r in tsv(os.path.join(render, "manifests", "png-srgb.tsv")) if r["form"] != "hdr-pq"]
    return sorted(rows, key=lambda r: r["id"])


def cmd_images(a):
    work = os.path.join(a.stage, "work")
    rows = sdr_rows(a.render)
    lines = [f"{r['id']}\t{a.render}/{r['path']}\tsrgb\n" for r in rows]
    os.makedirs(os.path.join(work, "sheets"), exist_ok=True)
    # Sheets: one corpus-thumbs run per 100 ids, in parallel.
    jobs = []
    for n in range(0, len(lines), PER_SHEET):
        lst = os.path.join(work, "sheets", f"sheet_{n // PER_SHEET:02d}.list")
        open(lst, "w").writelines(lines[n:n + PER_SHEET])
        jobs.append([THUMBS, lst, os.path.join(work, "sheets", f"sheet_{n // PER_SHEET:02d}")])
    run_parallel(jobs, a.jobs, os.path.join(work, "sheets.log"))
    # Full resolution only where the 1600 px preview is smaller than the image; quality 75 keeps
    # the 1,000 such images (11,137 MP) inside the artifact's 1 GiB asset quota (a 40-image
    # sample measured 0.079 bytes per pixel).
    # The published files hold up to 256 MB: images up to 1600 px get their full size there
    # (quality 80), larger ones a 1024 px preview (quality 78) and their full resolution in the
    # asset store.
    big = [l for l, r in zip(lines, rows) if max(int(r["width"]), int(r["height"])) > 1600]
    small = [l for l in lines if l not in set(big)]
    tiers = (("medium", [(small, 1600, 80), (big, 1024, 78)]), ("full", [(big, 16383, 75)]))
    for tier, runs in tiers:
        d = os.path.join(work, tier)
        os.makedirs(d, exist_ok=True)
        jobs, parts = [], []
        for n, (todo, size, quality) in enumerate(runs):
            for k in range(a.jobs):
                part = todo[k::a.jobs]
                if not part:
                    continue
                name = f"part-{n}-{k:02d}"
                lst = os.path.join(d, f"{name}.list")
                open(lst, "w").writelines(part)
                jobs.append([THUMBS, "--preview", str(size), str(quality), lst, os.path.join(d, name)])
                parts.append(name)
        run_parallel(jobs, a.jobs, os.path.join(work, f"{tier}.log"))
        # Gather the parts' files and TSVs into one directory and one previews.tsv.
        head, body = None, []
        for name in parts:
            pd = os.path.join(d, name)
            if not os.path.isdir(pd):
                continue
            for f in os.listdir(pd):
                if f.endswith(".webp"):
                    os.replace(os.path.join(pd, f), os.path.join(d, f))
            t = open(os.path.join(pd, "previews.tsv")).read().splitlines()
            head, body = t[0], body + t[1:]
            shutil.rmtree(pd)
        open(os.path.join(d, "previews.tsv"), "w").write("\n".join([head] + sorted(body)) + "\n")
        bad = [l for l in body if l.split("\t")[-1]]
        total = sum(int(l.split("\t")[3]) for l in body)
        print(f"{tier}: {len(body)} images, {total / 1e6:.1f} MB, {len(bad)} failed", file=sys.stderr)


def cmd_fullpacks(a):
    work = os.path.join(a.stage, "work")
    full = {r["id"]: r for r in tsv(os.path.join(work, "full", "previews.tsv")) if not r["error"]}
    out = os.path.join(work, "fullpacks")
    os.makedirs(out, exist_ok=True)
    rows, pack, buf = [], 0, bytearray()
    for i in sorted(full):
        data = open(os.path.join(work, "full", f"{i}.webp"), "rb").read()
        if buf and len(buf) + len(data) > 8 << 20:
            open(os.path.join(out, f"fp_{pack:03d}.webp"), "wb").write(buf)
            pack, buf = pack + 1, bytearray()
        rows.append(f"{i}\t{pack}\t{len(buf)}\t{len(data)}\t{full[i]['w']}\t{full[i]['h']}\n")
        buf += data
    if buf:
        open(os.path.join(out, f"fp_{pack:03d}.webp"), "wb").write(buf)
    open(os.path.join(out, "fullpacks.tsv"), "w").writelines(["id\tpack\toffset\tlength\twidth\theight\n"] + rows)
    total = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out) if f.endswith(".webp"))
    print(f"{len(rows)} images in {pack + 1} packs, {total / 1e6:.1f} MB", file=sys.stderr)


def run_parallel(cmds, n, log):
    with open(log, "a") as lf:
        procs = []
        for c in cmds:
            procs.append(subprocess.Popen(["nice", "-n", "19"] + c, stdout=lf, stderr=lf))
            while sum(p.poll() is None for p in procs) >= n:
                procs[[p.poll() is None for p in procs].index(True)].wait()
        for p in procs:
            p.wait()
        failed = [c for c, p in zip(cmds, procs) if p.returncode]
        if failed:
            sys.exit(f"{len(failed)} runs failed; see {log}")


def meta(render):
    out = {}
    for line in open(os.path.join(render, "RUN.meta")):
        k, _, v = line.rstrip("\n").partition("\t")
        out.setdefault(k, []).append(v)
    return out


def jxl_codestream_head(path, n=512):
    """The first n bytes of a JPEG XL file's codestream: the file itself, or its jxlc box or its
    jxlp boxes joined."""
    with open(path, "rb") as f:
        if f.read(2) == b"\xff\x0a":
            f.seek(0)
            return f.read(n)
        size, pos, out = os.fstat(f.fileno()).st_size, 0, bytearray()
        while pos + 8 <= size and len(out) < n:
            f.seek(pos)
            h = f.read(16)
            length, kind = struct.unpack(">I4s", h[:8])
            head = 8
            if length == 1:
                length, head = struct.unpack(">Q", h[8:16])[0], 16
            elif length == 0:
                length = size - pos
            if kind in (b"jxlc", b"jxlp"):
                skip = head + (4 if kind == b"jxlp" else 0)  # a jxlp box starts with its index
                f.seek(pos + skip)
                out += f.read(min(length - skip, n - len(out)))
            pos += length
        return bytes(out)


def jxl_bits_per_sample(path):
    """The bits per sample a JPEG XL file's codestream header states (ISO/IEC 18181-1: the
    SizeHeader, then the ImageMetadata up to its BitDepth)."""
    b, pos = jxl_codestream_head(path), 0

    def u(n):
        nonlocal pos
        v = 0
        for k in range(n):
            v |= (b[pos >> 3] >> (pos & 7) & 1) << k
            pos += 1
        return v

    def u32(*d):  # each choice is a value, or (bits, offset)
        c = d[u(2)]
        return c if isinstance(c, int) else u(c[0]) + c[1]

    def size_header():
        small = u(1)
        _ = u(5) if small else u32((9, 1), (13, 1), (18, 1), (30, 1))
        if u(3) == 0:
            _ = u(5) if small else u32((9, 1), (13, 1), (18, 1), (30, 1))

    if u(16) != 0x0AFF:
        raise ValueError(f"{path}: no JPEG XL codestream signature")
    size_header()
    if u(1):  # all_default
        return 8
    if u(1):  # extra_fields
        u(3)  # orientation
        if u(1):  # intrinsic size
            size_header()
        if u(1):  # preview
            d = (16, 32, (5, 1), (9, 33)) if u(1) else ((6, 1), (8, 65), (10, 321), (12, 1345))
            u32(*d)
            if u(3) == 0:
                u32(*d)
        if u(1):  # animation
            u32(100, 1000, (10, 1), (30, 1)), u32(1, 1001, (8, 1), (10, 1)), u32(0, (3, 0), (16, 0), (32, 0)), u(1)
    if u(1):  # float samples
        return u32(32, 16, 24, (6, 1))
    return u32(8, 10, 12, (6, 1))


def jxl_census_info(R, paths, jxlcheck):
    """What the census verdicts need of each JPEG XL file: its bits per sample and whether it is
    gray (jxl-check.tsv's colour)."""
    return {p: {"bits": jxl_bits_per_sample(os.path.join(R, p)),
                "gray": jxlcheck.get(p, {}).get("colour", "").startswith("Grayscale")}
            for p in paths if p.endswith(".jxl")}


def cmd_data(a):
    R, S = a.render, getattr(a, "site", "") or a.stage
    work = os.path.join(a.stage, "work")
    for d in ("data", "thumbs", "packs"):
        os.makedirs(os.path.join(S, d), exist_ok=True)
    layers = ("png-p3", "png-srgb", "jxl-p3", "jxl-srgb")
    man = {l: tsv(os.path.join(R, "manifests", f"{l}.tsv")) for l in layers}
    by_id = collections.defaultdict(list)
    for l in layers:
        for r in man[l]:
            by_id[r["id"]].append(dict(r, layer=l))
    prov = {}
    for line in open(os.path.join(R, "list.tsv")):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 4:
            prov[f[0]] = json.loads(f[3])
    orig = {}
    for b in ("train", "validate", "test"):
        for r in tsv(os.path.join(REPO, "manifests", f"{b}.tsv")):
            orig["1" + r["id"]] = r
    corpus = {"1" + r["number"]: r for r in tsv(os.path.join(REPO, "CORPUS-MANIFEST.tsv"))}

    # Per-path report rows.
    readback = {r["path"]: r for r in tsv(os.path.join(R, "readback.tsv"))}
    jxlcheck = {r["path"]: r for r in tsv(os.path.join(R, "jxl-check.tsv"))}
    bytescan = {}
    for l in layers:
        for r in tsv(os.path.join(R, f"byte-scan-{l}.tsv")):
            bytescan[f"{l}/{r['path']}"] = (r["findings"], r["allowed"])
    inv = collections.defaultdict(list)
    inv_file = os.path.join(R, "inventory-full.tsv")
    if os.path.exists(inv_file):
        with open(inv_file, newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                p = os.path.relpath(r["file"], R)
                inv[p].append([int(r["offset"] or 0), int(r["length"] or 0), int(r["depth"] or 0), r["kind"], r["tag"],
                               r["disposition"], r["label"]])
    dc = {r["path"]: r for r in tsv(os.path.join(R, "decode-check", "report.tsv"))}
    gms = {r["path"]: r for r in tsv(os.path.join(R, "decode-check", "gain-maps.tsv"))}
    hashes = collections.defaultdict(list)
    for r in tsv(os.path.join(R, "decoded-xxh3.tsv")):
        hashes[r["path"]].append([r["decoder"], int(r["width"] or 0), int(r["height"] or 0), r["channels"], r["bits"],
                                  r["xxh3"], r["gm_xxh3"]])
    imi = {}
    for r in tsv(os.path.join(R, "imi-check.tsv")):
        imi[r["path"].replace("imi-", "png-", 1).removesuffix(".imi") + ".png"] = [r["imij"], r["oracle"], r["metadata"], r["gain_map"]]
    census = collections.defaultdict(list)
    alias = collections.defaultdict(list)
    for r in ([] if a.no_census else tsv(os.path.join(R, "compat-census", "aliases.tsv"))):
        alias[r["sha256"]].append(r["path"])
    census_rows = [] if a.no_census else tsv(os.path.join(R, "compat-census", "census.tsv"))
    for r in census_rows:
        census[r["sha256"]].append(r)
    jxl_seen, jxl_ok = collections.Counter(), collections.Counter()
    for r in census_rows:
        if r["path"].endswith(".jxl"):
            jxl_seen[(r["image"], r["reader"])] += 1
            jxl_ok[(r["image"], r["reader"])] += r["status"] == "ok"
    jxl_support = {k: jxl_ok[k] / n for k, n in jxl_seen.items()}
    jxl_info = jxl_census_info(R, {r["path"] for r in census_rows}, jxlcheck)
    form_of ={f["path"]: f["form"] for rows_ in by_id.values() for f in rows_}
    pixels_of = {f["path"]: int(f["width"]) * int(f["height"]) for rows_ in by_id.values() for f in rows_}

    # Images, in id order, with their sheet cells and previews.
    sheet_cells = {}
    for f in sorted(os.listdir(os.path.join(work, "sheets"))):
        if f.endswith(".tsv"):
            n = int(f[6:8])
            for r in tsv(os.path.join(work, "sheets", f)):
                if not r.get("error"):
                    sheet_cells[r["id"]] = [n, int(r["col"]) * CELL, int(r["row"]) * CELL]
            shutil.copy(os.path.join(work, "sheets", f[:-4] + ".webp"), os.path.join(S, "thumbs", f[:-4] + ".webp"))
    medium = {r["id"]: r for r in tsv(os.path.join(work, "medium", "previews.tsv"))}
    full_of = {}
    if a.fullpack_urls:
        urls = {}
        for line in open(a.fullpack_urls):
            k, _, v = line.rstrip("\n").partition("\t")
            urls[int(k.removeprefix("fp_").removesuffix(".webp"))] = v
        for r in tsv(os.path.join(work, "fullpacks", "fullpacks.tsv")):
            full_of[r["id"]] = [urls[int(r["pack"])], int(r["offset"]), int(r["length"]), int(r["width"]), int(r["height"])]
    # Packs of medium previews, about 12 MB each.
    pack_of, pack, buf = {}, 0, bytearray()
    for r in sdr_rows(R):
        i = r["id"]
        data = open(os.path.join(work, "medium", f"{i}.webp"), "rb").read()
        if buf and len(buf) + len(data) > 12_000_000:
            open(os.path.join(S, "packs", f"pack_{pack:02d}.webp"), "wb").write(buf)
            pack, buf = pack + 1, bytearray()
        pack_of[i] = [pack, len(buf), len(data), int(medium[i]["w"]), int(medium[i]["h"])]
        buf += data
    if buf:
        open(os.path.join(S, "packs", f"pack_{pack:02d}.webp"), "wb").write(buf)

    classes = sorted({r["path"].split("/")[1] for r in sdr_rows(R)})
    images, details = [], {}
    tally = collections.Counter()
    for n, r in enumerate(sdr_rows(R)):
        i = r["id"]
        files = sorted(by_id[i], key=lambda f: (layers.index(f["layer"]), f["form"]))
        p3 = next(f for f in files if f["layer"] == "png-p3" and f["form"] != "hdr-pq")
        jxl = next((f for f in files if f["layer"] == "jxl-p3" and not f["form"].endswith("pq")), None)
        o = orig.get(i, {})
        title = corpus.get(i, {}).get("descriptor", "").replace("-", " ") or os.path.basename(r["path"]).split("_")[2]
        det_files, issue = [], False
        for f in files:
            p = f["path"]
            d = {k: f[k] for k in ("layer", "path", "form", "bytes", "sha256", "pixels_sha256", "colour", "clipped",
                                   "gain_map", "headroom_stops", "diffuse_white_nits", "max_cll", "max_fall", "jhgm",
                                   "jpeg_rebuild_sha256", "tool_commit") if f.get(k)}
            d["bytes"] = int(f["bytes"])
            if p in inv:
                d["inv"] = inv[p]
            if p in readback:
                rb = readback[p]
                d["readback"] = [rb["chunks"], rb["pngfix"], rb["pillow"], rb["magick"], rb["pngtopnm"]]
                issue |= any(not x.startswith(("ok", "opened")) for x in d["readback"])
            if p in jxlcheck:
                d["jxlcheck"] = [jxlcheck[p]["result"], jxlcheck[p]["colour"] or jxlcheck[p]["error"]]
                issue |= not jxlcheck[p]["result"].startswith("ok")
            if p in bytescan:
                d["bytescan"] = list(bytescan[p])
                issue |= bool(bytescan[p][0])
            if p in dc:
                d["decode"] = [dc[p]["all_decode"], dc[p]["same_as_png_twin"], dc[p]["agreeing_decoders"]]
                issue |= dc[p]["all_decode"] != "yes" or dc[p]["same_as_png_twin"] == "no"
            if p in gms:
                g = gms[p]
                d["gm"] = [g["lines_up"], g["metadata_same_in_decoders"], g["metadata_same_as_form"],
                           g["max_diff_vs_form_zenjxl_jxlrs_libjxl"]]
                d["hdr"] = [g["hdr_status"], g["hdr_stops_p50"], g["hdr_stops_p999"], g["hdr_stops_max"]]
                issue |= g["lines_up"] != "yes" or g["metadata_same_in_decoders"] != "yes"
            if p in hashes:
                d["xxh3"] = hashes[p]
            if p in imi:
                d["imi"] = imi[p]
                issue |= any(x != "ok" for x in imi[p][:2])
            det_files.append(d)
        cen = []
        for sha in dict.fromkeys(f["sha256"] for f in files):
            rows = census.get(sha, [])
            if not rows:
                continue
            paths = alias.get(sha, [])
            form = form_of.get(rows[0]["path"], "")
            # The bitmap a reader allocates: our decode's channels and sample size.
            ours = next((h for h in hashes.get(rows[0]["path"], []) if h[0] in ("zenpng", "zenjxl")), None)
            px_bytes = (1 if ours and ours[3] == "1" else 4) * (2 if ours and int(ours[4] or 8) > 8 else 1)
            vs = [verdict(c, form, jxl_support, pixels_of.get(rows[0]["path"], 0) * px_bytes, jxl_info.get(c["path"]))
                  for c in rows]
            for (label, problem), c in zip(vs, rows):
                fmt_ = "jxl" if c["path"].endswith(".jxl") else "png"
                tally[(fmt_, "problem" if problem else "exact" if label.startswith("exact")
                       else "refused" if c["status"] != "ok" else "expected")] += 1
            cen.append({"layer": rows[0]["layer"], "path": rows[0]["path"], "also": [x for x in paths if x != rows[0]["path"]],
                        "rows": [[f"{c['image']} {c['reader']} {short_version(c['version'])}".strip(), c["status"], c["same"],
                                  c["max_diff"], c["srgb_twin_same"], c["srgb_twin_max_diff"],
                                  int(float(c["ms"])) if c["ms"] else "", c["error"][:160], v[0], int(v[1])]
                                 for c, v in zip(rows, vs)]})
            issue |= any(v[1] for v in vs)
        details[i] = {"prov": prov.get(i, {}), "files": det_files, "census": cen,
                      "hdr": next((f["gain_map"] for f in files if f.get("gain_map")), ""),
                      "orig": {"path": o.get("path", ""), "format": o.get("format", ""), "bytes": int(o.get("bytes_actual") or 0),
                               "sha256": o.get("sha256", "")}}
        images.append({
            "id": i, "c": classes.index(r["path"].split("/")[1]), "b": r["bucket"],
            "lic": r["license"], "w": int(r["width"]), "h": int(r["height"]), "col": p3["colour"],
            "a": p3.get("source_alpha", ""), "hdr": any(f["form"] == "hdr-pq" for f in files),
            "jpeg": bool(jxl and jxl["form"].startswith("jpeg-in-jxl")), "t": title,
            "s": sheet_cells.get(i, [0, 0, 0]), "p": pack_of[i], "z": full_of.get(i, ""), "k": n // CHUNK,
            "o": o.get("raw_url", ""), "issue": issue,
        })
    for k in range(0, len(images), CHUNK):
        chunk = {im["id"]: details[im["id"]] for im in images[k:k + CHUNK]}
        json.dump(chunk, open(os.path.join(S, "data", f"d{k // CHUNK:02d}.json"), "w"), separators=(",", ":"))

    # The hash file: our decoders' rows (decoded-xxh3.tsv) plus every census reader's, one row per
    # path (a census row covers every path with the same bytes). It is kept beside the render as
    # decoded-xxh3-with-readers.tsv.
    src = os.path.join(R, "decoded-xxh3.tsv")
    head, body = [], []
    for line in open(src):
        (head if line.startswith("#") else body).append(line)
    cols = body[0].rstrip("\n").split("\t")
    out_cols = cols[:9] + ["rgba8_xxh3", "same_as_ours"] + cols[9:]
    lines = [l.rstrip("\n").split("\t") for l in body[1:]]
    rows = [r[:9] + ["", ""] + r[9:] for r in lines]
    for r in census_rows:
        for p in alias.get(r["sha256"], [r["path"]]):
            rows.append([p.split("/")[0], p, f"{r['image']} {r['reader']} {short_version(r['version'])}".strip(), r["status"],
                         r["width"], r["height"], r["channels"], r["bits"], r["xxh3"], r["rgba8_xxh3"], r["same"],
                         "", "", "", "", "", ""])
    rows.sort(key=lambda r: (r[1], r[2]))
    head.append("# rgba8_xxh3 and same_as_ours are for the Docker readers of the compatibility census: the\n"
                "# reader's bitmap as 8-bit RGBA, and whether it equals our decode (native: same samples and\n"
                "# layout; rgba8: same once both are 8-bit RGBA; no: differs).\n")
    text = "".join(head) + "\t".join(out_cols) + "\n" + "".join("\t".join(r) + "\n" for r in rows)
    open(os.path.join(R, "decoded-xxh3-with-readers.tsv"), "w").write(text)
    # Artifacts serve text up to 16 MB a file: parts of at most 12 MB, split at line ends, in
    # <stage>/hashes/; the page joins them for the download. With --hash-urls (part name, sha256
    # and URL per line: the parts uploaded to the artifact's asset store, which keeps their 40 MB
    # out of the version's 256 MiB) the index points at those URLs instead.
    hdir = os.path.join(S, "hashes")
    os.makedirs(hdir, exist_ok=True)
    for d in (hdir, os.path.join(S, "data")):  # data/ held the parts before 2026-10-17
        for f in os.listdir(d):
            if f.startswith("decoded-xxh3"):
                os.remove(os.path.join(d, f))
    parts, part, size = [], [], 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > 12_000_000 and part:
            parts.append("".join(part)); part, size = [], 0
        part.append(line); size += len(line)
    parts.append("".join(part))
    names = [f"decoded-xxh3-{k:02d}.txt" for k in range(len(parts))]
    for n, t in zip(names, parts):
        open(os.path.join(hdir, n), "w").write(t)
    if a.hash_urls:
        uploaded = {}
        for line in open(a.hash_urls):
            n, sha, url = line.rstrip("\n").split("\t")
            uploaded[n] = (sha, url)
        hash_files = []
        for n in names:
            sha = hashlib.sha256(open(os.path.join(hdir, n), "rb").read()).hexdigest()
            if uploaded.get(n, ("",))[0] != sha:
                sys.exit(f"hashes/{n} (sha256 {sha}) is not the part {a.hash_urls} names; upload it and update the file")
            hash_files.append(uploaded[n][1])
    else:
        hash_files = [f"hashes/{n}" for n in names]
    n_hash_rows = len(rows)

    m = meta(R)
    summary = build_summary(R, m, man, images, census_rows, n_hash_rows, tally)
    licences = [l for l, _ in collections.Counter(im["lic"] for im in images).most_common()]
    index = {"cell": CELL, "sheetW": CELL * COLS, "classes": classes, "licences": licences, "images": images,
             "summary": summary, "hashesFiles": hash_files, "footer": FOOTER}
    json.dump(index, open(os.path.join(S, "data", "index.json"), "w"), separators=(",", ":"))
    shutil.copy(os.path.join(REPO, "scripts", "v4_review_page.html"), os.path.join(S, "v4-review.html"))
    sizes = {d: sum(os.path.getsize(os.path.join(S, d, f)) for f in os.listdir(os.path.join(S, d)))
             for d in ("data", "thumbs", "packs")}
    print(f"{len(images)} images; " + ", ".join(f"{d} {v / 1e6:.1f} MB" for d, v in sizes.items()), file=sys.stderr)


# What a static host can give the page of the artifact runtime: no shared marks (the page then
# says marks are unavailable and works read-only, and the mark button is hidden) and the hash
# download saved by the browser. The empty icon keeps browsers from asking for /favicon.ico.
SITE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<link rel="icon" href="data:,">
<style>#vmark { display: none; }</style>
<script>
window.claude = { use: async name => name !== 'downloads' ? null : { save: async ({ filename, data }) => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(data); a.download = filename;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  return { status: 'saved' };
} } };
</script>
</head>
<body>
"""


def cmd_site(a):
    site = a.site = os.path.abspath(a.site)
    for d in ("data", "thumbs", "packs", "hashes", "fullpacks"):
        shutil.rmtree(os.path.join(site, d), ignore_errors=True)
    os.makedirs(os.path.join(site, "fullpacks"))
    src = os.path.join(a.stage, "work", "fullpacks")
    urls = os.path.join(a.stage, "work", "site-fullpack-urls.tsv")
    with open(urls, "w") as f:
        for n in sorted(os.listdir(src)):
            if n.endswith(".webp"):
                shutil.copy(os.path.join(src, n), os.path.join(site, "fullpacks", n))
                f.write(f"{n}\tfullpacks/{n}\n")
    a.fullpack_urls, a.hash_urls = urls, ""
    cmd_data(a)
    os.remove(os.path.join(site, "v4-review.html"))
    page = open(os.path.join(REPO, "scripts", "v4_review_page.html")).read()
    open(os.path.join(site, "index.html"), "w").write(SITE_HEAD + page + "\n</body>\n</html>\n")
    # Without a 404 page, Cloudflare Pages answers a missing path with index.html and status 200.
    open(os.path.join(site, "404.html"), "w").write(
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>Not found</title></head>\n'
        '<body><p>Not found. The review is at <a href="/">the start page</a>.</p></body></html>\n')


# QImageReader.allocationLimit() in MB in imazen26-compat:lts and :latest, read 2026-10-16. Both
# read the 108 MP 11415 with QT_IMAGEIO_MAXALLOC=1024 and refuse it without.
QT_DEFAULT_ALLOC_MB = {"6.4.2": 128, "6.11.2": 256}


def verdict(c, form, jxl_support, bitmap_bytes=0, jxl=None):
    """What a census row means: (label, problem?). bitmap_bytes: the decoded image's size; jxl: a
    JPEG XL file's jxl_census_info entry."""
    jxl = jxl or {}
    if c["status"] in ("crash", "unreadable-output"):
        return c["status"], True
    if c["status"] != "ok":
        if "readback returned all-zero" in c["error"]:
            return "canvas readback failed (WebKit)", False
        if c["reader"] == "qt":
            said = re.search(r"allocation limit of (\d+) megabytes", c["error"])
            v = re.search(r"Qt (\d+\.\d+\.\d+)", c["version"])
            limit = int(said[1]) if said else QT_DEFAULT_ALLOC_MB.get(v[1] if v else "")
            if limit and (said or ("Unable to read image data" in c["error"] and bitmap_bytes > limit << 20)):
                return f"over Qt's default {limit} MB image limit", False
        if c["path"].endswith(".jxl") and jxl_support.get((c["image"], c["reader"]), 0) < 0.5:
            return "no JPEG XL support", False
        # GraphicsMagick 1.3.42 and 1.3.48 ("Invalid colormap index", "An error has occurred
        # reading from file") and OpenCV 5.0 read every other JPEG XL file but not the 1-bit
        # patent pages, which djxl 0.12, ffmpeg 9, ImageMagick 7, vips 8.15 and 8.18, WebKit and
        # glycin read exactly, as our three decoders do.
        if jxl.get("bits") == 1:
            return "1-bit JPEG XL not read", False
        return "error", True
    if c["same"] == "native":
        return "exact", False
    if c["same"] == "rgba8":
        return "exact as 8-bit RGBA", False
    md = int(c["max_diff"]) if c["max_diff"] else 99
    if c["same"] == "stored":
        # ImageMagick and GraphicsMagick read a JPEG XL file's orientation as metadata and hand
        # back the stored pixels; the differences are against our decode in that orientation.
        if md <= 1 or (form.startswith("jpeg-in-jxl") and md <= 6):
            return f"orientation not applied (±{md})" if md else "orientation not applied (pixels exact)", False
        return f"orientation not applied, differs (±{md})", True
    if form in ("hdr-pq", "lossless-pq"):
        return "HDR shown differently (tone map or 8-bit)", False
    if c["srgb_twin_same"] == "within":
        # A wide-gamut JPEG-in-JXL file against our decode converted to sRGB, within what a decode
        # one code value from ours becomes after the conversion (jxl-decode-check srgb_of).
        return f"colour-managed to sRGB (±{c['srgb_twin_max_diff']}, within tolerance)", False
    if c["srgb_twin_max_diff"] != "" and int(c["srgb_twin_max_diff"]) <= 2:
        return f"colour-managed to sRGB (twin ±{c['srgb_twin_max_diff']})", False
    if md <= 1:
        return "rounding (±1)", False
    # libjxl 0.7's djxl writes a 1-bit image into an 8-bit PNG unscaled, as 0 and 1; djxl 0.12
    # writes 0 and 255, and libjxl 0.7 under vips 8.15 reads the same files exactly.
    if (c["image"], c["reader"]) == ("lts", "djxl") and jxl.get("bits") == 1 and md == 254:
        return "1-bit samples written as 0 and 1 (djxl 0.7)", False
    # glycin 2.1.5 (gdk-pixbuf 2.44.7) decodes a gray JPEG XL file with the sRGB curve its header
    # states but re-encodes it with a gamma 2.2 curve (twice the value below 8): up to 9 code
    # values lighter in the shadows, within 1 above 73. Checked 2026-10-17 on the 37 gray
    # JPEG-in-JXL files and on gray lossless and lossy files from cjxl; gray PNG reads exactly.
    if c["reader"] == "gdkpixbuf" and jxl.get("gray") and md <= 10:
        return f"gray re-encoded with gamma 2.2 (glycin, ±{md})", False
    if form.startswith("jpeg-in-jxl") and md <= 6:
        return f"JPEG decoding (±{md})", False
    return f"differs (±{md})", True


def short_version(v):
    """A reader's version string, shortened for a table cell."""
    v = v.replace("Version: ", "").replace("pngtopam: Using libnetpbm from Netpbm Version:", "Netpbm")
    for cut in (" Copyright", " https://", " http://", " x86_64"):
        v = v.split(cut)[0]
    return v.strip()[:40]


def build_summary(R, m, man, images, census_rows, n_hash_rows, tally):
    last = lambda k: (m.get(k) or [""])[-1]
    num = lambda x: f"{int(x):,}"
    files = {l: len(rows) for l, rows in man.items()}
    lic = collections.Counter(im["lic"] for im in images)
    s = [{"title": "Corpus", "rows": [
        ["Images rendered", f"{len(images):,}"], ["DNGs (originals only)", "3"],
        *[[f"{l} files", f"{n:,}"] for l, n in files.items()],
        *[[f"Licence {k}", f"{v:,}"] for k, v in lic.most_common()]]}]
    import re
    gates = []
    rb = re.match(r"(\d+) of (\d+) files pass; (\d+) fail", last("gates_readback"))
    if rb:
        gates.append(["PNG read-back (4 readers)", f"{num(rb[1])} of {num(rb[2])}", "ok" if rb[3] == "0" else "bad"])
    inv = re.search(r"(\d+) image files inventoried; (\d+) violations", last("gates_inventory"))
    if inv:
        gates.append(["Inventory", f"{num(inv[1])} files, {inv[2]} violations", "ok" if inv[2] == "0" else "bad"])
    for b in m.get("gates_byte_scan", [])[-4:]:
        g = re.match(r"([\w-]+): (\d+) files scanned, (\d+) with findings, (\d+) allowed findings", b)
        if g:
            v = f"{g[3]} findings" + (f", {g[4]} allowed" if g[4] != "0" else "")
            gates.append([f"Byte scan {g[1]}", v, "ok" if g[3] == "0" else "bad"])
    jr = re.match(r"(\d+) of (\d+) JXL files pass; (\d+) fail", last("jxl_recheck"))
    if jr:
        gates.append(["JPEG XL check, libjxl (full)", f"{num(jr[1])} of {num(jr[2])}", "ok" if jr[3] == "0" else "bad"])
    s.append({"title": "Gates", "rows": gates or [["Gates", "not recorded", "na"]]})
    rep = tsv(os.path.join(R, "decode-check", "report.tsv"))
    gms = tsv(os.path.join(R, "decode-check", "gain-maps.tsv"))
    if rep:
        lossless = [r for r in rep if r["same_as_png_twin"]]
        jpeg = [r for r in rep if r["agreeing_decoders"]]
        ok = sum(r["all_decode"] == "yes" for r in rep)
        same = sum(r["same_as_png_twin"] == "yes" for r in lossless)
        agree = sum(";" not in r["agreeing_decoders"] for r in jpeg)
        rows = [["Decode at the manifest's size", f"{ok:,} of {len(rep):,}", "ok" if ok == len(rep) else "bad"],
                ["Lossless = PNG twin's bitmap in all three", f"{same:,} of {len(lossless):,}", "ok" if same == len(lossless) else "bad"],
                ["JPEG-in-JXL: one bitmap in all three", f"{agree:,} of {len(jpeg):,}", "na"]]
        if gms:
            n = len(gms)
            c = lambda k, v="yes": sum(g[k] == v for g in gms)
            lossless_gm = [g for g in gms if g["form"] == "lossless+jhgm"]
            exact = sum(all(x == "0" for x in g["max_diff_vs_form_zenjxl_jxlrs_libjxl"].split()) for g in lossless_gm)
            hdr_ok = sum(g["hdr_status"] == "ok" and float(g["hdr_stops_p50"] or 9) <= 0.01 for g in gms)
            rows += [["Gain maps decode and line up", f"{c('lines_up')} of {n}", "ok" if c("lines_up") == n else "bad"],
                     ["Gain-map metadata the same in all three", f"{c('metadata_same_in_decoders')} of {n}",
                      "ok" if c("metadata_same_in_decoders") == n else "bad"],
                     ["Lossless gain maps = gain-map form", f"{exact} of {len(lossless_gm)}", "ok" if exact == len(lossless_gm) else "bad"],
                     ["zenjxl HDR reconstruction on target", f"{hdr_ok} of {n}", "ok" if hdr_ok == n else "bad"]]
        lj = last("decode_check_libjxl").split()
        s.append({"title": f"JPEG XL decoders: zenjxl, jxl-rs {last('decode_check_jxl_rs')}, libjxl {lj[1] if len(lj) > 1 else ''}",
                  "rows": rows})
    if census_rows:
        readers = sorted({(c["image"], c["reader"]) for c in census_rows})
        distinct = len({c["sha256"] for c in census_rows})
        ok = sum(c["status"] == "ok" for c in census_rows)
        exact = sum(c["same"] in ("native", "rgba8") for c in census_rows)
        png = [c for c in census_rows if c["path"].endswith(".png")]
        jxl = [c for c in census_rows if c["path"].endswith(".jxl")]
        rows = [["Readers", f"{len(readers)}"], ["Distinct files read", f"{distinct:,}"], ["Decodes", f"{len(census_rows):,}"]]
        for fmt_, name in (("png", "PNG"), ("jxl", "JPEG XL")):
            total = len({r["sha256"] for layer, rs in man.items() if layer.startswith(fmt_) for r in rs})
            read = len({c["sha256"] for c in census_rows if c["path"].endswith("." + fmt_)})
            rows.append([f"{name} files read", f"{read:,} of {total:,}" + ("" if read == total else " (census running)"),
                         "ok" if read == total else "na"])
            n = sum(v for (f, _), v in tally.items() if f == fmt_)
            if n:
                rows += [[f"{name}: exact", f"{tally[(fmt_, 'exact')]:,} of {n:,}", "ok"],
                         [f"{name}: expected differences", f"{tally[(fmt_, 'expected')]:,}", "na"],
                         [f"{name}: not read (no support, reader limits)", f"{tally[(fmt_, 'refused')]:,}", "na"],
                         [f"{name}: unexplained", f"{tally[(fmt_, 'problem')]:,}", "ok" if not tally[(fmt_, 'problem')] else "warn"]]
        s.append({"title": "Reader census (Docker)", "rows": rows,
                  "download": f"Download decoded-bitmap hashes ({n_hash_rows:,} rows)"})
    else:
        s.append({"title": "Decoded-bitmap hashes", "rows": [["Rows (file and decoder)", f"{n_hash_rows:,}"],
                                                              ["Reader census", "running", "na"]],
                  "download": f"Download decoded-bitmap hashes ({n_hash_rows:,} rows)"})
    return s


FOOTER = [
    "Thumbnails and previews are made from each image's <code>png-srgb</code> file (sRGB, orientation baked) with "
    "<code>tools/corpus-thumbs</code> (zen crates only): previews up to 1600 px at WebP quality 80, and full "
    "resolution at quality 75 for the larger images (it loads when you zoom past the preview). "
    "<b>Original ↗</b> opens the source file on the public R2 prefix.",
    "Decoded-bitmap hashes are XXH3-64 of the interleaved samples in each image's own layout (gray, gray+alpha, RGB or "
    "RGBA; 8-bit, or 16-bit little-endian above 8 bits), rows packed, in displayed orientation: equal hashes mean equal pixels.",
    "Reader census: each distinct file through the adapters of the image-compat matrix in Docker (Ubuntu 24.04 LTS "
    "packages, a rolling distribution, and Chromium, Firefox and WebKit through Playwright), with no network; each "
    "reader's bitmap is compared with ours (zenpng or zenjxl); for a wide-gamut file, also with an sRGB reference "
    "(its sRGB twin, or for a JPEG-in-JXL file our decode converted to sRGB, with a tolerance per pixel); and for a "
    "JPEG XL file a reader leaves unrotated, with our decode in the stored orientation.",
]


def cmd_census(a):
    """The census verdicts of one format, counted per reader and outcome, with an example of
    each unexplained one."""
    R = a.render
    man = {}
    for l in ("png-p3", "png-srgb", "jxl-p3", "jxl-srgb"):
        for r in tsv(os.path.join(R, "manifests", f"{l}.tsv")):
            man[r["path"]] = r
    rows = [r for r in tsv(os.path.join(R, "compat-census", "census.tsv")) if r["path"].endswith("." + a.format)]
    seen, ok = collections.Counter(), collections.Counter()
    for r in rows:
        seen[(r["image"], r["reader"])] += 1
        ok[(r["image"], r["reader"])] += r["status"] == "ok"
    jxl_support = {k: ok[k] / n for k, n in seen.items()}
    info = {}
    if a.format == "jxl":
        jxlcheck = {r["path"]: r for r in tsv(os.path.join(R, "jxl-check.tsv"))}
        info = jxl_census_info(R, {r["path"] for r in rows}, jxlcheck)
    hashes = collections.defaultdict(list)
    for r in tsv(os.path.join(R, "decoded-xxh3.tsv")):
        hashes[r["path"]].append(r)
    count, example = collections.Counter(), {}
    for c in rows:
        m = man[c["path"]]
        ours = next((h for h in hashes.get(c["path"], []) if h["decoder"] in ("zenpng", "zenjxl")), None)
        px_bytes = (1 if ours and ours["channels"] == "1" else 4) * (2 if ours and int(ours["bits"] or 8) > 8 else 1)
        label, problem = verdict(c, m["form"], jxl_support, int(m["width"]) * int(m["height"]) * px_bytes, info.get(c["path"]))
        k = (problem, f"{c['image']} {c['reader']}", re.sub(r" \(±\d+\)$", "", label) if problem else label)
        count[k] += 1
        example.setdefault(k, c)
    print(f"{len(rows):,} rows, {len({r['sha256'] for r in rows}):,} files, "
          f"{sum(v for k, v in count.items() if k[0]):,} unexplained")
    for k in sorted(count, key=lambda k: (not k[0], k[1], k[2])):
        c = example[k]
        print(("UNEXPLAINED " if k[0] else "") + f"{count[k]:6,}  {k[1]:22} {k[2]}"
              + (f"  e.g. {c['path'].split('/')[-1][:60]} {c['same']} {c['max_diff']} {c['error'][:80]}" if k[0] else ""))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("images"); p.add_argument("render"); p.add_argument("stage"); p.add_argument("--jobs", type=int, default=12)
    p = sub.add_parser("fullpacks"); p.add_argument("render"); p.add_argument("stage")
    p = sub.add_parser("data"); p.add_argument("render"); p.add_argument("stage"); p.add_argument("--fullpack-urls", default="")
    p.add_argument("--hash-urls", default="", help="the hash parts' asset URLs (part name, sha256, URL per line)")
    p.add_argument("--no-census", action="store_true", help="leave the reader census out (while it runs)")
    p = sub.add_parser("site", help="the page as a static site for a web host")
    p.add_argument("render"); p.add_argument("stage"); p.add_argument("site")
    p.add_argument("--no-census", action="store_true", help="leave the reader census out")
    p = sub.add_parser("census", help="count the census verdicts of one format")
    p.add_argument("render"); p.add_argument("format", choices=("png", "jxl"))
    a = ap.parse_args()
    a.render = os.path.abspath(a.render)
    {"images": cmd_images, "fullpacks": cmd_fullpacks, "data": cmd_data, "site": cmd_site,
     "census": cmd_census}[a.cmd](a)


if __name__ == "__main__":
    main()
