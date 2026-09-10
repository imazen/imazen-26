# variant/pristine-8th — artifact-free 1/8 references

A **distribution branch**, not a source branch: it carries rendered bytes through
Git LFS and nothing else. The corpus itself — manifests, canonical split,
`VARIANTS-SPEC.md`, the `variant-sets/` registry and the generation tooling —
lives on `main`.

| directory | files | what |
|---|---|---|
| `sdr/` | 505 | every lossy-sourced corpus image (jpg + heic) at 1/8, 8-bit PNG |
| `hdr/` | 76 | the 16-bit PQ layer at 1/8, cICP preserved |

Registry entries, with the full method and its caveats:
`variant-sets/pristine-8th@2026-09-09/` and
`variant-sets/pristine-8th-hdr@2026-09-09/` on `main`. Each directory here also
carries its own `SET.md` and the `variants.tsv` manifest that names every file,
its origin id, sha256, kernel, colorspace path and split bucket.

## Prefer the R2 copy

The same bytes are served over plain HTTPS with no git and no LFS client:

```
https://codec-corpus.r2.imazen.org/imazen-26-variants/pristine-8th-2026-09-09/<file>
https://codec-corpus.r2.imazen.org/imazen-26-variants/pristine-8th-hdr-2026-09-09/<file>
```

That is the path to point people at. This branch exists so a consumer can check
out the whole set in one operation, and so the bytes have a second home.

## What "pristine" means here, and what it does not

An 8×8 JPEG block averaged down to one pixel is that block's DC coefficient, so
the AC coefficients — the ringing and blocking — integrate away. Two limits are
real and recorded rather than papered over:

- **Chroma is only partly cleaned.** At 4:2:0 one chroma block spans 16×16 luma
  pixels, so 1/8 leaves 2×2 chroma pixels per block. Full chroma cancellation
  needs 1/16, which costs more resolution than the chroma artifacts are worth.
- **DC quantization error survives any kernel.** Measured over 1,080 paired
  cells, the kernel choice moves rejection by less than the ~0.3 ssim2 metric
  floor. Mitchell was chosen on a consistent-but-small margin, and the
  block-aligned box kernel that theory said should win actually lost — see the
  registry `SET.md` for the numbers and the mechanism.

Colour is preserved, not normalised: 191 of the SDR files and 43 of the HDR
files are Display-P3 and say so in `cICP`. Two Adobe RGB sources are absent and
named in `sdr/MISSING.tsv`; Adobe RGB has no CICP code point, so PNG cannot
describe it without an ICC profile and converting would have altered the pixels.

Every file was verified by decoding it back and comparing sample-for-sample
against the buffer that was encoded.
