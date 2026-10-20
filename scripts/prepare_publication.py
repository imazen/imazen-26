#!/usr/bin/env python3
"""Stage publication cards, branch manifests and source lists without copying images.

The default follows EXPORT-PLAN.md. --sets compact selects originals, JXL and XL.
No repository, branch, tag or remote object is created by this preparation step.
"""
import argparse
import csv
import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import export_card
import export_manifests
import render_v4_list


BUCKETS = ("train", "validate", "test")
REPO = Path(__file__).resolve().parents[1]

DECODING = """# Decoding the files

Start from the `train` branch. `validate` and `test` are holdouts: do not use
them for fitting, tuning, threshold selection or selecting codec defaults.
Related sources and every rendition of an image keep the same bucket.
The repository README gives the branches available in this repository.

## Git LFS in the XL repository

The ordinary originals and JXL repositories contain image bytes directly.
`imazen-xl-26` uses Git LFS for its image files. Install Git LFS before cloning,
or fetch the image bytes after an existing clone:

```sh
git lfs install
git lfs pull
```

Its committed `.lfsconfig` selects the public R2-backed LFS endpoint. A small
text file beginning `version https://git-lfs.github.com/spec/v1` is a pointer;
run `git lfs pull` to retrieve the image it names.

## PNG

Use a PNG decoder that preserves the stored bit depth and colour metadata.
The `p3` collection contains sRGB and Display P3 images. Adobe RGB sources
are converted to Display P3 using relative colorimetric intent and gamut clipping.
Honour the ICC/cICP or sRGB
signalling instead of interpreting every RGB buffer as sRGB.

For example, ImageMagick can read a PNG into a PPM for inspection:

```sh
magick input.png output.ppm
```

Keep the PNG when testing metadata: a PPM does not carry its colour profile,
provenance or HDR signalling. The `.hdr.png` files hold 16-bit PQ-encoded
samples in Display P3, with a 203-nit diffuse white. They need an HDR-aware
display path or an explicit tone map for an SDR preview. Reading 16-bit RGB
through an 8-bit-only image API loses precision.

## JPEG XL

The files were checked with libjxl 0.12.0, jxl-rs and zenjxl. With libjxl's
decoder tools:

```sh
jxlinfo input.jxl
djxl input.jxl output.png --num_threads=1
```

Lossless JXL files have the same samples as their PNG twins. Files whose
manifest form is `jpeg-in-jxl` instead retain JPEG coefficients and JPEG
reconstruction data. Reconstruct those with:

```sh
djxl input.jxl reconstructed.jpg --num_threads=1
```

The reconstructed JPEG must match `original_sha256`. JPEG pixel decoders may
differ in rounding; use the recorded decoder when comparing its pixel hash.
The `jhgm` box carries a separate gain-map image and ISO 21496-1 parameters.
A normal SDR decode does not apply the gain map. Use a decoder that implements
gain-map HDR reconstruction, or the explicit PQ twin where supplied.

## Originals and hashes

Originals retain their encoded format and orientation metadata. Apply the
orientation when comparing them with the rendered layers. HEIC, UltraHDR JPEG
and DNG require their respective decoders; DNGs have no rendered twins here.

`sha256` hashes encoded file bytes. `pixels_sha256` is a renderer-specific
sample-buffer hash, not a hash of another encoded PNG or JPEG. For cross-decoder
tests, the [readback tool documentation](https://github.com/imazen/imazen-26/tree/main/tools/jxl-decode-check)
defines the separate XXH3-64 tables: native channel layout, tightly packed rows,
displayed orientation, and little-endian samples above 8 bits.

See the [validation record](https://github.com/imazen/imazen-26/blob/main/benchmarks/render_v4_validation_2026-10-15.md)
for reader-specific limits and the checks performed on the stored files.
"""


