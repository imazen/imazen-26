#!/usr/bin/env python3
"""Write the dataset card (README.md), CITATION.cff and manifest.tsv of one export repository
(EXPORT-PLAN.md, "Repositories" and "Release").

    export_card.py <render-dir> <layer> <out-dir> --repo NAME --version X.Y.Z --date YYYY-MM-DD
                   [--bucket train|validate|test] [--exclude-ids 12402,...]

<layer> is one of png-p3, png-srgb, jxl-p3, jxl-srgb (the per-layer manifests that
export_manifests.py writes into <render-dir>/manifests/). Without --bucket the repository holds
all three buckets, one per branch; with it, only that bucket. --exclude-ids leaves out the
images that live in imazen-xl-26 instead.

Every number in the card comes from the manifest rows the repository holds; the tool commits
come from RUN.meta. Writes <out-dir>/README.md, <out-dir>/CITATION.cff and
<out-dir>/manifest.tsv (the rows, in id order).
"""
import argparse
import collections
import csv
import os
import sys

BUCKETS = ("train", "validate", "test")

LAYERS = {
    "png-p3": ("PNG, source colour",
               "lossless PNG renders that keep each source's own colour space and code values "
               "(sRGB, Display P3 or Adobe RGB), plus a 16-bit PQ HDR render beside each "
               "gain-map photo"),
    "png-srgb": ("PNG, sRGB",
                 "lossless PNG renders in sRGB: Display P3 and Adobe RGB sources converted "
                 "relative colorimetric through linear light, out-of-gamut colours clipped"),
    "jxl-p3": ("JPEG XL, source colour",
               "JPEG XL twins of the `png-p3` files: lossless JPEG XL with the same pixels, and "
               "JPEG-in-JXL for JPEG sources, which rebuilds the original JPEG byte for byte; "
               "gain-map photos carry their gain map as a `jhgm` box, and each HDR render has "
               "a lossless 16-bit PQ twin"),
    "jxl-srgb": ("JPEG XL, sRGB",
                 "JPEG XL twins of the `png-srgb` files: lossless JPEG XL with the same pixels, "
                 "and JPEG-in-JXL for sRGB JPEG sources, which rebuilds the original JPEG byte "
                 "for byte"),
}

LICENCE_NOTES = {
    "PD-own": "the maintainer's own photos, plots and AI images, dedicated to the public domain",
    "PD": "US patents and Internet Archive scans of public-domain works (`pd_basis` per file)",
    "PD-USGov": "works of the US federal government (17 USC §105): NPS, EPA, NOAA",
    "Unsplash-License": "free to use under the Unsplash License; attribution appreciated "
                        "(photographer in the provenance)",
    "CC0": "Art Institute of Chicago and Met open-access reproductions",
}
# Labels whose meaning the owner hasn't settled (EXPORT-PLAN.md): the card says so.
PENDING = "label under owner review before release"


def meta(render):
    out = {}
    for line in open(os.path.join(render, "RUN.meta")):
        k, _, v = line.rstrip("\n").partition("\t")
        out[k] = v
    return out


