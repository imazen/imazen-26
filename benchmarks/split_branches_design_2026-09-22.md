# Split branches, lossless twins, and variant layers — design proposal (2026-09-22)

**Status: proposal, awaiting decisions (last section).** The repository layout is revised in `layer_repos_2026-09-25.md` (originals plus sRGB and P3 PNG/JXL layers). The question: can the
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
twins should come from jxl-encoder's `cjxl-rs`. Measured below on all 2,233 full-size
renders: 0.533× for SDR and 0.646× for 16-bit HDR.

## Three ways to ship split branches

| layout | fits GitHub? | notes |
|---|---|---|
| **A. Raw bytes, `train`/`validate`/`test` branches in this repo** | **No.** SDR PNG alone is 10.54 GiB; with originals and HDR, 19.8 GiB, all charged to one repo. Seven files are blocked outright. | Every later render pass adds to the same budget, permanently. |
| **B. Raw bytes, one repository per bucket** | With PNG renders: test fits (0.99 + 2.04 + 0.89 = 3.9 GiB); validate ~5.9 GiB, already past the "strongly recommended" 5 GB; **train 9.96 GiB is at the hard limit**. JXL-only fits every bucket (train 4.03 GiB), but PNG + JXL twins put train at 11.2 GiB. | Works only for one lean format, which gives up the twin check. No JXL render exceeds 100 MB. |
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
- **Content:** a new render pass ("v4", below), not png-v3: png-v3 tags 210
  wide-gamut renders as sRGB (`signal_index_2026-09-24.md`), and registered sets are
  immutable.
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

**JPEG sources get a transcode, not a render, as the JXL member**
(`jpeg_in_jxl_validation_2026-09-22.md`). For the 417 JPEG sources, a lossless
JPEG→JXL transcode is 0.82× the JPEG against 2.40× for a lossless JXL render, and it
rebuilds the original byte-for-byte. Its decoded pixels are decoder-dependent (median
max difference 6 levels against zenjpeg), so it can't carry `pixel_sha256`. Its gate is
instead "rebuilt JPEG sha256 = original sha256", plus header orientation and colour
matching the source; the PNG render remains the pixel reference. This shrinks the JXL
layer from 8.06 to 6.18 GiB. It is blocked on encoder/decoder fixes listed in that note:
orientation, trailing restart markers, progressive rebuilds, and `jhgm` for gain maps.

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

## JXL twin sizes (measured 2026-09-22)

Every one of the 2,233 png-v3 renders (2,157 SDR, 76 HDR) was encoded with
jxl-encoder `cjxl-rs --lossless -e 7 --threads 2` (binary built 2026-09-17), 4 jobs
at a time under `run-heavy`, niced. 0 failures. Per-file data:
`/mnt/v/output/imazen-26-variants/jxl-lossless-probe-2026-09-22/sizes.tsv`
(sha256 `bff33dcfa4ce367a0b592f9af7f284c5f70ad66db48e042780e011b0f8e59fb9`; columns
`id, bucket_canonical_family, layer, png_bytes, jxl_bytes, encode_s, rc`).

| layer | PNG | lossless JXL | ratio (total / median per file) | encode median (2 threads) |
|---|--:|--:|--:|--:|
| SDR, 8-bit (and 1-bit) | 10.54 GiB | 5.62 GiB | 0.533 / 0.550 | 1.2 s |
| HDR, 16-bit PQ | 3.78 GiB | 2.44 GiB | 0.646 / 0.653 | 26.1 s |

The largest JXL is 69 MB (1521, HDR), so **no JXL twin hits GitHub's 100 MB block**. Five
of the seven >100 MB files are renders, and all five fit as JXL. The other two are DNG
originals, which the branches don't carry.

What each bucket would weigh (GiB):

| bucket | JXL only | originals + JXL | PNG + JXL twins | originals + twins |
|---|--:|--:|--:|--:|
| train | 4.03 | 6.82 | 11.20 | 13.99 |
| validate | 2.41 | 4.11 | 6.63 | 8.33 |
| test | 1.63 | 2.62 | 4.55 | 5.54 |
| all | 8.06 | 13.53 | 22.38 | 27.85 |

So:

- **Raw git, one repo for all buckets:** JXL-only (8.06 GiB) fits under 10 GB but not
  under the 5 GB "strongly recommended" line, and it leaves no room for a second
  render pass. Twins (22.4 GiB) do not fit.
- **Raw git, one repo per bucket:** JXL-only fits every bucket (train 4.03 GiB), but
  that drops the PNG twin, which is the decoder-consistency check. Twins put train
  at 11.2 GiB (over the limit) and validate at 6.63 GiB (over the recommended 5 GB).
- **LFS on R2 (proposed):** carries twins for every bucket, and later passes, with none
  of these limits.

Not measured here: **losslessness.** No imazen JXL decoder CLI was built in this
session, so these bytes were not decoded back and compared. The `pixel_sha256` gate
in the proposal is what closes that. The sizes also inherit png-v3's pixels,
including the colour mislabels in `color_orientation_audit_2026-09-22.md`. A v4 pass
changes the bytes but not the order of magnitude.

## Decisions for the owner

1. **Layout:** LFS-on-R2 bucket branches in this repo (C, proposed), or raw-git
   repositories per bucket (B, lean layer only)?
2. **Names:** `validate` (matches the manifests) or `eval`?
3. **Bucket rule:** the current family map, or the extended map from the leak audit
   (proposed) before any branch is cut? Measured: the extension moves 57 ids (2.6%) and
   leaves bucket sizes at 1,083 / 663 / 414 (from 1,084 / 661 / 415).
4. **Render v4 scope:** SDR + HDR twins from originals; DNGs via zenraw or excluded?
5. **sRGB layer:** ship one for display-constrained consumers, or native only?
6. **Conformance repo:** create `imazen-26-conformance` as raw git?
7. **JPEG sources:** use the JPEG-in-JXL transcode as their JXL member (once the
   blockers in `jpeg_in_jxl_validation_2026-09-22.md` are fixed)?
8. **HDR JPEGs:** restore the gain maps the metadata rewrite removed from the 33 UltraHDR
   originals (33 canonical sha256s change; location metadata stays out)? Without it, render v4 has no
   HDR for those ids.
