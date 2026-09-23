# Split branches, lossless twins, and variant layers — design proposal (2026-09-22)

**Status: proposal, awaiting decisions (last section).** The question: can the
corpus ship as `train` / `eval` / `test` branches that hold the images themselves,
with `.png` and `.jxl` twins for decoder consistency, and should any of that live in
separate repositories? This note measures what each layout would weigh, then proposes
one, including how it treats HDR, colour profiles and crop/scale/subset variants.

## What bounds the layout

**GitHub** (docs.github.com, "Repository limits", fetched 2026-09-22):

| limit | value |
|---|---|
| on-disk size | **10 GB per repository** (the "large files" page: ideally <1 GB, <5 GB strongly recommended) |
| push | 2 GB per push |
| file | 100 MB hard block (1 MB recommended) |
| directory width | 3,000 entries |
| branches | 5,000 |

Three consequences follow from how git stores objects:

- **Branches share one object store.** `train`, `validate` and `test` branches in one
  repository draw on the same 10 GB, not 10 GB each.
- **History only grows.** A re-render adds its full size and the old blobs stay
  reachable (and live on in every clone and fork). The registry already treats sets as
  immutable, so every render pass is a permanent addition.
- **Images don't compress further** inside git's packs.

**What we would put in them** (measured 2026-09-22 from the manifests and the
`/mnt/v` copies; GiB):

| bucket | ids | originals | png-v3 SDR | png-v3 HDR (76 ids) | largest SDR render |
|---|--:|--:|--:|--:|--:|
| train | 1,084 | 2.79 | 5.27 | 1.90 | 121.8 MB |
| validate | 661 | 1.70 | 3.23 | 0.99 | 103.6 MB |
| test | 415 | 0.99 | 2.04 | 0.89 | 83.3 MB |
| **all** | **2,160** | **5.47** | **10.54** | **3.78** | |

Seven files exceed the 100 MB block: two DNG originals (1455, 1458), SDR renders of
2402 and 1415, and HDR renders of 1521, 1531 and 1540. A per-directory limit is not an
issue: the largest class folder in one bucket holds 374 images, under 800 files once each has PNG and JXL twins.

**Lossless JXL twins.** The 2026-08-23 benchmark (`lossless_recompress_2026-08-23.md`)
measured lossless JXL at 0.606× the stored PNG bytes over 7,119 variant-set files,
16-bit PQ included, with libjxl's `cjxl`. That predates the imazen-only rule, so
twins should come from jxl-encoder's `cjxl-rs`. Its measurement over the full-size
png-v3 renders is in progress. See "JXL twin sizes" below.

## Three ways to ship split branches

| layout | fits GitHub? | notes |
|---|---|---|
| **A. Raw bytes, `train`/`validate`/`test` branches in this repo** | **No.** SDR PNG alone is 10.54 GiB; with originals and HDR, 19.8 GiB, all charged to one repo. Seven files are blocked outright. | Every later render pass adds to the same budget, permanently. |
| **B. Raw bytes, one repository per bucket** | test fits (0.99 + 2.04 + 0.89 = 3.9 GiB); validate ~5.9 GiB, already past the "strongly recommended" 5 GB; **train 9.96 GiB is at the hard limit** before any JXL twin or re-render. | Works only for a lean layer (one format, capped size). The seven >100 MB files still need splitting or a different format. |
| **C. LFS pointers on R2, `train`/`validate`/`test` branches in this repo** (the mechanism `variant/png-v3` and `variant/pristine-8th` already use) | **Yes.** Git holds ~130-byte pointers; bytes live at `codec-corpus/lfs/imazen-26/<sha256>` behind `imazen-lfs.pages.dev`. No GitHub storage, bandwidth, 10 GB or 100 MB limit applies. | Consumers need `git-lfs`. Re-renders cost R2 bytes, not repo size. Cloning a bucket is one command. |

**Proposal: C for the corpus, plus one small raw-git repository for decoder
conformance** (below), which is the one place where "clone with plain git, nothing
else installed" pays for itself.

## Proposed branches in `imazen/imazen-26`

```
main                  manifests, registry, splits, scripts — no image bytes (unchanged)
train                 LFS: every train id as lossless .png + .jxl twins (SDR), plus
validate                   .hdr.png + .hdr.jxl for ids with a gain map; MANIFEST.tsv
test                       with pixel hashes and colour signalling per file
variant/<set-id>      LFS: registered derived sets (existing pattern; large sets may
                           split per bucket as variant/<set-id>-<bucket>)
```

```sh
git clone --branch test --single-branch --depth 1 https://github.com/imazen/imazen-26.git
```

- **Bucket names:** `train`, `validate`, `test`, matching `manifests/split_map.tsv`
  and every consumer's code. `eval` would be a second name for `validate`.
- **Bucket rule:** the family-aware map, extended with the keys
  `split_leak_audit_2026-09-22.md` recommends (sha256, url+page, photo bursts), so a
  clone of `test` holds no twin of a train image. Doing this before the branches exist
  is cheap. Doing it after means moving files between branches that people have
  already cloned.
- **Content:** a new render pass ("v4", below), not png-v3: png-v3 labels ~165
  Display-P3 photos BT.709 (`color_orientation_audit_2026-09-22.md`), and registered
  sets are immutable.
- **Originals** stay on R2 (`imazen-26-unprocessed/`, ACCESS.md §1). Most consumers
  want decoded pixels, and originals as LFS branches would double the storage for a
  layer few people clone.

## Lossless twins and decoder consistency

