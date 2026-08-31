# variant/png-v3 — codec-test-ready PNG renders

SDR PNG renders of the imazen-26 corpus, plus the HDR renders. Use this layer
when you want decoded pixels without carrying the original camera formats or
their metadata.

**Coverage: 2,157 of the 2,160 canonical images (SDR), and all 76 HDR renders.**

## The manifest URLs are wrong for 196 images — read this before joining

The `png_v3_sdr_url` column in `manifests/{train,validate,test}.tsv` is derived
by swapping the extension on the corpus path. For images whose original carries
**EXIF Orientation = 6** (portrait phone photos, stored landscape), that derivation
is wrong: the PNG-v3 render pass applied the rotation and named the output by the
**rotated** dimensions, so the object on R2 is `…_3000x4000.sdr.png` while the
manifest asks for `…_4000x3000.sdr.png`.

**Fixed upstream on `main` (2026-08-30).** The split manifests no longer derive
render URLs: `png_v3_sdr_url` is corrected for all 196 rows, a `png_v3_hdr_url`
column is populated for the 76 images that have an HDR companion, and both are
generated from [`variant-sets/png-v3-index.tsv`](https://github.com/imazen/imazen-26/blob/main/variant-sets/png-v3-index.tsv)
— a probe of what actually exists on R2. **Use the manifest columns or that
index; never build a render URL from the corpus filename.**

[`RENDER-NAME-MAP.tsv`](RENDER-NAME-MAP.tsv) remains as the record of what was
wrong, and maps all 196 affected rows:
`id, corpus_path, manifest_sdr_url (404s), actual_sdr_url, actual_hdr_url`.
**Join through that file, not through `png_v3_sdr_url` alone.**

Measured 2026-08-30: 196 of the 199 URLs previously recorded as missing return
200 once the WxH token is transposed; a sample of 12 gave EXIF Orientation 6 for
all 12, against Orientation 1/3 for 12 sampled rows whose manifest URL resolves.
Every recovered file's IHDR matches its (transposed) filename token, 196/196.

## Still absent: 3 renders

| id | source | why |
|---|---|---|
| 1444 | `.dng` | no PNG-v3 render at any probed name |
| 1455 | `.dng` | no PNG-v3 render at any probed name |
| 1458 | `.dng` | no PNG-v3 render at any probed name |

These are the corpus's only three DNG originals; the render pass appears to have
skipped that format. Twelve name variants were probed per file (as-is,
transposed, `.dng.sdr.png`, `.png`, …) — all 404. The raw `.dng` originals are
present under `imazen-26-unprocessed/`. Listed in [`MISSING.tsv`](MISSING.tsv).

## HDR

All **76** gain-map origins have a 16-bit `.hdr.png` render, and all 76 are here.
This matches `ACCESS.md` §2 and the registered variant set
[`hdr-grid-15scale@2026-06-14`](variant-sets/hdr-grid-15scale@2026-06-14/SET.md)
(76 origins × 15 scales = 1,140 files), whose origin basenames are identical to
the 76 `.hdr.png` objects found by sweeping the whole manifest namespace.

54 of the 76 are named by rotated dimensions for the same reason as above, which
is why an earlier pass that derived HDR names from `png_v3_sdr_url` found only 22.

**This branch is not the corpus.** `main` is: it carries the provenance
manifests, the canonical split, and the variant registry, and it holds no image
bytes at all. This branch adds one derived render set, distributed through Git
LFS so it can be checked out directly instead of fetched object by object.

## Getting it

```sh
# just this variant, no corpus history
git clone --branch variant/png-v3 --single-branch --depth 1 \
  https://github.com/imazen/imazen-26.git
```

Pointers only, then pull the bytes you actually need:

```sh
GIT_LFS_SKIP_SMUDGE=1 git clone --branch variant/png-v3 --single-branch --depth 1 \
  https://github.com/imazen/imazen-26.git
cd imazen-26
git lfs pull --include "png-v3/8100-lilith-web-screenshots/**"
```

The same bytes remain available over plain HTTPS with no git and no LFS client —
see [`ACCESS.md`](ACCESS.md) §2. Use that when you want a handful of files, or
when LFS bandwidth is the wrong cost to pay.

## Layout

```
png-v3/<category>/<basename>.sdr.png     2,157 files
png-v3/<category>/<basename>.hdr.png     76 files
RENDER-NAME-MAP.tsv                      196 rows whose manifest URL 404s
MISSING.tsv                              3 renders absent from R2
```

**Size: 15.4 GB across 2,233 objects** (2,157 SDR + 76 HDR), measured on disk
2026-08-30. `ACCESS.md` quotes 16 GB / 2,639 objects for the `imazen-26-png-v3/`
prefix as a whole; the residual ~406 objects are the drift `STORAGE-MAP.md`
records (the prefix predates the final curation pass). This branch mirrors only
the manifest-referenced subset.

Paths mirror the **R2 object names**, which for the 196 EXIF-rotated images are
not what `png_v3_sdr_url` says. A row in `manifests/{train,validate,test}.tsv`
joins by stripping the R2 base from `png_v3_sdr_url`, **except** for the 196 rows
in `RENDER-NAME-MAP.tsv`, which join through its `actual_sdr_url` column. Keeping
the R2 name is deliberate: this branch is a byte- and name-exact mirror of the
prefix, so the divergence lives in a map file rather than in renamed bytes.

## Provenance

Rendered by the PNG-v3 pass; the R2 prefix `imazen-26-png-v3/` is the origin of
these exact bytes and this branch is a mirror of it, not a re-render. Membership
is the 2,160-row canonical manifest on `main` — `CORPUS-MANIFEST.tsv` is the
oracle, and an object present on R2 without a manifest row is not part of the
corpus.

Metadata: these renders carry no EXIF at all (PNG conversion drops it). The
metadata whitelist policy that governs the original files is described in
[`STORAGE-MAP.md`](STORAGE-MAP.md).

## Verification

Every committed file was checked for the PNG signature `89504e470d0a1a0a` — three
R2 404 pages had landed as `.sdr.png` from a fetch that omitted `curl -f`, and were
removed. Byte-exactness against R2 was confirmed by sha256 on a random sample. The
250 files recovered on 2026-08-30 were fetched with `curl -sSf`, signature-checked
before staging and again after copy into the tree, and their IHDR dimensions were
checked against their filenames (250/250 agree).

`scripts/fetch-variant-png-v3.sh` is the tool that built the branch; it now
rejects any non-PNG response before staging, since a bad blob cannot be rewound
out of a pushed branch.

## Rules for this branch

- Image bytes here are **LFS pointers only**. `corpus-guard` fails the branch if
  a raw blob is committed — a raw blob cannot be rewound out of a published
  branch.
- Never merge a `variant/*` branch into `main`. Canonical stays byte-free.
- Renders are not regenerated in place. A new render pass gets a new branch
  (`variant/png-v4`), so an existing set stays reproducible.
