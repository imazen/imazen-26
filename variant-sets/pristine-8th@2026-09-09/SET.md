# pristine-8th@2026-09-09 — artifact-free SDR references

Every lossy-sourced image in the corpus, downscaled 1/8 to PNG so that the codec
artifacts it carries are gone and it can serve as a **clean reference**.

- **Files:** 507 renditions, 0.105 GP. 143 MB.
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
- **Split:** inherited per origin id — 255 train / 157 validate / 95 test
  (50/31/19, against the canonical 50/30/20).
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
