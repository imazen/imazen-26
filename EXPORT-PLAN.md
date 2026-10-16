# imazen-26 export plan

**Status: decided 2026-10-15. Steps 1 (originals) and 2 (R2) are done: the owner's go came
2026-10-16, and the public prefix now holds exactly the manifests' originals and documents.** This settles the open questions in
`benchmarks/layer_repos_2026-09-25.md` and `benchmarks/split_branches_design_2026-09-22.md`.
Membership becomes final after the removal review: the 11 byte-identical duplicates are
retired, and the review may retire more.

## Order of work

1. **Originals.**
   - Swap in the whitelist-v2 versions of the 316 camera files: same privacy policy, but
     colour and HDR structure kept.
   - Replace 1214 with its camera original.
   - Re-encode 1044 as a quality-100 JPEG, dropping its motion-photo clip.
   - Replace 9869 and 9874 with background-cleaned versions (9231, the third, is retired). They
     were regenerated after the white-background flatten pass, so they are the only
     white-background product images still uncleaned. zenfilters' `ai_corpus_flatten` at main
     reproduces the original pass byte for byte (checked on 9226).
   - Apply the camera metadata policy to the 32 phone screenshots (their SEFT trailers go with
     it) and, in place, to the JPEG previews inside the 3 DNGs.
   - Strip the IPTC zTXt and XMP chunks (3 AI PNGs) and the C2PA stores (106 PNG `caBX`, 5 JPEG
     APP11), with our own code.
   - Keep the museum metadata.
   - Crush every PNG before final storage, in the originals and in every PNG layer, with zenpng
     at main, effort 22 (owner choice; `benchmarks/png_crush_effort_2026-10-15.md`: Crush adds
     0.3–1.2 points for 7–18× the time). Re-encoding is lossless (pixel hash checked) and
     replaces the PNGs written by third-party code (the product images' white-background pass
     used the `image` crate). Colour (ICC, gamma, sRGB, chromaticities) and EXIF are carried
     over, and so is `pHYs` (the scan resolution of 175 scans and documents).
     `sBIT` is dropped: every one in the corpus is 8,8,8, which an 8-bit PNG already says.
     `tools/png-crush` does this and refuses any file whose pixels change.
   - Keep the originals camera-faithful: record reader quirks in manifest columns instead of
     editing files. The quirks are tile-only HEIC colour, HEIC `irot` plus EXIF orientation,
     and the depth/`tmap` reference libheif 1.17 rejects.
2. **R2.**
   - A private bucket keeps every revision of the originals as dated, read-only checkpoints.
   - Then the public prefix mirrors the manifest exactly: unlisted objects are deleted, and the
     three AI files under stale names are re-keyed.
   - Done 2026-10-16 with `scripts/r2_originals_sync.py`. No originals bucket existed before,
     so the private bucket `imazen-26-originals` was created for it. It holds
     `2026-10-16-before/` (the public prefix as it stood: 2,688 objects, 6.96 GB) and
     `2026-10-16-after/` (2,174 objects, 5.23 GB). Each copy was checked against its source by
     size and MD5, and a bucket-lock rule per prefix refuses deletes and overwrites. The sync put
     1,945 objects and deleted 518; `verify` then read every public object back by sha256 (0
     missing, 0 extra, 0 mismatched).
3. **Membership and splits.**
   - Retired ids are listed in `manifests/retired.tsv` and never reused; the gaps stay.
   - At export every id gets a leading `1` (1044 becomes 11044). The last digit doesn't
     change, so neither does any bucket, and the old-to-new mapping is the prefix itself.
     Class folders take the same prefix (`1000-lilith-photos-general` becomes
     `11000-lilith-photos-general`). The derived layers drop the sub-folders inside a class:
     every file name starts with its unique id.
   - The successor family map (`manifests/split_map_family_v2.tsv`) adds sha256, URL-plus-page
     and photo-burst keys. It also keys patent scans by `patent_page`, so a page's 1-bit original
     and both rescans always share a bucket; us3807657's rescans are its pages 1, 3, 5 and 7.
     It is computed once more, on the final membership, before any branch exists. Every export
  bucket, and the bucket in each file's provenance, comes from this map.
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

