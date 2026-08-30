# variant/png-v3 — codec-test-ready PNG renders

SDR PNG renders of the imazen-26 corpus, plus HDR renders where they exist. Use
this layer when you want decoded pixels without carrying the original camera
formats or their metadata.

**Coverage: 1,961 of the 2,160 canonical images.** 199 renders do not exist in
the `imazen-26-png-v3/` R2 prefix that this branch mirrors, so they are not here
either; every one of them is listed in [`MISSING.tsv`](MISSING.tsv) with the URL
that 404s. The gap is not spread evenly — it falls entirely in the four
camera-original categories:

| category | missing | of |
|---|--:|--:|
| 1400-lilith-nature | 99 | 157 |
| 1000-lilith-photos-general | 45 | 72 |
| 1200-lilith-interiors | 31 | — |
| 1600-lilith-food | 24 | — |

Measured by HEAD request against every `png_v3_sdr_url` in the split manifests on
2026-08-30. Anything selecting on those categories should treat coverage as
partial and check `MISSING.tsv` rather than assuming a render exists.

22 images have an `.hdr.png` companion. `ACCESS.md` describes 76 gain-map
images, so either the HDR pass is also partial or the two counts mean different
things — unresolved, and worth a look before anyone depends on the HDR layer.

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
png-v3/<category>/<basename>.sdr.png     1,961 files
png-v3/<category>/<basename>.hdr.png     22 files
MISSING.tsv                              199 renders absent from R2
```

**Size: 8.7 GB across 1,983 objects** (1,961 SDR + 22 HDR) (mean 4.5 MB), measured from
Content-Length on 2026-08-30. `ACCESS.md` quotes 16 GB / 2,639 objects for the
`imazen-26-png-v3/` prefix as a whole — the prefix holds more objects than the
2,160-row canonical manifest, which `STORAGE-MAP.md` already records as known
drift. This branch mirrors only the manifest-referenced subset.

Paths mirror the corpus layout on `main`, so a row in
`manifests/{train,validate,test}.tsv` joins to a file here by taking the
`png_v3_sdr_url` column and stripping the R2 base prefix.

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

Every committed file was checked for the PNG signature — three R2 404 pages had
landed as `.sdr.png` from a fetch that omitted `curl -f`, and were removed.
Byte-exactness against R2 was confirmed by sha256 on a random sample.

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
