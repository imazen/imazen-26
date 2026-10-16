#!/usr/bin/env python3
"""Compare the decodes scripts/render_v4_decode_check.sh collected (EXPORT-PLAN.md, "Gates").

    render_v4_decode_report.py <render-dir>

Reads <render-dir>/decode-check/{files,png,jxl,jxl-libjxl,hdr}.tsv, the gain-map dumps under
decode-check/gm/ and the manifests, and writes:

- decode-check/report.tsv: per JPEG XL file, whether zenjxl, jxl-rs and libjxl decoded it at
  the manifest's size, whether a lossless file gave its PNG twin's bitmap in all three, and
  which decoders agree on a JPEG-in-JXL file (JPEG pixels depend on the decoder).
- decode-check/gain-maps.tsv: per `jhgm` file, each decoder's gain map: its size against the
  displayed base (it must cover the base in the base's displayed orientation), its ISO 21496-1
  metadata against the other decoders' and the gain-map form's (gain-maps/<stem>.iso21496), its
  pixels against the gain-map form's PNG, and zenjxl's HDR reconstruction against the PQ render.
- <render-dir>/decoded-xxh3.tsv: every decoded bitmap's XXH3, one row per file and decoder.

Prints a summary; exits 1 if a decoder failed on any file, a lossless file or gain map differs
from its twin, a gain map doesn't line up with its base, or the metadata differs.
"""
import csv
import os
import sys

import numpy as np
from PIL import Image

DECODERS = ("zenjxl", "jxl-rs", "libjxl")
LOSSLESS = ("lossless", "lossless+jhgm", "lossless-pq")


def tsv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def pnm(path):
    """Samples of a binary PGM/PPM as a uint8 array (H, W[, 3])."""
    data = open(path, "rb").read()
    parts, pos = [], 0
    while len(parts) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        parts.append(data[pos:end])
        pos = end
    magic, w, h = parts[0], int(parts[1]), int(parts[2])
    px = np.frombuffer(data, np.uint8, offset=pos + 1)
    return px.reshape((h, w)) if magic == b"P5" else px.reshape((h, w, 3))