- **XL membership** (v4 sizes, `scripts/export_sizing.py`, 2026-10-16): 5 ids.
  - 11455 and 11458: their DNG originals (118.8 and 126.8 MiB).
  - 11521 and 11540: their HDR PNGs (107.9 and 100.4 MiB).
  - 12402: its SDR PNG, 101.2 MiB in both PNG layers.
  - 11531's HDR PNG is 99.5 MiB, under the limit. No JPEG XL file exceeds 71 MiB.
  - An XL image leaves the other repositories completely.
- **Repository size.** GitHub caps a repository at 10 GB on disk and a push at 2 GiB
  ([repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits),
  checked 2026-10-16). Without the XL images, v4
  measures: originals 4.86 GB, `png-p3` 12.59 GB (6.13 / 3.81 / 2.66 by bucket), `png-srgb`
  9.44 GB, `jxl-p3` 6.16 GB, `jxl-srgb` 4.77 GB. The PNG layers get a repository per bucket;
  the others one repository with a branch per bucket. A large branch goes up in several
  pushes.
- **R2 copies.** Every layer also sits under named prefixes in an `imazen-26` R2 bucket.
- **Older layers.** png-v3 and pristine-8th keep their bytes and leave the docs.
- **Release.** One version tag goes on every repository at once, with release notes, a
  dataset card and `CITATION.cff`.

## Render v4

