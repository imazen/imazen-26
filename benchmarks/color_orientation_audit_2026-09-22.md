# Colour signalling and orientation across render layers (2026-09-22)

Read-only census of the published render layers. Chunk data comes from reading
each PNG's header chunks; pixel comparisons use zenpipe's `pristine_downscale`
(zencodecs decode → zenresize linear light) so both sides went through one route.

## 1. What png-v3 signals

All 2,233 png-v3 renders (`/mnt/v/output/imazen-26-png-v3`, the bytes behind
`variant/png-v3`):

| layer | files | colour signalling |
|---|--:|---|
| SDR | 1,570 | none (untagged; readers assume sRGB) |
| SDR | 459 | `cICP 1/13/0/1` (BT.709 primaries, sRGB transfer) |
| SDR | 48 | `cICP 12/13/0/1` (Display-P3) |
| SDR | 41 | `iCCP` |
| SDR | 39 | 1-bit (patent scans) |
| HDR | 43 | 16-bit, `cICP 12/16/0/1` (Display-P3, PQ) + `cLLI` |
| HDR | 33 | 16-bit, `cICP 1/16/0/1` (BT.709, PQ) + `cLLI` |

No render carries `mDCV`. The HDR `cLLI` values vary per image: MaxCLL 386–1,646
nits (median 641), MaxFALL 26–232 nits. So each gain map was applied at that
image's own headroom. The reconstruction settings (headroom, SDR white level,
tool) are not recorded in this repo.

## 2. ~165 Display-P3 photos are labelled BT.709 in png-v3

`pristine-8th@2026-09-09` reads each lossy origin's colour description and
preserves it (`cICP` verbatim). Joining its 505 renders to png-v3 by id:

| pristine-8th | png-v3 | n |
|---|---|--:|
| untagged sRGB | `1/13/0/1` | 292 (consistent) |
| Display-P3 `12/13/0/1` | Display-P3 `12/13/0/1` | 26 (consistent) |
| **Display-P3 `12/13/0/1`** | **`1/13/0/1` (BT.709)** | **165** |
| untagged | Display-P3 | 22 |

For the 165: the originals embed a Display-P3 profile. Checked on 1007 and 1008:
their JPEG `ICC_PROFILE` segment reads "DCI-P3 D65 Gamut with sRGB Transfer". Their
png-v3 pixel values are the unconverted P3 values. Downscaling the png-v3 render 1/8
through the same route and aligning orientation reproduces pristine-8th to within
0.01–0.02 levels mean absolute difference on 1007, 1013 and 1015, including the 37%
strongly saturated pixels of 1013, with identical mean chroma. A P3→sRGB conversion
would have raised saturated values. So png-v3 kept the P3 numbers and tagged them
BT.709.

Effect: a colour-managed viewer (browsers honour PNG `cICP`) shows these ~165 photos
less saturated than the camera captured them. Comparisons that read raw samples on
both sides (reference and encodes built from the same render) are internally
consistent. Anything that claims colour fidelity to the original, or wide-gamut
evaluation, is not.

The 22 in the other direction are iPhone HDR HEICs (e.g. 1495–1498). Their first
colour boxes belong to the gain map ("Linear Gray"). Which layer is right there is
**not verified**.

## 3. Orientation differs between layers

png-v3 applies EXIF orientation. It names renders by the rotated dimensions, the
cause of the 196-row `RENDER-NAME-MAP.tsv`. pristine-8th keeps the **stored**
orientation: 1007's reference is `…4000x3000.scale500x375.png` (landscape) while its
png-v3 render is 3000×4000 (portrait). Aligning them took a 270° rotation for
1007/1013 and 180° for 1015. A consumer mixing the two layers gets sideways or
upside-down pairs unless it rotates one of them.

## 4. What this means for new layers

- Every render carries explicit colour: `cICP` where H.273 can express it
  (BT.709/sRGB, Display-P3, BT.2020, PQ, HLG), `iCCP` otherwise (Adobe RGB,
  ProPhoto, camera profiles). Untagged means "unknown", so write sRGB explicitly and
  record `transfer_assumed=1` when that was an assumption.
- One orientation convention for all layers, stated in each `SET.md`: apply
  orientation. A 90°/180°/270° rotation maps 8×8 blocks onto 8×8 blocks, so
  pristine's DC-block argument survives it.
- HDR renders record the reconstruction: gain-map headroom used, SDR reference
  white in nits, tool and version. Keep native primaries in a PQ container, as
  zenmetrics' HDR ingress contract expects (`cICP` primaries 1/9/12, full range; ICC
  refused).
- png-v3 is immutable under the registry contract. Fixing the labels means a
  successor layer, not a rewrite.