def gb(n):
    return f"{n / 1e9:.2f} GB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("render")
    ap.add_argument("layer", choices=sorted(LAYERS))
    ap.add_argument("out")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--bucket", choices=BUCKETS)
    ap.add_argument("--exclude-ids", default="")
    a = ap.parse_args()
    exclude = {i for i in a.exclude_ids.split(",") if i}
    path = os.path.join(a.render, "manifests", f"{a.layer}.tsv")
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        columns = reader.fieldnames
        rows = [r for r in reader if r["id"] not in exclude and (a.bucket is None or r["bucket"] == a.bucket)]
    if not rows:
        sys.exit("no rows")
    rows.sort(key=lambda r: (r["id"], r["form"]))
    m = meta(a.render)
    buckets = [a.bucket] if a.bucket else list(BUCKETS)

    images = {r["id"] for r in rows}
    per_bucket = collections.OrderedDict(
        (b, (len({r["id"] for r in rows if r["bucket"] == b}),
             sum(1 for r in rows if r["bucket"] == b),
             sum(int(r["bytes"]) for r in rows if r["bucket"] == b))) for b in buckets)
    licences = collections.Counter()
    for i in images:
        licences[next(r["license"] for r in rows if r["id"] == i)] += 1
    forms = collections.Counter(r["form"] for r in rows)
    colours = collections.Counter(r["colour"] for r in rows if r["form"] not in ("hdr-pq", "lossless-pq"))
    hdr = sum(1 for r in rows if r["form"] in ("hdr-pq", "lossless-pq"))
    clipped = sum(1 for r in rows if r["clipped"] not in ("", "0"))
    title, what = LAYERS[a.layer]
    scope = f"the {a.bucket} bucket" if a.bucket else "all three buckets, one branch each"

    out = []
    w = out.append
    w(f"# imazen-26: {title}" + (f", {a.bucket}" if a.bucket else ""))
    w("")
    w("imazen-26 is a test corpus for image codecs and image processing: camera photos "
      "(HEIC and UltraHDR JPEG with gain maps among them), stock photos, artwork reproductions, "
      "born-digital government documents, document and manuscript scans, synthetic charts, UI "
      "screenshots and AI-generated graphics. It covers what codecs trip on: photographic "
      "noise, hard-edged graphics, bilevel scans, dense text and flat regions.")
    w("")
    w(f"This repository holds {what}, for {len(images):,} images in {scope} "
      f"({len(rows):,} files, {gb(sum(int(r['bytes']) for r in rows))}). Version {a.version}.")
    w("")
    w("| bucket | branch | images | files | size |")
    w("|---|---|--:|--:|--:|")
    for b, (n_img, n_files, n_bytes) in per_bucket.items():
        w(f"| {b} | `{b}` | {n_img:,} | {n_files:,} | {gb(n_bytes)} |")
    w("")
    w("```sh")
    w(f"git clone --branch {buckets[0]} --single-branch --depth 1 https://github.com/imazen/{a.repo}.git")
    w("```")
    w("")
    w("## Files")
    w("")
    w("Each file is named `<class folder>/<id>_<category>_<descriptor>_<W>x<H>.<ext>`. The id is "
      "the corpus id with a leading 1 (five digits); `W`x`H` is the displayed size, with the "
      "source's orientation already applied to the pixels.")
    w("")
    w("`manifest.tsv` has one row per file: " + ", ".join(f"`{c}`" for c in columns) + ". "
      "`pixels_sha256` is the decoded pixels' hash; a lossless file has its PNG twin's.")
    w("")
    w("Forms: " + ", ".join(f"{n:,} `{k}`" for k, n in sorted(forms.items())) + ". Colour: "
      + ", ".join(f"{n:,} `{k}`" for k, n in sorted(colours.items())) + "."
      + (f" {hdr} files are 16-bit PQ HDR renders (`cICP` 12/16, BT.2408 diffuse white at "
         "203 nits, measured `cLLI`)." if hdr else ""))
    w("")
    w("Each file carries one provenance record, JSON with the corpus id, bucket, category, "
      "source, licence, attribution and the original's sha256; nothing about where or with "
      "what a photo was taken. PNG files hold it in a `tEXt` chunk with keyword `imazen-26`; "
      "lossless JPEG XL files as XMP (`imazen26:provenance`). A JPEG-in-JXL file keeps the "
      "JPEG's own metadata instead, which the byte-exact rebuild needs.")
    w("")
    w("## Buckets")
    w("")
    w("Buckets follow `manifests/split_map_family_v2.tsv` in imazen/imazen-26: related images "
      "share one bucket (a patent page's 1-bit original and its rescans, the pages of one "
      "URL, a photo burst, a plot run, identical files). Every derivative of an image belongs "
      "to its bucket. Don't train or tune on `validate` or `test`.")
    w("")
    w("## Licences")
    w("")
    w("| licence | images | what |")
    w("|---|--:|---|")
    for lic, n in licences.most_common():
        w(f"| {lic} | {n:,} | {LICENCE_NOTES.get(lic, PENDING)} |")
    w("")
    w("`license` is assigned per source folder, as a best effort, not per-file legal "
      "clearance. Artwork photos are reproductions of public-domain works. Document and "
      "screenshot pages can embed third-party logos or photos whose rights differ from the "
      "page's. The phone-screenshot captures are released CC0, but where a frame shows "
      "third-party app or web content, that content is included under fair use, not "
      "relicensed. Check embedded media before redistributing.")
    w("")
    w("## How the files were made")
    w("")
    w("`tools/render-v4` in imazen/imazen-26 rendered every file from the originals, built "
      "against the main branch of every imazen crate. Each manifest row names the tool commit "
      "and `Cargo.lock` hash that wrote its file. Before release, every file passed: "
      "re-decode to the written pixels; a third-party read-back (libpng, Pillow, ImageMagick "
      "and netpbm for PNG; libjxl for JPEG XL); an inventory of every part of the file and a "
      "byte scan for nested media and location data; for the sRGB layers, a textbook "
      "colour conversion of each wide-gamut file's own `p3` twin; for HDR, a rebuild from "
      "third-party decodes.")
    w("")
    passes = [("SDR render", "tool_commit")]
    passes += [(f"redo {k.split('_')[1]}", k) for k in sorted(m) if k.startswith("redo_") and k.endswith("_tool_commit")]
    if a.layer == "png-p3" or a.layer == "jxl-p3":
        passes.append(("HDR pass", "hdr_tool_commit"))
    if a.layer.startswith("jxl"):
        passes.append(("JPEG XL pass", "jxl_tool_commit"))
        passes += [(f"JPEG XL redo {k.split('_')[2]}", k) for k in sorted(m)
                   if k.startswith("jxl_redo_") and k.endswith("_tool_commit")]
    w("imazen-26 commits: " + "; ".join(f"{name} `{m[k][:12]}`" for name, k in passes if m.get(k)) + ".")
    w("")
    w("## Known limitations")
    w("")
    if a.layer.endswith("srgb"):
        w(f"- Wide-gamut colours are clipped to sRGB; {clipped:,} files clip at least one pixel "
          "and `clipped` gives the count per file.")
    codestreams = sum(1 for r in rows if r["form"].startswith("jpeg-in-jxl-codestream"))
    if codestreams:
        w(f"- {codestreams} progressive Unsplash JPEGs can't carry JPEG reconstruction data (a scan "
          "exceeds the `jbrd` range); their files are a JPEG XL codestream of the same DCT "
          "coefficients, without a byte-exact rebuild.")
    if a.layer.startswith("jxl"):
        w("- A JPEG-in-JXL file's pixels depend on the decoder, like the JPEG's own; its "
          "`pixels_sha256` is zenjxl-decoder's decode in displayed orientation.")
    w("- The three Samsung DNGs are in the originals only.")
    w("- HEIC decoders differ by a few code values at saturated edges; the renders use the zen "
      "decode.")
    w("")
    w("## Citing")
    w("")
    w("See `CITATION.cff`.")
    w("")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "README.md"), "w") as f:
        f.write("\n".join(out))
    with open(os.path.join(a.out, "CITATION.cff"), "w") as f:
        f.write(f"""cff-version: 1.2.0
message: "If you use this corpus, please cite it as below."
type: dataset
title: "imazen-26: {title}"
version: "{a.version}"
date-released: "{a.date}"
authors:
  - family-names: "River"
    given-names: "Lilith"
    affiliation: "Imazen"
repository: "https://github.com/imazen/{a.repo}"
url: "https://github.com/imazen/imazen-26"
keywords:
  - image codecs
  - image corpus
  - HDR
  - JPEG XL
  - PNG
""")
    with open(os.path.join(a.out, "manifest.tsv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=columns, delimiter="\t", lineterminator="\n")
        wr.writeheader()
        wr.writerows(rows)
    print(f"{a.repo}: {len(images)} images, {len(rows)} files")


if __name__ == "__main__":
    main()
