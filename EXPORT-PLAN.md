# imazen-26 export plan

**Status: decided 2026-10-15, not yet built.** This settles the open questions in
`benchmarks/layer_repos_2026-09-25.md` and `benchmarks/split_branches_design_2026-09-22.md`.
Membership becomes final after the removal review: the 11 byte-identical duplicates are
retired, and the review may retire more.

## Order of work

1. **Originals.**
   - Swap in the whitelist-v2 versions of the 316 camera files: same privacy policy, but
     colour and HDR structure kept.
   - Replace 1214 with its camera original.
   - Re-encode 1044 as a quality-100 JPEG, dropping its motion-photo clip.
   - Replace 9231, 9869 and 9874 with background-cleaned versions. They were regenerated after
     the white-background flatten pass, so they are the only white-background product images
     still uncleaned. zenfilters' `ai_corpus_flatten` at main reproduces the original pass byte
     for byte (checked on 9226).
   - Strip the SEFT trailers (32 screenshots), the IPTC zTXt chunks (3 AI PNGs) and the C2PA
     stores (115 AI images), with our own code.
   - Keep the museum metadata.
   - Crush every PNG before final storage, in the originals and in every PNG layer, with zenpng
     at main, effort 22 (owner choice; `benchmarks/png_crush_effort_2026-10-15.md`: Crush adds
     0.3–1.2 points for 7–18× the time). Re-encoding is lossless (pixel hash checked) and
     replaces the PNGs written by third-party code (the product images' white-background pass
     used the `image` crate). Colour (ICC, gamma, sRGB, chromaticities), EXIF and XMP are
     carried over, and so is `pHYs` (the scan resolution of 175 scans and documents).
     `sBIT` is dropped: every one in the corpus is 8,8,8, which an 8-bit PNG already says.
     `tools/png-crush` does this and refuses any file whose pixels change.
   - Keep the originals camera-faithful: record reader quirks in manifest columns instead of
     editing files. The quirks are tile-only HEIC colour, HEIC `irot` plus EXIF orientation,
     and the depth/`tmap` reference libheif 1.17 rejects.
2. **R2.**
   - A private bucket keeps every revision of the originals as dated, read-only checkpoints.
   - Then the public prefix mirrors the manifest exactly: unlisted objects are deleted, and the
     three AI files under stale names are re-keyed.
3. **Membership and splits.**
   - Retired ids are listed in `manifests/retired.tsv` and never reused; the gaps stay.
   - At export every id gets a leading `1` (1044 becomes 11044). The last digit doesn't
     change, so neither does any bucket, and the old-to-new mapping is the prefix itself.
   - The successor family map (`manifests/split_map_family_v2.tsv`) adds sha256, URL-plus-page
     and photo-burst keys. It also keys patent scans by `patent_page`, so a page's 1-bit original
     and both rescans always share a bucket; us3807657's rescans are its pages 1, 3, 5 and 7.
     It is computed once more, on the final membership, before any branch exists.
4. **Render v4** from the restored originals, with the rules below.
5. **Gates, then publish** (see the last two sections).

## Repositories

Plain git, one repository per set and subset, with `train`, `validate` and `test` branches.
Git LFS only where GitHub's limits leave no choice.

| repository | holds |
|---|---|
| `imazen-26-originals` | the source files, byte for byte |
| `imazen-26-png-srgb`, `imazen-26-png-p3` | lossless PNG renders |
| `imazen-26-jxl-srgb`, `imazen-26-jxl-p3` | JPEG XL (see below) |
| `imazen-26-imi-srgb`, `imazen-26-imi-p3` | IMIJ `.imi` renders; private until IMIJ ships with a frozen format version |
| `imazen-xl-26` | every image that has a file over GitHub's 100 MiB limit in any layer, with all of its layers, in GitHub LFS |