def read_table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def write_table(path, rows, fields):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def special_card(name, layer, rows, version):
    kinds = Counter(row["layer"] for row in rows)
    lines = [f"# {name}", "", "imazen-26 is a corpus for testing image codecs and image processing.", ""]
    if layer == "originals":
        lines += ["This repository holds JPEG, PNG and HEIC source files byte for byte;",
                  "their encoded metadata and orientation remain in the files.",
                  "The DNG originals and other XL images are in",
                  "[imazen-xl-26](https://github.com/imazen/imazen-xl-26).", ""]
    elif layer == "xl":
        lines += ["This repository holds all three DNG originals and every public layer of images",
                  "with a file exceeding GitHub's 100 MiB limit. DNG 11444 joins the larger",
                  "DNGs here so the ordinary originals and JXL sets have identical membership.",
                  "These ids are excluded from the ordinary repositories. Image bytes use Git LFS.", ""]
    else:
        colour = "sRGB and Display P3 (Adobe RGB sources converted to Display P3)" if layer.endswith("p3") else "sRGB"
        encoding = "JPEG XL" if layer.startswith("jxl") else "PNG"
        lines += [f"This repository holds {encoding} renders in {colour}.",
                  "The XL images are in [imazen-xl-26](https://github.com/imazen/imazen-xl-26).",
                  "DNG sources are in imazen-xl-26 and have no rendered twins.", ""]
        if layer.startswith("jxl"):
            lines += ["Lossless files preserve their PNG twins' samples. JPEG-in-JXL files retain",
                      "JPEG coefficients and reconstruct the original JPEG byte for byte.", ""]
        if layer.endswith("p3"):
            lines += ["Gain-map sources include explicit 16-bit PQ HDR twins; JPEG XL also carries",
                      "gain maps in `jhgm` boxes. See the decoding guide for HDR handling.", ""]
    lines += [f"Version {version}: {len({r['id'] for r in rows})} images,",
              f"{len(rows)} files, {sum(int(r['bytes']) for r in rows)} encoded bytes.", "",
              "| branch | images | files | bytes |", "|---|---:|---:|---:|"]
    for bucket in BUCKETS:
        chosen = [r for r in rows if r["bucket"] == bucket]
        lines.append(f"| `{bucket}` | {len({r['id'] for r in chosen})} | {len(chosen)} | {sum(int(r['bytes']) for r in chosen)} |")
    lines += ["", "`main` contains documentation. Each data branch contains only its own bucket.",
              "Related sources and all renditions share a bucket. Do not train or tune on",
              "`validate` or `test`; keep both out of fitting and default selection.", "",
              "```sh", f"git clone --branch train --single-branch --depth 1 https://github.com/imazen/{name}.git", "```", "",
              "See [DECODING.md](DECODING.md) for decoder commands, colour/HDR handling and hashes.", "",
              "`manifest.tsv` identifies each file, its bucket, encoded SHA-256, licence and",
              "source provenance. The image licences differ; the Unsplash files retain the",
              "[Unsplash License](https://unsplash.com/license), while the other files are",
              "public domain or CC0 as specified per row. `provenance_json` preserves attribution",
              "and source URLs. The corpus tooling's software licence does not replace these licences.", "",
              "Layers: " + ", ".join(f"{k} ({v})" for k, v in sorted(kinds.items())) + ".", "",
              "Source and validation: [imazen-26](https://github.com/imazen/imazen-26).", ""]
    return "\n".join(lines)


