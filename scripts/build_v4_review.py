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
    build_v4_review.py data <render-dir> <stage-dir> [--fullpack-urls TSV]
        The page and its data: v4-review.html (scripts/v4_review_page.html), data/index.json,
        data/dNN.json (details, 100 images each), thumbs/sheet_NN.webp, packs/pack_NN.webp
        (the medium previews concatenated; the index gives each one's offset and length) and
        data/decoded-xxh3.tsv.gz. --fullpack-urls maps each full-resolution pack to the asset
        URL its Artifact upload returned (fp_NNN.webp<TAB>url).

The details join the render's reports: manifests/, list.tsv (provenance), readback.tsv,
jxl-check.tsv, byte-scan-<layer>.tsv, inventory-full.tsv (every part of every file),
decode-check/ (render_v4_decode_check.sh), decoded-xxh3.tsv, compat-census/
(render_v4_compat_census.py) and imi-check.tsv (status only), plus the repository's
manifests for the originals.
"""
import argparse
import collections
import csv
import gzip
import json
import os
import shutil
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


def cmd_data(a):
    R, S = a.render, a.stage
    work = os.path.join(S, "work")
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
    for r in tsv(os.path.join(R, "compat-census", "aliases.tsv")):
        alias[r["sha256"]].append(r["path"])
    census_rows = tsv(os.path.join(R, "compat-census", "census.tsv"))
    for r in census_rows:
        census[r["sha256"]].append(r)

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
                issue |= any(x != "ok" for x in d["readback"])
            if p in jxlcheck:
                d["jxlcheck"] = [jxlcheck[p]["result"], jxlcheck[p]["colour"] or jxlcheck[p]["error"]]
                issue |= jxlcheck[p]["result"] != "ok"
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
            cen.append({"layer": rows[0]["layer"], "path": rows[0]["path"], "also": [x for x in paths if x != rows[0]["path"]],
                        "rows": [[f"{c['image']} {c['reader']} {short_version(c['version'])}".strip(), c["status"], c["same"],
                                  c["max_diff"], c["srgb_twin_same"], c["srgb_twin_max_diff"],
                                  int(float(c["ms"])) if c["ms"] else "", c["error"][:160]] for c in rows]})
            if rows[0]["path"].endswith(".png"):
                issue |= any(c["status"] != "ok" or (c["same"] == "no" and c["max_diff"] and int(c["max_diff"]) > 1)
                             for c in rows)
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
    # path (a census row covers every path with the same bytes), gzipped; the page decompresses
    # it for the download. It is also kept beside the render as decoded-xxh3-with-readers.tsv.
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
    with gzip.open(os.path.join(S, "data", "decoded-xxh3.tsv.gz"), "wb", 9) as g:
        g.write(text.encode())
    n_hash_rows = len(rows)

    m = meta(R)
    summary = build_summary(R, m, man, images, census_rows, n_hash_rows)
    licences = [l for l, _ in collections.Counter(im["lic"] for im in images).most_common()]
    index = {"cell": CELL, "sheetW": CELL * COLS, "classes": classes, "licences": licences, "images": images,
             "summary": summary, "hashesFile": "data/decoded-xxh3.tsv.gz", "footer": FOOTER}
    json.dump(index, open(os.path.join(S, "data", "index.json"), "w"), separators=(",", ":"))
    shutil.copy(os.path.join(REPO, "scripts", "v4_review_page.html"), os.path.join(S, "v4-review.html"))
    sizes = {d: sum(os.path.getsize(os.path.join(S, d, f)) for f in os.listdir(os.path.join(S, d)))
             for d in ("data", "thumbs", "packs")}
    print(f"{len(images)} images; " + ", ".join(f"{d} {v / 1e6:.1f} MB" for d, v in sizes.items()), file=sys.stderr)


def short_version(v):
    """A reader's version string, shortened for a table cell."""
    v = v.replace("Version: ", "").replace("pngtopam: Using libnetpbm from Netpbm Version:", "Netpbm")
    for cut in (" Copyright", " https://", " http://", " x86_64"):
        v = v.split(cut)[0]
    return v.strip()[:40]


def build_summary(R, m, man, images, census_rows, n_hash_rows):
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
    redos = sorted({k for k in m if re.fullmatch(r"jxl_redo_\d+_check", k)})
    if redos:
        gates.append(["JPEG XL redo checks", "; ".join(f"{k.split('_')[2]}: {last(k).split(';')[0].replace(' JXL files pass', '')}"
                                                       for k in redos), "ok"])
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
        s.append({"title": "Reader census (Docker)", "rows": [
            ["Readers", f"{len(readers)}"], ["Distinct files read", f"{distinct:,}"], ["Decodes", f"{len(census_rows):,}"],
            ["Decoded without error", f"{ok:,}"], ["Bitmap equal to ours", f"{exact:,}"],
            ["PNG decodes equal to ours", f"{sum(c['same'] in ('native', 'rgba8') for c in png):,} of {len(png):,}"],
            ["JPEG XL decodes without error", f"{sum(c['status'] == 'ok' for c in jxl):,} of {len(jxl):,}"]],
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
    "reader's bitmap is compared with ours (zenpng or zenjxl) and, for a wide-gamut file, with its sRGB twin.",
]


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("images"); p.add_argument("render"); p.add_argument("stage"); p.add_argument("--jobs", type=int, default=12)
    p = sub.add_parser("fullpacks"); p.add_argument("render"); p.add_argument("stage")
    p = sub.add_parser("data"); p.add_argument("render"); p.add_argument("stage"); p.add_argument("--fullpack-urls", default="")
    a = ap.parse_args()
    a.render = os.path.abspath(a.render)
    {"images": cmd_images, "fullpacks": cmd_fullpacks, "data": cmd_data}[a.cmd](a)


if __name__ == "__main__":
    main()
