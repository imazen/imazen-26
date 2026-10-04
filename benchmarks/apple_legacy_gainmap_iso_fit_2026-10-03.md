# Apple legacy gain maps restated as ISO 21496-1 (2026-10-03)

**Question:** can the 24 HEICs with an Apple legacy gain map (iPhone 13 and 15 Pro: an
auxiliary gain-map image plus headroom in the EXIF MakerNote) gain an ISO 21496-1 `tmap`
that reuses the same gain-map pixels, so a normalized copy says the same thing in the
standard form without new pixels?

**Answer:** only approximately. The best ISO parameters miss Apple's rendition by up to
0.023–0.029 stops on the 8 files with 1.6–1.8 stops of headroom, 0.056–0.061 on the 3 at
2.5–2.7, and 0.076 on the 13 at 3.0 stops (about 5% in linear light, at mid-range gain
values). Re-encoding the gain-map pixels in ISO form instead stays within 0.006 stops
(half an 8-bit step), but that needs new pixels, and we have no HEIC encoder.

## The two curves

Apple (as heic's `HdrGainMap` documents it): `scale = 1 + (H − 1) · sRGB_EOTF(g)`, with
`g` the stored gain value and `H` the headroom. ISO 21496-1: `log2(scale) = a + b ·
g^(1/γ)`, where `a` is log2 of the minimum gain and `a + b` log2 of the maximum. One is
linear in a decoded gain value, the other exponential in a power of it, so no `(a, b, γ)`
makes them equal across all 256 gain values.

## Fit per headroom

`scripts/apple_legacy_iso_fit.py`, minimax over the 256 gain codes. "Pinned" keeps the
endpoints exact (min gain 1, max gain H); "free" also fits `a` and `b`.

| headroom (stops) | files | max error, pinned | max error, free | γ (free) | max error, gain map re-encoded |
|--:|--:|--:|--:|--:|--:|
| 1.600 | 1 | 0.034 | 0.023 | 0.632 | 0.003 |
| 1.626 | 1 | 0.036 | 0.024 | 0.634 | 0.003 |
| 1.677 | 1 | 0.038 | 0.025 | 0.642 | 0.003 |
| 1.739 | 1 | 0.041 | 0.027 | 0.650 | 0.003 |
| 1.776 | 1 | 0.042 | 0.028 | 0.654 | 0.004 |
| 1.800 | 3 | 0.043 | 0.029 | 0.658 | 0.004 |
| 2.529 | 1 | 0.084 | 0.056 | 0.758 | 0.005 |
| 2.659 | 1 | 0.092 | 0.061 | 0.778 | 0.005 |
| 2.663 | 1 | 0.092 | 0.061 | 0.778 | 0.005 |
| 3.000 | 13 | 0.114 | 0.076 | 0.828 | 0.006 |

Errors are in stops (log2 of the HDR/SDR scale), worst case over gain codes; per-image
error weighted by each gain map's histogram would be lower and wasn't measured. Headrooms
come from the whitelist-v2 signal probe (`_checks/sig_final.tsv`), where heic reports
these 24 files as `min 0, max H, gamma 1` parameters: a label for the legacy curve, which
heic applies with Apple's formula, not an ISO equivalent.

## What Apple does where it writes both

The 19 iPhone 16/17 Pro HEICs carry an Apple auxiliary gain map and a `tmap`. Their ISO
parameters are per image and three-channel, with a negative minimum (down to −0.70 stops)
and γ between 0.65 and 1.09: an ISO-native gain map, not a restatement of the legacy
curve. They give no conversion recipe for the older files.

## Consequence for the normalization tiers

A lossless tier can't give the 24 legacy files an exact ISO 21496-1 form. Either it
carries an approximate `tmap` (worst case 0.076 stops) or it leaves them legacy-only and
a re-encoding tier recomputes their gain maps in ISO form (within 0.006 stops) in a
container we can write.