def main():
    out = sys.argv[1]
    dc = os.path.join(out, "decode-check")
    layer_of = {r["path"]: r["layer"] for r in
                tsv_rows(os.path.join(dc, "files.tsv"), ["layer", "path"])}
    man = {}
    for layer in ("png-p3", "png-srgb", "jxl-p3", "jxl-srgb"):
        for r in tsv(os.path.join(out, "manifests", f"{layer}.tsv")):
            man[r["path"]] = r  # the path starts with the layer
    rel = lambda p: os.path.relpath(p, out)
    png = {rel(r["path"]): r for r in tsv(os.path.join(dc, "png.tsv"))}
    dec = {}
    for name in ("jxl.tsv", "jxl-libjxl.tsv"):
        for r in tsv(os.path.join(dc, name)):
            dec[(rel(r["path"]), r["decoder"])] = r
    hdr = {rel(r["jxl"]): r for r in tsv(os.path.join(dc, "hdr.tsv"))}
    forms = {r["id"]: r for r in tsv(os.path.join(out, "gain-maps-report.tsv"))}

    problems = []
    report, gm_rows = [], []
    counts = dict(jxl=0, all_ok=0, lossless=0, lossless_same=0, jpeg=0, jpeg_all_agree=0,
                  jpeg_rs_libjxl=0, gm=0, gm_ok=0, gm_aligned=0, gm_meta_same=0, gm_meta_form=0,
                  gm_lossless=0, gm_lossless_exact=0, gm_jpeg=0, hdr_aligned=0)
    jpeg_gm_diffs = []
    for path, layer in sorted(layer_of.items()):
        if not layer.startswith("jxl"):
            continue
        counts["jxl"] += 1
        m = man[path]
        form = m["form"]
        rows = [dec.get((path, d)) for d in DECODERS]
        notes = []
        ok = all(r is not None and r["status"] == "ok" and not r["error"] for r in rows)
        size = (m["width"], m["height"])
        if ok and any((r["width"], r["height"]) != size for r in rows):
            ok = False
            notes.append("size " + ", ".join(f"{d} {r['width']}x{r['height']}" for d, r in zip(DECODERS, rows)))
        if not ok:
            notes += [f"{d}: {(r or {}).get('error') or (r or {}).get('status', 'missing')}" for d, r in zip(DECODERS, rows)
                      if r is None or r["status"] != "ok" or r["error"]]
            problems.append(f"{path}: {'; '.join(notes)}")
        counts["all_ok"] += ok
        same_png = agree = ""
        if ok and form in LOSSLESS:
            counts["lossless"] += 1
            twin = png.get(path.replace("jxl-", "png-", 1).removesuffix(".jxl") + ".png")
            same = twin is not None and all(
                (r["xxh3"], r["channels"], r["bits"]) == (twin["xxh3"], twin["channels"], twin["bits"]) for r in rows)
            same_png = "yes" if same else "no"
            counts["lossless_same"] += same
            if not same:
                problems.append(f"{path}: a decoder's bitmap differs from the PNG twin's")
        elif ok:
            counts["jpeg"] += 1
            hashes = {d: r["xxh3"] for d, r in zip(DECODERS, rows)}
            groups = {}
            for d, h in hashes.items():
                groups.setdefault(h, []).append(d)
            agree = "; ".join("=".join(g) for g in sorted(groups.values(), key=len, reverse=True))
            counts["jpeg_all_agree"] += len(groups) == 1
            counts["jpeg_rs_libjxl"] += hashes["jxl-rs"] == hashes["libjxl"]
        report.append([layer, path, form, "yes" if ok else "no", same_png, agree, "; ".join(notes)])

        if form.endswith("+jhgm"):
            counts["gm"] += 1
            stem = os.path.basename(path)
            ref = forms[m["id"]]
            ref_px = np.asarray(Image.open(os.path.join(out, ref["path"])))
            ref_meta = open(os.path.join(out, ref["metadata_path"]), "rb").read()
            gm_ok = ok and all(r["gm_status"] == "ok" for r in rows)
            base_w, base_h = int(m["width"]), int(m["height"])
            aligned, metas, diffs = True, [], []
            for d, r in zip(DECODERS, rows):
                if not gm_ok:
                    break
                gw, gh = int(r["gm_width"]), int(r["gm_height"])
                # The map covers the displayed base: equal scale on both axes, to a pixel.
                if abs(gw * base_h - gh * base_w) > max(base_w, base_h):
                    aligned = False
                metas.append(open(os.path.join(dc, "gm", d, stem + ".iso21496"), "rb").read())
                ext = ".pgm" if r["gm_channels"] == "1" else ".ppm"
                px = pnm(os.path.join(dc, "gm", d, stem + ext))
                diffs.append(int(np.abs(px.astype(np.int16) - ref_px.astype(np.int16)).max())
                             if px.shape == ref_px.shape else None)
            meta_same = gm_ok and len(set(metas)) == 1
            meta_form = meta_same and metas[0] == ref_meta
            counts["gm_ok"] += gm_ok
            counts["gm_aligned"] += gm_ok and aligned
            counts["gm_meta_same"] += meta_same
            counts["gm_meta_form"] += meta_form
            if not gm_ok:
                problems.append(f"{path}: a decoder did not decode the jhgm gain map")
            elif not aligned:
                problems.append(f"{path}: the gain map does not line up with the displayed base")
            if gm_ok and not meta_same:
                problems.append(f"{path}: the decoders read different ISO 21496-1 metadata")
            if form == "lossless+jhgm":
                counts["gm_lossless"] += 1
                exact = gm_ok and all(x == 0 for x in diffs)
                counts["gm_lossless_exact"] += exact
                if gm_ok and not exact:
                    problems.append(f"{path}: a lossless gain map differs from the gain-map form")
            else:
                counts["gm_jpeg"] += 1
                jpeg_gm_diffs += [x for x in diffs if x is not None]
                if gm_ok and None in diffs:
                    problems.append(f"{path}: a gain map's size differs from the gain-map form's")
            h = hdr.get(path, {})
            hdr_aligned = h.get("status") == "ok" and float(h["stops_p50"]) <= 0.01
            counts["hdr_aligned"] += hdr_aligned
            gm_rows.append([layer, path, form, rows[2]["orientation"] if rows[2] else "",
                            " ".join(f"{r['gm_width']}x{r['gm_height']}" for r in rows if r),
                            "yes" if gm_ok and aligned else "no", "yes" if meta_same else "no",
                            "yes" if meta_form else "no",
                            " ".join("" if x is None else str(x) for x in diffs),
                            h.get("status", ""), h.get("pq10_p50", ""), h.get("pq10_p999", ""),
                            h.get("pq10_max", ""), h.get("stops_p50", ""), h.get("stops_p999", ""),
                            h.get("stops_max", ""), h.get("error", "")])

    with open(os.path.join(dc, "report.tsv"), "w") as f:
        f.write("layer\tpath\tform\tall_decode\tsame_as_png_twin\tagreeing_decoders\tnotes\n")
        f.writelines("\t".join(r) + "\n" for r in report)
    with open(os.path.join(dc, "gain-maps.tsv"), "w") as f:
        f.write("layer\tpath\tform\tbase_orientation\tgain_map_size_zenjxl_jxlrs_libjxl\tlines_up\t"
                "metadata_same_in_decoders\tmetadata_same_as_form\tmax_diff_vs_form_zenjxl_jxlrs_libjxl\t"
                "hdr_status\thdr_pq10_p50\thdr_pq10_p999\thdr_pq10_max\thdr_stops_p50\thdr_stops_p999\t"
                "hdr_stops_max\thdr_error\n")
        f.writelines("\t".join(r) + "\n" for r in gm_rows)
    write_hashes(out, layer_of, png, dec)

    c = counts
    print(f"{c['jxl']} JPEG XL files: {c['all_ok']} decode in zenjxl, jxl-rs and libjxl at the manifest's size")
    print(f"lossless: {c['lossless_same']} of {c['lossless']} give their PNG twin's bitmap in all three decoders")
    print(f"JPEG-in-JXL: all three agree on {c['jpeg_all_agree']} of {c['jpeg']}; jxl-rs = libjxl on {c['jpeg_rs_libjxl']}")
    print(f"jhgm gain maps: {c['gm_ok']} of {c['gm']} decode in all three; {c['gm_aligned']} line up with the "
          f"displayed base; metadata identical across decoders on {c['gm_meta_same']}, and equal to the "
          f"gain-map form's on {c['gm_meta_form']}")
    print(f"lossless gain maps identical to the gain-map form in all three: {c['gm_lossless_exact']} of {c['gm_lossless']}")
    if jpeg_gm_diffs:
        print(f"JPEG-derived gain maps vs the gain-map form (zenjpeg's decode of the JPEG's): max diff "
              f"{min(jpeg_gm_diffs)}-{max(jpeg_gm_diffs)} over {c['gm_jpeg']} files x 3 decoders")
    print(f"zenjxl HDR reconstruction within 0.01 stops of the PQ render at the median: {c['hdr_aligned']} of {c['gm']}")
    print(f"{len(problems)} problems")
    for p in problems[:30]:
        print("  " + p)
    sys.exit(1 if problems else 0)


