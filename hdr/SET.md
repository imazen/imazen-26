# pristine-8th-hdr@2026-09-09

- **Files:** 76 renditions, 0.017 GP, 80 MB.
- **Selection:** list (hdr_ok.txt); split=any; crops=none.
- **Render:** kernel=mitchell, generator=make_variant_set.py@187fbf3.
- **Storage:** /mnt/v/output/imazen-26-variants/pristine-8th-hdr-2026-09-09 (register mirrors here when synced).
- **Consumers:** (fill in as projects adopt this set)
- **Status:** active.

## What this set is

The HDR leg of `pristine-8th@2026-09-09`. Source is the 16-bit PQ layer
(`/mnt/v/output/imazen-26-hdr-2026-06-14`, the `.hdr.png` files) rather than the
corpus originals — those 76 files are **all** derived from lossy origins (43
heic + 33 jpg), so every one of them carries codec artifacts and needs the same
1/8 treatment. `--select list`, ratio 1/8, mitchell, `linear-light-pq`.

Output is 16-bit RGB PNG with cICP preserved verbatim (all 33 carry `1/16/0/1` —
BT.709 primaries, PQ transfer, full range). Verified by reading IHDR and the
cICP chunk back off every file.

## All 76 render — the Display-P3 half needed a zenpng fix first

The HDR layer splits **43 Display-P3 / 33 BT.709**, both PQ, and on the first
attempt only the 33 could be written. zenpng advertised no wide-gamut or HDR
encode descriptors, so `adapt_for_encode_cow` targeted BT.709 and converting a
PQ source across primaries failed for want of a peak luminance
(`HdrSourceRequiresPeak`).

Worse, the 33 that *did* succeed were only correct by accident: their primaries
matched an advertised entry, so the *permissive* negotiator passed PQ samples
through unconverted and would have written them with **no colour chunk** — PQ
pixels in a file reading back as sRGB — had the caller not passed `cICP` by
hand. That is exactly why this layer has been produced outside zencodecs until
now (`extract_hdr_size_grid.rs` writes through the `image` crate and splices the
cICP chunk in by hand).

Fixed in zenpng `cfccd88f` by advertising the forms PNG can already carry and
deriving `cICP` from a non-sRGB descriptor. All 76 now render with colour
preserved: 33 × `1/16/0/1` (BT.709 PQ) and 43 × `12/16/0/1` (Display-P3 PQ),
all 16-bit, every file verified by decoding it back and comparing
sample-for-sample.

## The linear-light path is hand-rolled here, and has to be

zenresize's **u8** path dispatches on the descriptor's transfer, so 8-bit sRGB
resamples in correct linear light for free. Its **u16** path does not:
`resize_u16` linearizes with a hardcoded sRGB curve (its own doc comment says
so), which is wrong for PQ/HLG and would corrupt highlights — the trap the
2026-06 HDR renderer documented, still open in zenresize 0.3.1. So
`pristine_downscale` linearizes 16-bit sources with their own curve
(`zenresize::Pq`/`Hlg` via `TransferCurve`), resizes as linear f32, and
re-encodes. One honest path for SDR and HDR instead of silently
mis-resampling the HDR half.
