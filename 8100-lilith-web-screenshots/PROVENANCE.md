# web-screenshots/ — viewport crops of `auto_screen/` captures

Generated 2026-06-07 by `scripts/07_crop_webshots.py` from the full-page
captures in `../auto_screen/`.

## What this is

The `auto_screen/` captures are **full-page** screenshots: width = the
device-pixel viewport width, height = the entire scrollable page (browser UI
excluded). Many overshoot the real content with trailing whitespace.

This folder holds the same pages cropped to **exact viewport tiles**:

```
web-screenshots/<WxH>/<name>_page1.png   top viewport ("above the fold")
web-screenshots/<WxH>/<name>_page2.png   second viewport (only when real
                                         content extends past the first)
```

- `<WxH>` mirrors the `auto_screen/` resolution folders. For sized folders the
  folder name is the authoritative device-pixel crop target; for `other/` the
  target is parsed from the filename's CSS `WxH` × `dpr` (so `…__375x667__dpr2`
  → 750×1334).
- **Every output is exactly the target WxH** — no padding, no resampling, pure
  top-left crops of the source pixels (lossless, suitable as codec corpus
  sources).
- **`_page2` is emitted only when real content reaches it.** A tile that would
  fall entirely in trailing whitespace is dropped (trailing-uniform rows are
  detected per capture). 724 crops were generated (438 `_page1` + 286 `_page2`),
  0 near-blank, 0 skipped.

> **PD-only as of 2026-06-07.** This folder was filtered to public-domain
> sources: 354 non-PD crops were moved to `../../imazen-26-not-pd/web-screenshots/`
> (and 227 non-PD source captures to `.../auto_screen/`). **370 PD crops remain
> here.** See `../../imazen-26-not-pd/WHAT-WAS-MOVED.md`. Original 724-row manifest
> is preserved at `MANIFEST.tsv.bak.before-pd-filter`.

`MANIFEST.tsv` columns: `filename · source_capture · page · crop_w · crop_h ·
url · license · source_kind`. `SKIPPED.tsv` lists any captures that could not
produce a full tile (currently empty).

## Copyright status

Every crop inherits the license of its source capture (carried through from
`../auto_screen/MANIFEST.tsv`, which has 100% license coverage). The folder holds
public-domain pages only: the 2026-06-07 PD filter kept 370 crops, and the removal reviews
since leave 348.

| License | Crops | Sources |
|---|---:|---|
| PD | 343 | US government sites (nps.gov, nasa.gov, loc.gov, archives.gov, climate.gov, usgs.gov, data.gov, nih.gov, weather.gov, noaa.gov, usaspending.gov, federalreserve.gov, whitehouse.gov, cdc.gov), gutenberg.org, si.edu, lkml.org, web.archive.org |
| PD-own | 5 | the maintainer's terminal captures |

The non-PD sources (CC-BY-SA, CC-BY, ODbL, PSF, GPL, Apache-MIT, open-source-readme,
mixed-CC, MIXED, Various-open — 354 crops) were moved to
`../../imazen-26-not-pd/web-screenshots/`; their per-row licenses live in that
folder's `MANIFEST.tsv` if you ever restore them (attribution / share-alike
obligations apply to those).

## Regenerating

```
python3 scripts/07_crop_webshots.py
```
Idempotent: re-reads `auto_screen/`, overwrites `web-screenshots/` crops and
both manifests.
