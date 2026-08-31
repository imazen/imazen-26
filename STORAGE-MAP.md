# imazen-26 — storage map

What exists, where the published copies live, and which artifacts are canonical.

**Canonical source of truth: this repository.** `imazen-26/` holds the per-folder
`MANIFEST.tsv` provenance files (in git), the aggregate `CORPUS-MANIFEST.tsv`, and the
split manifests under `imazen-26/manifests/`. Published image bytes are served from the
public R2 base (`https://codec-corpus.r2.imazen.org` — see [`ACCESS.md`](ACCESS.md)).
Anything not reachable from this repo plus `ACCESS.md` is a working copy, not a
distribution surface.

## Published surfaces (public HTTPS, no credentials)

| Layer | Location | Contents |
|---|---|---|
| Raw corpus | `…/imazen-26-unprocessed/<manifest path>` | the corpus images + manifests (ACCESS.md §1) |
| PNG derivatives | `…/imazen-26-png-v3/<render basename>.sdr.png` (+ `.hdr.png` for the 76 gain-map images) — **basename comes from [`variant-sets/png-v3-index.tsv`](variant-sets/png-v3-index.tsv), not from the corpus path**, because EXIF-rotated originals transpose the `WxH` token (ACCESS.md §2) | codec-test-ready PNG renders; 2,157 of 2,160 images have one |
| Multi-scale renditions + codec-encoded sweeps | `…/picker-sweep-2026-06-22/` | ACCESS.md §5–6 |

Known drift (recorded 2026-08-22): the R2 prefixes predate the final curation pass and
hold more objects than the 2,160-row canonical manifest (earlier mirror passes included
working material). A reconciliation pass to make each prefix exactly mirror the manifest
is queued. Until then, **`CORPUS-MANIFEST.tsv` is the membership oracle** — an object on
R2 with no manifest row is not part of the corpus.

## Variant branches (checkoutable render sets)

Derived render sets are distributed as `variant/*` branches in this repository,
with the image bytes in Git LFS. `main` still holds no image bytes — the split
is deliberate: canonical provenance stays small and cloneable, while a consumer
who wants pixels can take exactly one variant.

| Branch | Contents | Objects |
|---|---|--:|
| `variant/png-v3` | SDR (+ HDR where present) PNG renders, mirroring `imazen-26-png-v3/` | 1,983 |

```sh
git clone --branch variant/png-v3 --single-branch --depth 1 \
  https://github.com/imazen/imazen-26.git
```

Rules, enforced by `corpus-guard`:

- Image bytes on a `variant/*` branch must be LFS pointers, and
  `.gitattributes` must declare the LFS filter. A raw blob cannot be rewound out
  of a published branch, so the guard fails before it lands.
- Canonical branches keep the no-image-bytes rule unchanged.
- A `variant/*` branch is never merged into `main`.
- A new render pass gets a new branch (`variant/png-v4`) rather than rewriting an
  existing one, so a set someone cited stays reproducible.

Each variant branch carries a `VARIANT.md` stating what the set is, how it was
produced, and — importantly — where its coverage is incomplete. `variant/png-v3`
mirrors 1,961 of the 2,160 canonical images; the 199 renders that do not exist
on R2 are listed in that branch's `MISSING.tsv`.

The R2 prefixes remain available over plain HTTPS for consumers who want a
handful of files without git or an LFS client — see [`ACCESS.md`](ACCESS.md).

## Metadata policy (published files)

Camera-sourced files carry **whitelist EXIF only**: Make/Model/lens identification,
exposure parameters (FNumber, ExposureTime, ISO, FocalLength incl. 35mm-equivalent,
ApertureValue, ShutterSpeedValue, ExposureProgram, MeteringMode, ExposureCompensation,
WhiteBalance, Flash), capture dates, Orientation, ColorSpace, and the ICC profile.
No location tags, no serial numbers, no device or asset UUIDs — in any tag group, in
any format (jpg/heic/dng/png). Enforcement is a whitelist rewrite
(`exiftool -all= -tagsFromFile @ <keep-list> -icc_profile`), so unknown vendor tags fail
closed rather than silently surviving. Decoded pixel data — including HEIC auxiliary and
JPEG MPF gain maps — is hash-verified unchanged by the rewrite.

Verified 2026-08-22: 0/319 camera-folder files carry location or device-identifying
metadata, in this tree and in the published R2 copies (spot sha256 match between the
two).

Non-camera categories (museum, government-document, Internet Archive, AI-generated,
screenshot sets) retain the attribution-relevant metadata their licenses expect.

## Split manifests

`imazen-26/manifests/` carries the canonical train/validate/test split (deterministic,
by the last digit of the image id — see `manifests/README.md`). Derived datasets must
inherit an image's bucket from these manifests; do not invent per-dataset splits.

## Working copies

Operator-side working copies, staging pools, and pre-publication archives are indexed
in a private operations repo, not here. If a layer isn't listed above, it isn't
published.