Each image ships as a PNG and a JXL holding the same pixels, and the manifest carries
the answer every decoder must produce:

| column | meaning |
|---|---|
| `pixel_sha256` | sha256 of the decoded buffer in one canonical layout: row-major, interleaved, 8-bit or 16-bit big-endian, orientation applied |
| `width`, `height`, `channels`, `bit_depth` | as decoded |
| `cicp` or `icc_sha256` | the colour description both twins must carry |
| `png_sha256`, `jxl_sha256` | container bytes (these change if an encoder changes; `pixel_sha256` must not) |

A decoder passes when both twins reproduce `pixel_sha256` and report the same colour
description. zenpng and zenjxl-decoder are the first two decoders to gate. image-rs,
libjxl and browsers can be checked against the same hashes by anyone.

Two lessons from today's probe go into the build:

- `cjxl-rs` carries a PNG's `cICP` chunk into the JXL colour encoding, but it embeds
  an ICC profile only when given `--icc`. The builder must supply colour explicitly,
  and the gate must compare colour, not just pixels.
- Lossless WebP (VP8L) is 8-bit only and cannot hold the 16-bit HDR twins. Leave it
  out rather than carry a format that covers half the corpus.

**Separate repository: `imazen-26-conformance`** (raw git, target well under 1 GB): a
curated ~150–200 image decoder set, PNG + JXL twins with the same manifest columns.
It spans 1/8/16-bit; gray, RGB, RGBA and palette; sRGB, Display-P3, PQ (BT.709 and P3)
and ICC; the eight EXIF orientations; odd and tiny dimensions; and the format probes
from `subset_adoption_review_2026-09-22.md` (orientation set, gain-map test vectors,
HEIF features). CI in any repo, ours or not, can clone it with plain git.

## Render v4: one route, explicit colour, recorded HDR

Everything below comes from the originals through the imazen route (zencodecs
decode → zenpixels-convert where a conversion is declared → zenresize in linear
light → zenpng / jxl-encoder), with write-back verification like `pristine_downscale`:

- **Orientation:** applied, in every layer. Rotations by 90°/180°/270° map 8×8 blocks
  onto 8×8 blocks, so pristine-style references keep their property.
  (png-v3 applied it; pristine-8th did not.)
- **Colour, SDR:** native gamut, signalled explicitly: `cICP` where H.273 can say it
  (BT.709/sRGB, Display-P3, BT.2020), `iCCP` otherwise (Adobe RGB 3005/3006, ProPhoto,
  camera profiles). An untagged source is written as sRGB with `transfer_assumed=1` in
  the manifest. Never untagged, never relabelled.
- **Optional sRGB layer:** for consumers that need one guaranteed display space
  (squintly's registered sRGB condition), a separate `variant/srgb-v4`, converted by
  zenpixels-convert with the rendering intent recorded. Never mixed into the native
  layer.
- **HDR:** 16-bit, full-range PQ in the source's primaries (BT.709 or Display-P3,
  BT.2020 if a source is), signalled by `cICP` — the form zenmetrics' HDR ingress
  (`HDR_COMMON_PRIMARIES_2026-09-15.md`) admits; it refuses ICC for HDR. Record per
  image what today's renders do not: the gain-map headroom applied, the SDR reference
  white in nits (BT.2408's 203 unless decided otherwise), and tool plus version.
  Today's `cLLI` values run from MaxCLL 386 to 1,646 nits, consistent with per-image
  full headroom, but nothing says so. The camera's SDR base image is the pair's SDR
  twin; label it as the base rendition, not a tone-map of the HDR.
- **Coverage gaps to close in the same pass:** the three DNGs (1444, 1455, 1458) via
  zenraw or an explicit exclusion; 1449 needs zenpng's 120 MP default raised for that
  one decode; the 25 EPA pages carry an unused alpha channel that the write verifier
  trips on.

## Crop, scale and subset variants

VARIANTS-SPEC v2 already fixes the grammar (`<id-stem>.scale<W>x<H>[.crop…]`), the
size grid, the 11-unit crop vocabulary and the selection procedures. What is missing:

- **A crop renderer** (the spec notes this). Extending `pristine_downscale` with a crop
  argument gives crops the same colour, orientation and verification guarantees as
  scales.
- **A source layer to render from:** v4, so derived sets inherit correct colour instead
  of png-v3's labels.
- **Checkoutable bytes:** registered sets still live mostly on R2 and `/mnt/v`. Each gets
  a `variant/<set-id>` LFS branch, as `pristine-8th` has.
- **Buckets:** every derived file inherits its origin's family bucket. Subsets
  (krep-500, FPS, squintly-candidates, rd-gap train26, the lossless bench set) stay
  selection manifests on `main` and materialize by id from the bucket branches.

## JXL twin sizes

*In progress: `cjxl-rs --lossless -e 7 --threads 2` over all 2,233 png-v3 renders,
seeded random order, niced. Per-file results:
`/mnt/v/output/imazen-26-variants/jxl-lossless-probe-2026-09-22/`.*

## Decisions for the owner

1. **Layout:** LFS-on-R2 bucket branches in this repo (C, proposed), or raw-git
   repositories per bucket (B, lean layer only)?
2. **Names:** `validate` (matches the manifests) or `eval`?
3. **Bucket rule:** the current family map, or the extended map from the leak audit
   (proposed) before any branch is cut?
4. **Render v4 scope:** SDR + HDR twins from originals; DNGs via zenraw or excluded?
5. **sRGB layer:** ship one for display-constrained consumers, or native only?
6. **Conformance repo:** create `imazen-26-conformance` as raw git?
