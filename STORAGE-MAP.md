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
| Git LFS objects of the `variant/*` branches | `…/lfs/imazen-26/<sha256>` | content-addressed copies of the branch renders; Git LFS reaches them through `imazen-lfs.pages.dev` (ACCESS.md §7) |

Known drift (recorded 2026-08-22): the R2 prefixes predate the final curation pass and
hold more objects than the 2,160-row canonical manifest (earlier mirror passes included
working material). A reconciliation pass to make each prefix exactly mirror the manifest
is queued. Until then, **`CORPUS-MANIFEST.tsv` is the membership oracle** — an object on
R2 with no manifest row is not part of the corpus.

## Variant branches (checkoutable render sets)

Derived render sets are distributed as `variant/*` branches in this repository,
with the image bytes in Git LFS — served from the `lfs/imazen-26/` prefix above
through imazen's [git-lfs-s3-proxy](https://github.com/imazen/git-lfs-s3-proxy)
instance, not from GitHub's LFS store. `main` still holds no image bytes — the
split is deliberate: canonical provenance stays small and cloneable, while a
consumer who wants pixels can take exactly one variant.

| Branch | Contents | Pointers |
|---|---|--:|
| `variant/png-v3` | SDR (+ HDR where present) PNG renders, mirroring `imazen-26-png-v3/` | 2,233 |
| `variant/pristine-8th` | artifact-free 1/8 references, SDR + HDR | 581 |

```sh
git clone --branch variant/png-v3 --single-branch --depth 1 \
  https://github.com/imazen/imazen-26.git
```

Rules, enforced by `corpus-guard`:

- Image bytes on a `variant/*` branch must be LFS pointers, and
  `.gitattributes` must declare the LFS filter. A raw blob cannot be rewound out
  of a published branch, so the guard fails before it lands.
- `.lfsconfig` must point Git LFS at `imazen-lfs.pages.dev` (or `lfs.imazen.org`)
  and carry no credentials: downloads are public, and an upload key stays in
  the maintainer's own git config.
- Canonical branches keep the no-image-bytes rule unchanged.
- A `variant/*` branch is never merged into `main`.
- A new render pass gets a new branch (`variant/png-v4`) rather than rewriting an
  existing one, so a set someone cited stays reproducible.

Each variant branch carries a `VARIANT.md` stating what the set is, how it was
produced, and — importantly — where its coverage is incomplete. `variant/png-v3`
mirrors 2,157 of the 2,160 canonical images; the three with no render are
listed in that branch's `MISSING.tsv`.

The R2 prefixes remain available over plain HTTPS for consumers who want a
handful of files without git or an LFS client — see [`ACCESS.md`](ACCESS.md).

## Metadata policy (published files)

As of the originals pass of 2026-10-15 (`EXPORT-PLAN.md`):

- **Camera photos (1000/1200/1400/1600)** carry **whitelist Exif only**, applied to the
  oldest copy of each file by our own container-aware code (`scripts/whitelist_v2.py`), so
  unknown vendor data fails closed.
  - Kept: Make, Model and lens identification; exposure parameters (FNumber, ExposureTime,
    ISO, FocalLength and its 35 mm equivalent, ApertureValue, ShutterSpeedValue,
    ExposureProgram, MeteringMode, ExposureCompensation, WhiteBalance, Flash); capture dates
    with sub-seconds; Orientation, ColorSpace and the pixel dimensions; the Interop sRGB
    marker; SubjectArea and SubjectLocation.
  - Colour and HDR structure stays as the camera wrote it: every ICC profile; in UltraHDR
    JPEGs the container XMP, the ISO 21496-1 records, a rebuilt MPF index and the gain-map
    JPEG; in HEICs every item and property (`colr`, `auxC`, `tmap`, grids, auxiliary
    images), with a MakerNote reduced to Apple's three HDR values where there is no `tmap`.
  - Removed: location tags, serial numbers, ImageUniqueID and other device or asset ids,
    OffsetTime*, HostComputer, Software, the rest of every MakerNote, IFD1 thumbnails, vendor
    APPn segments and comments, Samsung SEF data, and all of a HEIC's primary XMP but the
    camera's focus regions.
  - 1044, a motion photo, is published as a quality-100 JPEG of its still image (every
    quantizer 1, 4:4:4) without the embedded video.
  - The 3 DNGs keep their own tags as the August 2026 exiftool whitelist left them; their
    full-size JPEG previews get the keep-list above, applied in place.
- **Phone screenshots (8000)** get the same Exif keep-list and lose their SEF trailers.
- **Every other category** keeps the attribution-relevant metadata its licence expects
  (museum IPTC records and comments, PDF document information), except that the C2PA
  manifest stores (106 PNG `caBX` chunks, 5 JPEG APP11 segments) and the IPTC/XMP text
  chunks of 3 AI product PNGs are removed.
- **Every PNG** is recompressed losslessly by zenpng at effort 22 (`tools/png-crush`): ICC,
  Exif, the colour chunks and `pHYs` are kept, other ancillary chunks dropped, and each
  output decodes to its source's pixels in zenpng, Pillow and ImageMagick.

Before this pass, the camera photos carried an August 2026 exiftool whitelist rewrite
(`exiftool -all= -tagsFromFile @ <keep-list> -icc_profile`). It left coded image data
unchanged but also removed colour and HDR structure the policy meant to keep: the gain-map
images, MPF index, `hdrgm` XMP and ISO 21496-1 records of the 33 UltraHDR JPEGs; the HDR
headroom values Apple stores in the EXIF MakerNote for 24 HEIC gain maps; the `Flash` tag and
the EXIF Interop sRGB marker; and, in 22 HEICs, the primary image's colour profile. Details:
[`benchmarks/metadata_audit_earlier_copies_2026-09-25.md`](benchmarks/metadata_audit_earlier_copies_2026-09-25.md).

Checked 2026-08-22 on each file's top-level Exif and XMP: none of the 319 camera-folder
files carried location or device-identifying tags, in this tree or in the published R2
copies (spot sha256 match between the two). That check could not see inside 1044's embedded
motion-photo video or the DNGs' embedded JPEG previews; the originals pass of 2026-10-15
handles both, and the export's byte-scan and inventory gates now read whole files.

## Split manifests

`imazen-26/manifests/` carries the canonical train/validate/test split (deterministic,
by the last digit of the image id — see `manifests/README.md`). Derived datasets must
inherit an image's bucket from these manifests; do not invent per-dataset splits.

## Working copies

Operator-side working copies, staging pools, and pre-publication archives are indexed
in a private operations repo, not here. If a layer isn't listed above, it isn't
published.