- **XL membership.**
  - On the png-v3 sizes and the originals, 7 ids qualify today: 1415, 1455, 1458, 1521,
    1531, 1540 and 2402.
  - 8 more HDR renders are within 10 MiB of the limit: 1520, 1527, 1528, 1532, 1536, 1537,
    1542 and 1543.
  - The v4 file sizes decide. An XL image leaves the other repositories completely.
- **Repository size.** GitHub caps a repository at 10 GB. The PNG layers measure 10.5 and
  14.3 GiB on png-v3, so they get a repository per bucket.
- **R2 copies.** Every layer also sits under named prefixes in an `imazen-26` R2 bucket.
- **Older layers.** png-v3 and pristine-8th keep their bytes and leave the docs.
- **Release.** One version tag goes on every repository at once, with release notes, a
  dataset card and `CITATION.cff`.

## Render v4

- **Tooling.** Only zen tools write files, built against the main branch of every imazen
  crate and never crates.io releases (`tools/corpus-thumbs/README.md` shows how). Each
  manifest row records the tool commits.
- **Orientation.** It is baked into the pixels and the tag is removed. File names carry the
  displayed size.
- **Colour.**
  - The `p3` layers keep each source's own colour space. sRGB stays sRGB and is never
    converted to P3 at 8 bits; Adobe RGB keeps its profile.
  - The `srgb` layers convert relative colorimetric, clipping out-of-gamut colours, and
    record the clipped-pixel count per file.
  - Untagged sources are written as sRGB and marked `assumed`.
- **PNG signalling.**
  - sRGB files carry the `sRGB` chunk.
  - Other spaces carry an `iCCP` plus an agreeing `cICP`, so Linux libraries and Windows,
    which ignore `cICP` on its own, still see the right colours.
  - HDR files carry `cICP` and `cLLI`.
- **HDR (76 images, `p3` layers only).**
  - Every format gets a 16-bit PQ render: each image's full gain-map headroom, diffuse white
    at 203 nits (BT.2408), measured `cLLI`, and the settings recorded in the manifest.
  - JXL (`jhgm`) and `.imi` also get the gain-map form: the camera's SDR base plus an
    ISO 21496-1 gain map.
  - The 24 Apple legacy gain maps are re-encoded in ISO form (within 0.006 stops).
  - Check `jhgm` support in libjxl, jxl-rs and zenjxl-decoder.
- **Layout.** Channels and bit depth follow the source. A fully opaque alpha channel is
  dropped, and the manifest records it.
- **Metadata.** Colour and HDR signalling, plus one provenance text chunk: corpus id,
  bucket, licence and attribution. In PNG this is an `iTXt` chunk; JXL and `.imi` carry the
  same text in their own metadata.
- **JPEG XL.**
  - JPEG sources ship as JPEG-in-JXL, which rebuilds the original byte for byte, and all
    other sources as lossless renders.
  - The 12 progressive Unsplash JPEGs wait for zenjxl-decoder#59.
  - In `jxl-srgb`, the 168 wide-gamut JPEGs need a colour conversion, so they are lossless
    renders there.
- **`.imi`.** Lossless pixel twins of the PNG and JXL files, published as single files plus
  archives as release assets.
- **DNGs.** They stay in the originals and are left out of every derived layer.

## Gates

A file ships only if all of these pass:

- **Inventory.** The inventory names every part of the file. An unknown part blocks the
  release unless its kind is on a reviewed allow-list. The inventory also decompresses
  zTXt.
- **Byte scan.** No nested media and no location atom in any original or layer.
- **Third-party read-back.** libpng, Pillow and ImageMagick read every PNG; libjxl reads
  every JXL. No third-party `.imi` decoder exists, so IMIJ's own decoder checks those.
- **Lossless twins.** The PNG, JXL and `.imi` copies of one image decode to one pixel hash
  and state one colour description.
- **JPEG-in-JXL.** The rebuilt JPEG's sha256 equals the original's.
