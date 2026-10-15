#!/usr/bin/env python3
"""Write render-v4's input list from the manifests (EXPORT-PLAN.md, "Render v4").

One row per manifest image:

    id <TAB> source path <TAB> out stem <TAB> provenance JSON

- id: the export id, the manifest id with a leading 1 (1044 -> 11044).
- source path: the image under <originals-dir> (the originals pass, byte for byte).
- out stem: <class folder>/<file name>, both renumbered, without the stored `_WxH` and the
  extension; render-v4 appends the displayed size. Sub-folders are dropped: every file name
  starts with its unique id, so names stay unique within a class folder.
- provenance JSON: corpus, id, split, category, source, licence and the attribution the
  per-folder MANIFEST.tsv records, plus the original's sha256. ASCII (`\\uXXXX` escapes), so
  the PNG `tEXt` chunk reads the same as Latin-1 or UTF-8. Nothing about where or with what a
  photo was taken: no location, camera or capture time.

Usage: render_v4_list.py <originals-dir> [--ids 1044,1214] > list.tsv
"""
import argparse
import csv
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUCKETS = ("train", "validate", "test")


def manifest_rows():
    for b in BUCKETS:
        with open(os.path.join(REPO, "manifests", f"{b}.tsv"), newline="") as f:
            yield from csv.DictReader(f, delimiter="\t")


def folder_rows():
    """Per-folder MANIFEST.tsv rows, keyed by the path relative to the repo."""
    out = {}
    for folder in sorted(os.listdir(REPO)):
        p = os.path.join(REPO, folder, "MANIFEST.tsv")
        if re.fullmatch(r"\d{4}-.+", folder) and os.path.isfile(p):
            with open(p, newline="") as f:
                for r in csv.DictReader(f, delimiter="\t"):
                    out[f"{folder}/{r['filename']}"] = r
    return out


def new_id(old):
    if not re.fullmatch(r"\d{4}", old):
        raise SystemExit(f"unexpected id {old!r}")
    return "1" + old


def stem(path, old):
    folder, name = path.split("/", 1)[0], path.rsplit("/", 1)[-1]
    m = re.fullmatch(r"(\d{4})(-.+)", folder)
    base, _ = os.path.splitext(name)
    base = re.sub(r"_\d+x\d+$", "", base)
    if not m or not base.startswith(old + "_"):
        raise SystemExit(f"unexpected path {path!r} for id {old}")
    return f"1{m.group(1)}{m.group(2)}/{new_id(old)}{base[len(old):]}"


def attribution(src, f):
    """The attribution fields one source kind records, by its per-folder manifest columns."""
    if src in ("art-institute-chicago", "met-museum"):
        a = {k: f[k] for k in ("artist", "title", "date", "medium") if f.get(k)}
        object_url = {"art-institute-chicago": "https://www.artic.edu/artworks/",
                      "met-museum": "https://www.metmuseum.org/art/collection/search/"}[src]
        a["object_url"] = object_url + f["keyinfo"]
        a["image_url"] = f["image_url"]
        a["art_license"] = f["art_license"]
        return a
    if src == "unsplash":
        m = re.fullmatch(r"(.+)-([A-Za-z0-9_-]{11})-unsplash\.(?:jpe?g|png)", f["original_filename"])
        if not m:
            raise SystemExit(f"unparsed Unsplash name {f['original_filename']!r}")
        return {"photographer": m.group(1), "source_url": f"https://unsplash.com/photos/{m.group(2)}"}
    if src in ("nps", "noaa"):
        return {k: f[k] for k in ("source_description", "source_url", "pd_basis") if f.get(k)}
    if src == "epa":
        page = re.search(r"\|p(\d+)$", f.get("keyinfo", ""))
        a = {"source_work": "epa-climate-impact-2021-report"}
        if page:
            a["page"] = str(int(page.group(1)))
        return a
    if src == "uspto":
        return {"inventor": f["inventor"], "patent": f["patent"].upper(), "page": f["page"],
                "variant": f["variant"]}
    if src == "internet-archive":
        return {k: f[k] for k in ("source_work", "contributor", "ia_identifier", "page_index", "source_url",
                                  "pd_basis") if f.get(k)}
    if src == "various-web" and f.get("url"):
        return {"url": f["url"], "source_kind": f["source_kind"]}
    if src in ("lilith", "lilith-generated", "lilith-ai", "various-web"):
        return {}
    raise SystemExit(f"no attribution rule for source {src!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("originals")
    ap.add_argument("--ids", help="comma-separated manifest ids to keep")
    a = ap.parse_args()
    keep = set(a.ids.split(",")) if a.ids else None
    folders = folder_rows()
    n = 0
    for r in manifest_rows():
        if keep is not None and r["id"] not in keep:
            continue
        f = folders.get(r["path"])
        if f is None:
            raise SystemExit(f"{r['path']} has no per-folder manifest row")
        source = os.path.join(a.originals, r["path"])
        if not os.path.isfile(source):
            raise SystemExit(f"missing original {source}")
        prov = {"corpus": "imazen-26", "id": new_id(r["id"]), "split": r["split"], "category": f["category"],
                "source": f["source"], "license": f["license"]}
        prov.update(attribution(f["source"], f))
        prov["original_sha256"] = r["sha256"]
        fields = [new_id(r["id"]), source, stem(r["path"], r["id"]),
                  json.dumps(prov, ensure_ascii=True, separators=(",", ":"))]
        if any("\t" in v or "\n" in v for v in fields):
            raise SystemExit(f"a field for {r['id']} holds a tab or newline")
        sys.stdout.write("\t".join(fields) + "\n")
        n += 1
    if keep is not None and n != len(keep):
        raise SystemExit(f"{len(keep) - n} of the requested ids are not in the manifests")
    print(f"{n} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
