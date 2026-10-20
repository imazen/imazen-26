# Redo-5 reader census and public review — 2026-10-20

Executed after the [four dataset publications](minimal_publication_2026-10-19.pointer.md).
The twelve redo-5 IDs share their replacement JXL bytes across the two colour
layers: 12 missing hashes, 24 paths. The PNG hashes already had reader rows.

The resumable census used `--ids
12003,12005,12009,12012,12013,12022,12203,12204,12207,12212,12402,12409`,
`--jobs 2 --mem-budget 16 --chunk 4`, under the shared heavy-job lock.
Eight chunks added 252 rows from 21 readers. The old census table remains an
unchanged byte prefix. All 144 successful decodes match our pixels: 128 native
and 16 RGBA8. The remaining 108 rows are readers without JPEG XL support.
All 168 reader containers exited normally, with zero recorded OOM kills.

`python3 scripts/build_v4_review.py census <render> jxl` reports:

```text
52,500 rows, 2,500 files, 0 unexplained
```

The table preserves 252 rows for the twelve old hashes. Current JXL files have
52,248 rows over 2,488 distinct hashes. The complete alias map covers 8,600
PNG/JXL paths. The top-up preserves full aliases when `--ids` selects decoding
(`2c1ca973`). The public builder selects current manifest hashes (`8bb3ab3a`):
including historical rows would create 252 duplicate path/decoder identities.
The deployed hash download has zero duplicates; the browser check now enforces
this (`6ca33344`). Census verdict thresholds were unchanged.

## Deployment and browser check

Used `scripts/deploy_v4_review_site.sh <render> <stage> <site>` followed by:

```sh
uvx --with playwright python scripts/check_v4_review_site.py \
  https://imazen-26-review.pages.dev/ --chrome <chrome-binary>
```

Deployment [a78bd3b0](https://a78bd3b0.imazen-26-review.pages.dev/) is live at
[the production review](https://imazen-26-review.pages.dev/). The checker exited
zero: 2,112 tiles for 2,112 images; image 11000 opened at its full 4,032-pixel
width; details and read-only state worked; a missing path returned HTTP 404;
no page, console, failed-request or HTTP errors occurred.

The hash download is 40,591,101 bytes in four parts, with 197,876 unique
path/decoder identities and zero duplicates. SHA-256:
`221b742297fe1a1f877a7a5a3837f3bb06bdaaa206a7d9dba6a9701597ce5368`.
Anonymous downloads of the public index and all four hash parts match the
prepared site byte-for-byte. The current site's 174 files were mirrored and
three randomly selected files were SHA-256-verified against the local copy.

## Evidence

Checked from dev on 2026-10-20 UTC:
`/mnt/tower/output/imazen-26-review-topup-2026-10-20/`.
`before/` preserves census metadata, RUN.meta and the previous combined reader
hash table. `site-before/` and `site-after/` preserve both site versions. Coverage,
reader images, memory records, verdicts, full logs and public-byte proof remain
beside them. `evidence.json` SHA-256:
`c47fe4d23471d3f25e575564f54cf36c9b2396165744e54b006264f827372d84`.
The canonical census is under the render's `compat-census/`; no encoded image
was changed or re-encoded.

Resource records (controller RSS; Docker's separate per-container cgroup peaks
are in `memory.tsv`):

```text
census: run-heavy: done rc=0 1369s | peak-RSS 1.65GiB | min-avail 43705MiB | peak-load 10.90
deploy/check: run-heavy: done rc=0 76s | peak-RSS 0.57GiB | min-avail 48335MiB | peak-load 2.18
mirror/proof: run-heavy: done rc=0 11s | peak-RSS 0.06GiB | min-avail 49255MiB | peak-load 0.71
```
