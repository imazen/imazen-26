# dHash census of all 2,149 images (2026-10-15)

The 2026-08-27 dHash audit covered only the 414 picker-selected ids. Every other id's split
families came from names and manifests alone. This census hashes every image in the
current corpus and checks what the successor family map (`manifests/split_map_family_v2.tsv`)
still leaves in different buckets.

## Method

- `tools/corpus-thumbs --dhash` produces two difference hashes per image: 64-bit (9×8)
  and 256-bit (17×16). Each is taken over Rec. 709 luma of the oriented, sRGB-converted
  image (zencodecs decode, zenpixels-convert, zenresize Lanczos; main of every crate).
- It covered all 2,149 ids, including 1214's camera original and the DNGs' embedded
  previews: 84 s, 8 workers, 1.31 GiB peak RSS.
- Every pair of ids was compared.

## dHash-64 is too coarse here

At d64 ≤ 10 there are 3,339 pairs, and 1,964 of them sit in different v2 families and
different buckets. Almost all are different pages of one text-heavy document, or different
products centred on white. Pages 10 and 12 of us5046022 hash to d64 = 0.

## Calibration of dHash-256

Distances between pairs whose relation is known (min, median, max):

| pairs | n | d256 |
|---|--:|---|
| a patent page's 1-bit original vs its rescans | 109 | 4, 50, 107 |
| different pages of one patent | 3,948 | 30, 97, 143 |
| photo bursts (v2 family) | 64 | 13, 125, 140 |
| web captures of one URL + page at other viewports | 827 | 0, 116, 163 |
| plot-run variants | 37 | 1, 9, 57 |

dHash finds re-encodes and same-framing copies. It cannot see the relations the provenance
keys exist for: rescans of a page, bursts, and other viewports. It verifies those keys; it
can't replace them.

## Cross-bucket candidates

`dhash_census_2026-10-15.tsv` lists the 45 pairs in different v2 families and different
buckets with d256 ≤ 32 (3 at ≤ 16, 13 at ≤ 24). Each pair was checked by eye, side by side:

- **None is a duplicate.** They are different products photographed alike (bottles, jars,
  apparel on white), different NOAA storm tables, the lkml "Not Found" captures (already
  flagged for removal), and a blank rescan page next to an Access Denied capture.
- **One structural family:** 7115–7119 are the same pie chart (one dataset) in five colour
  themes. They were spread over all three buckets. The v2 map now keys real-charts theme
  variants as one family (`chart`); they all take 7115's bucket, validate.

With the chart key, v2 holds 2,149 ids: 1,081 train, 660 validate, 408 test, in 186
multi-member families.
