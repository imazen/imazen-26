# pristine-8th@2026-09-09 — artifact-free SDR references

Every lossy-sourced image in the corpus, downscaled 1/8 to PNG so that the codec
artifacts it carries are gone and it can serve as a **clean reference**.

- **Files:** 505 of 507 lossy origins, 0.105 GP, 141 MB. The 2 absent are
  named with the renderer's reason in `MISSING.tsv` (see below).
- **Selection:** `all`, filtered to lossy origins (`--sources lossy`) — the
  417 `jpg` + 90 `heic` rows of `CORPUS-MANIFEST.tsv`. The other 1,653 origins
  are already lossless and need no treatment.
- **Sizes:** ratio, not a grid rung. `selection_param = 1/8`. Sources are cropped
  to a whole multiple of 8 first (at most 7 px per axis), because a partial MCU
  cannot have its AC cancelled and the edge is where edge artifacts live. Names
  stay grammar-compliant: `<stem>.scale<W>x<H>.png`.
- **Render:** kernel `mitchell`, no sharpen, `colorspace_path = linear-light`.
  Generator `make_variant_set.py`; renderer `zenpipe` example
  `pristine_downscale` (`--ratio 8 --filter mitchell`), all-imazen:
  zencodecs decode → zenresize linear-light → zencodecs PNG encode with
  `ColorEmitPolicy::Verbatim`.
- **Split:** inherited per origin id, against the canonical 50/30/20.
- **Storage:** `/mnt/v/output/imazen-26-variants/pristine-8th-2026-09-09/`.
  Distribution: the `variant/pristine-8th` branch (Git LFS).
- **Consumers:** (fill in as projects adopt this set)
- **Status:** active.

## Why 1/8, and what it does not fix

An 8×8 JPEG luma block averaged to one pixel is that block's DC coefficient, so
the AC coefficients — the ringing and blocking — integrate away. Two limits are
real and recorded rather than hidden:

- **Chroma is only partly cleaned.** At 4:2:0 the chroma planes are half
  resolution, so one chroma block spans 16×16 luma pixels and 1/8 leaves 2×2
  chroma pixels per block. Full chroma cancellation needs 1/16, which costs more
  resolution than the chroma artifacts are worth.
- **DC quantization error survives any kernel.** That is what the kernel
  measurement below is actually about.

## Kernel choice was measured, and the obvious answer lost

`zenpipe` example `pristine_kernel_ab`, 1,080 cells (20 content-stratified clean
PNG sources × q10..95 step 5 × 3 kernels), paired per cell:

| comparison | median Δ rejection | winner rate |
|---|---|---|
| box − lanczos | −0.036 | box 39.2% |
| box − mitchell | −0.268 | box 9.2% |
| mitchell − lanczos | +0.228 | mitchell 88.6% |

where rejection = `ssim2(down_K(clean), down_K(jpeg))`.

The prediction was that **box** would win, since only a block-aligned box kernel
extracts the DC exactly. It lost. Once 1/8 has removed the AC content, what is
left is DC *quantization* error, and a wider, smoother kernel averages
independent per-block DC errors down — which box, seeing one block and never its
neighbours, cannot do. That predicts mitchell > lanczos > box, which is the
measured order.

Every delta is at or below the ~0.3 ssim2 floor, so **the kernel barely matters
here** and this is a tiebreak, not a win. Mitchell takes it on a consistent
direction (88.6% of cells), and it is both a VARIANTS-SPEC v2 permitted kernel
for metric-reference sets and the corpus's deployed SDR convention, so this set
joins existing renditions.

## Note on assumed transfer

Most corpus JPEGs are untagged. zenresize refuses to resample through an unknown
transfer rather than guessing, so the renderer resolves untagged sources to sRGB
explicitly (web convention) and records `transfer_assumed` per row in its own
output TSV. Sources that declare a transfer (all HEIC, all HDR) are never
assumed.


## Colour is preserved, and fixing that changed 191 files

**191 of the 505 are Display-P3** (`cICP 12/13/0/1`); the other 314 are untagged
sRGB, which is the conventional and smallest encoding for sRGB/BT.709.

Every one of those 191 would previously have been **silently gamut-converted to
BT.709**. zenpng advertised only sRGB/BT.709 and linear descriptors, so the
encode negotiator either converted a wide-gamut buffer or — worse, when the
primaries happened to match — passed it through unconverted and wrote it with no
colour chunk at all. Fixed in zenpng `cfccd88f`: the forms PNG can already carry
are advertised, and a non-sRGB descriptor now supplies its own `cICP`.

The renderer also reconciles the decoded descriptor against the container's own
cICP before resampling, because a decoder can hand back Display-P3 pixels under
a BT.709 descriptor — and it verifies every file it writes by decoding it back
and comparing sample-for-sample. A reference set that quietly ships converted
pixels or a wrong colour tag is worse than one that fails.

## The 2 in MISSING.tsv

Both are Art Institute scans in **Adobe RGB with a gamma-2.2 transfer**. Adobe
RGB has **no CICP code point at all** — it is expressible only through an ICC
profile — so PNG cannot describe these via `cICP`, and the encoder converts them
to the nearest advertised gamut. That is a genuine pixel change, so the write
verifier refuses them rather than shipping altered pixels as a reference.

Unlike the Display-P3 case this is not a missing descriptor; carrying it needs
ICC passthrough, a different mechanism. Recorded rather than worked around.

Two sources also carry a `Gamma22` transfer that `zenpixels` does not map to a
CICP code (ITU-T H.273 code 4 exists for it; `TransferFunction::to_cicp` returns
`None`). Those files ship with `color_untagged` recorded in the renderer's TSV.
