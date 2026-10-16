#!/usr/bin/env python3
"""Write the per-layer manifests of a finished render v4 output (EXPORT-PLAN.md, "Render v4").

    export_manifests.py <render-dir>

Reads the render's reports (report.tsv, hdr-report.tsv, jxl-report.tsv, jxl-hdr-report.tsv),
list.tsv and RUN.meta, and writes <render-dir>/manifests/<layer>.tsv for png-p3, png-srgb,
jxl-p3 and jxl-srgb: one row per file, HDR files in their p3 layer, with the image facts,
the provenance and the commits that made it. A row's tool commit and Cargo.lock hash are those
of the pass that wrote its file: the first run, a redo (redo-<n>-report.tsv lists its rows),
the HDR pass or the JXL pass, as RUN.meta records them.
"""
import csv
import json
import os
import sys

COLUMNS = ["id", "bucket", "path", "form", "width", "height", "bytes", "sha256", "pixels_sha256",
           "colour", "source_alpha", "clipped", "gain_map", "headroom_stops", "diffuse_white_nits",
           "max_cll", "max_fall", "jhgm", "jpeg_rebuild_sha256", "original_sha256", "license",
           "source", "tool_commit", "cargo_lock_sha256"]


def meta(render):
    out = {}
    for line in open(os.path.join(render, "RUN.meta")):
        k, _, v = line.rstrip("\n").partition("\t")
        out[k] = v
    return out


def rows(path):
    if not os.path.exists(path):
        return []
    return [r for r in csv.DictReader(open(path), delimiter="\t") if not r["error"]]


def main():
    render = sys.argv[1]
    m = meta(render)
    lst = {}
    for line in open(os.path.join(render, "list.tsv")):
        f = line.rstrip("\n").split("\t")
        lst[f[0]] = json.loads(f[3])
    redo = {}
    n = 1
    while os.path.exists(os.path.join(render, f"redo-{n}-report.tsv")):
        for r in rows(os.path.join(render, f"redo-{n}-report.tsv")):
            redo[r["id"]] = n
        n += 1

    def tool(pass_name, i):
        if pass_name == "sdr" and i in redo:
            k = f"redo_{redo[i]}_"
            return m.get(k + "tool_commit", ""), m.get(k + "render_v4_cargo_lock_sha256", "")
        prefix = {"sdr": "", "hdr": "hdr_", "jxl": "jxl_"}[pass_name]
        return m.get(prefix + "tool_commit", ""), m.get(prefix + "render_v4_cargo_lock_sha256", "")

    out = {layer: [] for layer in ("png-p3", "png-srgb", "jxl-p3", "jxl-srgb")}
    sdr = {(r["id"], r["layer"]): r for r in rows(os.path.join(render, "report.tsv"))}
    for (i, layer), r in sdr.items():
        p = lst[i]
        commit, lock = tool("sdr", i)
        out[layer].append({**{c: "" for c in COLUMNS}, "id": i, "bucket": p["split"], "path": r["path"],
                           "form": "sdr", "width": r["width"], "height": r["height"], "bytes": r["bytes"],
                           "sha256": r["sha256"], "pixels_sha256": r["rgba_sha256"], "colour": r["colour"],
                           "source_alpha": r["source_alpha"], "clipped": r["clipped"], "gain_map": r["gain_map"],
                           "original_sha256": p["original_sha256"], "license": p["license"],
                           "source": p["source"], "tool_commit": commit, "cargo_lock_sha256": lock})
    for r in rows(os.path.join(render, "hdr-report.tsv")):
        p = lst[r["id"]]
        commit, lock = tool("hdr", r["id"])
        out["png-p3"].append({**{c: "" for c in COLUMNS}, "id": r["id"], "bucket": p["split"], "path": r["path"],
                              "form": "hdr-pq", "width": r["width"], "height": r["height"], "bytes": r["bytes"],
                              "sha256": r["sha256"], "pixels_sha256": r["rgb16_sha256"], "colour": r["colour"],
                              "gain_map": r["gain_map"], "headroom_stops": r["headroom_stops"],
                              "diffuse_white_nits": r["diffuse_white_nits"], "max_cll": r["max_cll"],
                              "max_fall": r["max_fall"], "original_sha256": p["original_sha256"],
                              "license": p["license"], "source": p["source"], "tool_commit": commit,
                              "cargo_lock_sha256": lock})
    hdr_png = {r["id"]: r for r in rows(os.path.join(render, "hdr-report.tsv"))}
    for name in ("jxl-report.tsv", "jxl-hdr-report.tsv"):
        for r in rows(os.path.join(render, name)):
            p = lst[r["id"]]
            commit, lock = tool("jxl", r["id"])
            layer = r["layer"].removesuffix("-hdr")
            twin = sdr.get((r["id"], layer.replace("jxl-", "png-")), {})
            row = {**{c: "" for c in COLUMNS}, "id": r["id"], "bucket": p["split"], "path": r["path"],
                   "form": r["kind"], "width": r["width"], "height": r["height"], "bytes": r["bytes"],
                   "sha256": r["sha256"], "pixels_sha256": r["pixels_sha256"], "colour": r["colour"],
                   "source_alpha": twin.get("source_alpha", ""), "clipped": twin.get("clipped", ""),
                   "gain_map": twin.get("gain_map", ""), "jhgm": r.get("jhgm", ""),
                   "jpeg_rebuild_sha256": r["jpeg_sha256"], "original_sha256": p["original_sha256"],
                   "license": p["license"], "source": p["source"], "tool_commit": commit,
                   "cargo_lock_sha256": lock}
            if r["layer"].endswith("-hdr"):
                h = hdr_png.get(r["id"], {})
                row.update(gain_map=h.get("gain_map", ""), headroom_stops=h.get("headroom_stops", ""),
                           diffuse_white_nits=h.get("diffuse_white_nits", ""), max_cll=h.get("max_cll", ""),
                           max_fall=h.get("max_fall", ""))
            out[layer].append(row)
    os.makedirs(os.path.join(render, "manifests"), exist_ok=True)
    for layer, rs in out.items():
        rs.sort(key=lambda r: (r["id"], r["form"]))
        with open(os.path.join(render, "manifests", f"{layer}.tsv"), "w") as f:
            f.write("\t".join(COLUMNS) + "\n")
            f.writelines("\t".join(str(r[c]) for c in COLUMNS) + "\n" for r in rs)
        missing = [r["id"] for r in rs if not r["tool_commit"]]
        print(f"{layer}: {len(rs)} files" + (f"; {len(missing)} without a tool commit" if missing else ""))


if __name__ == "__main__":
    main()