def review_pages(root, plan):
    style = "body{max-width:1100px;margin:2em auto;padding:0 1em;font:16px system-ui;line-height:1.5}pre{white-space:pre-wrap;background:#f4f5f7;padding:1.2em}td,th{padding:.45em .8em;text-align:left}table{border-collapse:collapse}tr{border-bottom:1px solid #ddd}"
    def document(title, body):
        return f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(title)}</title><style>{style}</style><body>{body}</body></html>'
    def markdown_source(text):
        escaped = html.escape(text)
        def link(match):
            target = match[2]
            if target == "DECODING.md":
                target = "#decoding"
            return f'<a href="{target}">{match[1]}</a>'
        return "<pre>" + re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, escaped) + "</pre>"
    items = []
    for row in plan:
        name = row["repository"]
        base = root / name
        body = '<p><a href="../index.html">All repositories</a></p><h1>' + html.escape(name) + '</h1>'
        body += '<p>README text proposed for publication. Image files and Git branches have not been published.</p>'
        body += markdown_source((base / "main/README.md").read_text())
        body += '<h2 id="decoding">Decoding instructions</h2>' + markdown_source((base / "main/DECODING.md").read_text())
        body += '<h2>Branch manifests</h2><ul>'
        for branch in row["branches"]:
            body += f'<li><a href="{branch}/manifest.tsv">{branch} manifest</a> — SHA-256 {row["manifest_sha256"][branch]}</li>'
        body += '</ul><p><a href="main/CITATION.cff">CITATION.cff</a></p>'
        (base / "review.html").write_text(document(name, body))
        items.append(f'<tr><td><a href="{name}/review.html">{name}</a></td><td>{row["images"]}</td><td>{row["files"]}</td><td>{row["bytes"]:,}</td><td>{", ".join(row["branches"])}</td></tr>')
    intro = '<h1>imazen-26 publication review</h1><p>Prepared README text, decoding instructions and exact branch membership. No repositories, branches, tags or image bytes have been published by this staging step.</p>'
    intro += '<p>XL holds all three DNGs and every public layer of the five size-limit images, including their PNG twins. Ordinary PNG render repositories are a separate publication phase; IMI remains private.</p>'
    table = '<table><tr><th>Repository</th><th>Images</th><th>Files</th><th>Bytes</th><th>Data branches</th></tr>' + ''.join(items) + '</table>'
    (root / "index.html").write_text(document("imazen-26 publication review", intro + table))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("render", type=Path)
    parser.add_argument("originals", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--sets", choices=("plan", "compact"), default="plan")
    parser.add_argument("--version", default="2026.10.19")
    parser.add_argument("--date", default="2026-10-19")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    policy = read_table(REPO / "manifests/export_xl.tsv")
    xl_ids = {row["id"] for row in policy}
    oversize_ids = {row["id"] for row in policy if row["reason"] == "file_over_100_mib"}
    buckets = render_v4_list.family_buckets()
    families = defaultdict(set)
    for row in read_table(REPO / "manifests/split_map_family_v2.tsv"):
        if row["family"]:
            families[row["family"]].add(row["split"])
    if any(len(found) != 1 for found in families.values()):
        raise ValueError("a related-image family crosses holdout buckets")
    folders = render_v4_list.folder_rows()
    provenance, sources, layers = {}, {}, {}
    originals = []
    for bucket in BUCKETS:
        for row in read_table(REPO / "manifests" / f"{bucket}.tsv"):
            old, cid = row["id"], "1" + row["id"]
            source = args.originals / row["path"]
            if source.stat().st_size != int(row["bytes_actual"]):
                raise ValueError(f"original size mismatch: {cid}")
            folder = folders[row["path"]]
            prov = {"corpus": "imazen-26", "id": cid, "split": buckets[old],
                    "category": folder["category"], "source": folder["source"],
                    "license": folder["license"], "original_sha256": row["sha256"]}
            prov.update(render_v4_list.attribution(folder["source"], folder))
            provenance[cid] = json.dumps(prov, ensure_ascii=True, separators=(",", ":"))
            pieces = Path(row["path"]).parts
            path = str(Path("1" + pieces[0], *pieces[1:-1], "1" + pieces[-1]))
            record = dict.fromkeys(export_manifests.COLUMNS, "")
            record.update(id=cid, bucket=buckets[old], path=path, form="original",
                          bytes=row["bytes_actual"], sha256=row["sha256"],
                          original_sha256=row["sha256"], license=folder["license"],
                          source=folder["source"], layer="originals", provenance_json=provenance[cid])
            originals.append(record)
            sources[("originals", path)] = str(source)
    layers["originals"] = originals
    for layer in export_card.LAYERS:
        rows = read_table(args.render / "manifests" / f"{layer}.tsv")
        for row in rows:
            if row["bucket"] != buckets[row["id"][1:]]:
                raise ValueError("layer bucket differs from family map")
            source = args.render / row["path"]
            if source.stat().st_size != int(row["bytes"]):
                raise ValueError("layer size mismatch")
            row["path"] = row["path"].removeprefix(layer + "/")
            sources[(layer, row["path"])] = str(source)
            row.update(layer=layer, provenance_json=provenance[row["id"]])
        layers[layer] = rows
    measured_xl = {r["id"] for rows in layers.values() for r in rows if int(r["bytes"]) > 100 * 1024**2}
    if measured_xl != oversize_ids:
        raise ValueError("XL membership changed")
    specs = [("imazen-26-originals", "originals", None)]
    if args.sets == "plan":
        specs += [(f"imazen-26-{layer}-{bucket}", layer, bucket)
                  for layer in ("png-p3", "png-srgb") for bucket in BUCKETS]
    specs += [(f"imazen-26-{layer}", layer, None) for layer in ("jxl-p3", "jxl-srgb")]
    specs += [("imazen-xl-26", "xl", None)]
    plan = []
    for name, layer, only_bucket in specs:
        rows = [dict(r) for key, items in layers.items() for r in items
                if (layer == "xl" and r["id"] in xl_ids) or
                (key == layer and r["id"] not in xl_ids and (only_bucket is None or r["bucket"] == only_bucket))]
        if layer == "xl":
            for row in rows:
                row["path"] = row["layer"] + "/" + row["path"]
        total = sum(int(row["bytes"]) for row in rows)
        if layer != "xl" and total >= 10_000_000_000:
            raise ValueError("repository exceeds the export plan's 10 GB payload budget")
        repository = args.out / name
        fields = list(rows[0])
        hashes = {}
        for bucket in (None, *(BUCKETS if only_bucket is None else (only_bucket,))):
            selected = rows if bucket is None else [r for r in rows if r["bucket"] == bucket]
            dest = repository / (bucket or "main")
            dest.mkdir(parents=True)
            (dest / "README.md").write_text(special_card(name, layer, rows, args.version))
            (dest / "CITATION.cff").write_text(f'cff-version: 1.2.0\ntype: dataset\nmessage: "Please cite this dataset."\ntitle: "{name}"\nversion: "{args.version}"\nauthors:\n  - family-names: "River"\n    given-names: "Lilith"\n    affiliation: "Imazen"\nrepository: "https://github.com/imazen/{name}"\n')
            (dest / "DECODING.md").write_text(DECODING)
            if layer == "xl":
                (dest / ".lfsconfig").write_bytes((REPO / ".lfsconfig").read_bytes())
                (dest / ".gitattributes").write_text("".join(
                    f"{prefix}/** filter=lfs diff=lfs merge=lfs -text\n" for prefix in layers))
            write_table(dest / "manifest.tsv", selected, fields)
            hashes[bucket or "main"] = hashlib.sha256((dest / "manifest.tsv").read_bytes()).hexdigest()
            source_rows = []
            for row in selected:
                old_path = row["path"].removeprefix(row["layer"] + "/") if layer == "xl" else row["path"]
                source_rows.append({"path": row["path"], "source": sources[(row["layer"], old_path)],
                                    "bytes": row["bytes"], "sha256": row["sha256"]})
            write_table(repository / f"{bucket or 'main'}.sources.tsv", source_rows,
                        ["path", "source", "bytes", "sha256"])
        plan.append({"repository": name, "layer": layer, "lfs": layer == "xl", "files": len(rows),
                     "images": len({r["id"] for r in rows}), "bytes": total,
                     "manifest_sha256": hashes,
                     "branches": list(BUCKETS if only_bucket is None else (only_bucket,))})
    (args.out / "publication-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    review_pages(args.out, plan)
    print(json.dumps({"repositories": len(plan), "files": sum(r["files"] for r in plan),
                      "bytes": sum(r["bytes"] for r in plan), "sets": args.sets}))


if __name__ == "__main__":
    main()
