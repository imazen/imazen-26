# pristine-8th-hdr@2026-09-09

- **Files:** 33 renditions, 0.006 GP total.
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

## 43 of 76 are MISSING, and why — see MISSING.tsv

The HDR layer splits 43 Display-P3 / 33 BT.709, both PQ. **The Display-P3 half
cannot currently be written.** zenpng's accepted-format set does not include
Display-P3 primaries, so `adapt_for_encode_cow` negotiates towards BT.709, and
converting a PQ source across primaries requires a peak luminance that is not
available — `HdrSourceRequiresPeak`.

This fails loudly, which is the correct behaviour: the alternative is a
silently gamut-shifted file presented as a reference. It is a real gap in
zenpng (PNG's own cICP chunk can express Display-P3 — primaries code 12 — so
this is a supported-format-list omission, not a format limitation), and zenpng
is a separate repository, so it is reported here rather than patched.

Unblocking it makes this set 76 files with no other change. The 43 are exactly
the HEIC-origin images, which is where the phone-captured P3 content lives.

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