- **Tooling.** Only zen tools write files, built against the main branch of every imazen
  crate and never crates.io releases (`tools/corpus-thumbs/README.md` shows how). Each
  manifest row records the tool commits. `scripts/render_v4_list.py` lists every image with
  its export name and provenance; `tools/render-v4` renders the list (its `Cargo.lock` pins
  the crate commits, `tools/corpus-thumbs/zen-main/COMMITS.tsv` the three taken by path).
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
- **HDR (76 images, `p3` layers only).** Each p3 layer holds the camera's SDR base (in P3)
  and, beside it, the HDR render as `<name>.hdr.<ext>`; the `srgb` layers hold the SDR base
  converted like any other source. render-v4 finds the gain map with each codec's own probe.
  - Every format gets a 16-bit PQ render: each image's full gain-map headroom, diffuse white
    at 203 nits (BT.2408), measured `cLLI`, and the settings recorded in the manifest.
    - The gain map is oriented like the displayed base and sampled as ultrahdr-core's
      `apply_gainmap` samples it: corner-aligned, as libultrahdr, with Shepard's weights over
      the per-sample gains (libultrahdr blends the stored values first; 0.011 stops apart at
      the 99.9th percentile on 1064, imazen/ultrahdr#42).
    - ISO 21496-1 maps (33 UltraHDR JPEGs, 19 iPhone `tmap` HEICs) go through `apply_gainmap`;
      the 24 legacy Apple maps use Apple's curve, `1 + (H - 1) * sRGB_EOTF(g)`, under the same
      sampling (zen's own reconstruction approximates it by up to 0.3 stops, imazen/heic#62).
    - PQ is ST 2084 in f64, rounded to 16 bits; `cICP` 12/16/0/1; `cLLI` is measured on the
      written codes. The `.hdr.jxl` twin holds the same samples, with MaxCLL as its intensity
      target (JXL has no MaxFALL).
  - JXL (`jhgm`) and `.imi` also get the gain-map form: the camera's SDR base plus an
    ISO 21496-1 gain map, in the `p3` file itself. A JPEG-in-JXL transcode of an UltraHDR JPEG
    carries the JPEG's gain map as `jhgm` already; a HEIC's lossless `p3` file gets the box
    appended.
  - The 24 Apple legacy gain maps are re-encoded in ISO form (min 0, max = headroom, gamma 1,
    no offsets), within half a code step of Apple's curve: 0.006 stops measured.
  - `jhgm` support, checked 2026-10-15 on each project's main:
    - libjxl reads and writes the gain-map bundle since v0.11.0 (`jxl/gain_map.h`, "utility
      functions to manipulate jhgm boxes"; `jxlinfo` reports it). Applying it is left to
      the application.
    - jxl-rs recognises the box (`JxlAuxBoxType::HDR_GAIN_MAP`) and returns its raw bytes.
      It parses nothing inside it.
    - zenjxl-decoder parses the bundle (`container/gain_map.rs`). zenjxl decodes the gain-map
      codestream (`GainMapRender::Components`) and applies it with its `reconstruct-hdr`
      feature (`tests/gain_map_render.rs`). jxl-encoder writes the box.
- **Layout.** Channels and bit depth follow the source. A fully opaque alpha channel is
  dropped, and the manifest records it.
- **Metadata.** Colour and HDR signalling, plus one provenance text chunk: corpus id,
  bucket, licence, attribution and the original's sha256, as JSON. Nothing about where or with
  what a photo was taken. In PNG this is a `tEXt` chunk (keyword `imazen-26`) holding ASCII
  JSON, non-ASCII characters escaped, so it reads the same as Latin-1 or UTF-8; JXL and
  `.imi` carry the same text in their own metadata.
- **JPEG XL.**
  - JPEG sources ship as JPEG-in-JXL, which rebuilds the original byte for byte, and all
    other sources as lossless renders. A JPEG-in-JXL file keeps the JPEG's own metadata (its
    Exif and XMP, under the originals' keep-list) because the rebuild needs it, and its
    orientation lives in the codestream header.
  - Lossless files state sRGB and Display P3 in JXL's own colour encoding and Adobe RGB as its
    ICC profile, and carry the provenance JSON as XMP (one `imazen26:provenance` property).
    Owner question 5 settles whether JPEG-in-JXL files carry provenance too.
  - The 12 progressive Unsplash JPEGs (2003, 2005, 2009, 2012, 2013, 2022, 2203, 2204, 2207,
    2212, 2402, 2409) cannot carry JPEG reconstruction data: each has a scan with more than
    65,555 EOB-run reset points, beyond the `jbrd` field's range. libjxl refuses them too, and
    jxl-encoder now does (zenjxl-decoder#59). Open owner choice: JPEG-in-JXL without
    reconstruction data (the exact DCT coefficients, no byte-exact JPEG rebuild) or lossless
    renders.
  - In `jxl-srgb`, the 168 wide-gamut JPEGs need a colour conversion, so they are lossless
    renders there.
- **`.imi`.** Lossless pixel twins of the PNG and JXL files, published as single files plus
  archives as release assets. A private tool in the IMIJ repository writes them from the PNG
  layers: the PNG's samples, colour, `cLLI` and provenance (as the JXL files' XMP packet),
  and on each gain-map source's `p3` SDR file the ISO 21496-1 gain map that
  `render-v4 gain-maps` writes under `gain-maps/` (the map oriented like the base, and its
  metadata).
- **DNGs.** They stay in the originals and are left out of every derived layer.

## Gates

A file ships only if all of these pass:

- **Inventory.** The inventory names every part of the file. An unknown part blocks the
  release unless its kind is on a reviewed allow-list. The inventory also decompresses
  zTXt.
- **Byte scan.** No nested media and no location atom in any original or layer.
- **Third-party read-back.** libpng, Pillow and ImageMagick read every PNG; libjxl reads
  every JXL. No third-party `.imi` decoder exists: imij and imij-oracle, a second decoder
  written from the format specification alone, both decode every `.imi`.
  (`scripts/render_v4_readback.py`, `scripts/render_v4_jxl_check.py`.)
- **Colour and HDR oracles.** Every wide-gamut `png-srgb` file is within 1 code value of a
  textbook conversion of its own `png-p3` twin (`scripts/colour_oracle.py`, which also reports
  LittleCMS); every HDR render is rebuilt in numpy from libheif, Pillow and exiftool decodes
  (`scripts/hdr_oracle.py`).
- **Lossless twins.** The PNG, JXL and `.imi` copies of one image decode to one pixel hash
  and state one colour description.
- **JPEG-in-JXL.** The rebuilt JPEG's sha256 equals the original's.