def tsv_rows(path, names):
    with open(path) as f:
        return [dict(zip(names, line.rstrip("\n").split("\t"))) for line in f if line.strip()]


def write_hashes(out, layer_of, png, dec):
    """decoded-xxh3.tsv: every decoded bitmap, one row per file and decoder."""
    cols = ["layer", "path", "decoder", "status", "width", "height", "channels", "bits", "xxh3",
            "gm_width", "gm_height", "gm_channels", "gm_bits", "gm_xxh3", "metadata_xxh3"]
    with open(os.path.join(out, "decoded-xxh3.tsv"), "w") as f:
        f.write("# XXH3-64 (seed 0) of each decoded bitmap: the interleaved samples in the image's own\n"
                "# layout (gray, gray+alpha, RGB or RGBA; 8-bit, or 16-bit little-endian above 8 bits),\n"
                "# rows packed, in displayed orientation. gm_* is a jhgm gain map decoded by the same\n"
                "# decoder, metadata_xxh3 its ISO 21496-1 metadata. Paths are relative to the layer roots.\n")
        f.write("\t".join(cols) + "\n")
        for path, layer in sorted(layer_of.items()):
            rows = [png.get(path)] if not layer.startswith("jxl") else [dec.get((path, d)) for d in DECODERS]
            for r in rows:
                if r is None:
                    continue
                gm = r.get("gm_status") == "ok"
                f.write("\t".join([layer, path, r["decoder"], r["status"], r["width"], r["height"],
                                   r["channels"], r["bits"], r["xxh3"],
                                   r["gm_width"] if gm else "", r["gm_height"] if gm else "",
                                   r["gm_channels"] if gm else "", r["gm_bits"] if gm else "",
                                   r["gm_xxh3"] if gm else "", r["metadata_xxh3"] if gm else ""]) + "\n")


if __name__ == "__main__":
    main()
