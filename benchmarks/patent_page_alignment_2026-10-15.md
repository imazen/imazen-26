# Patent rescans against their 1-bit originals (2026-10-15)

The 6000 class holds three US patents. Each comes as a 1-bit original plus a colour and a
gray rescan of a print. A page and its rescans must share a train/validate/test bucket.
This note checks which 1-bit page each rescan shows.

**Method.**
- Every page was OCR'd at full resolution with tesseract 5.5.0 (`--psm 3`, English). The
  originals run 2320×3408 and the rescans 2479×3230 pixels, so both are scanned at about
  300 dpi.
- Each rescan page was matched to the 1-bit page of the same patent with the highest
  Jaccard overlap of words of four or more letters. Per-page scores are in
  `patent_page_alignment_2026-10-15.tsv`.
- Drawing sheets have too few words for OCR to decide, so they were compared by eye, side by
  side.

**Result.**

| patent | 1-bit pages | rescan pages | which 1-bit page each rescan shows |
|---|--:|--:|---|
| us5046022 | 29 | 30 | the same page number. Text pages 9–29 match with Jaccard 0.84–1.00; drawing sheets 2–7 (pages 3–8) match by eye; rescan page 30 is a blank back page (6058, 6088) |
| us77494 | 3 | 3 | the same page number. Jaccard 0.43, 0.93 and 0.79; page 1 is a drawing |
| us3807657 | 7 | 4 | pages **1, 3, 5, 7**. The print was rescanned on one side only. Text pages 5 and 7 match with Jaccard 0.98–1.00; pages 1 and 3 match by eye |

Colour and gray rescans agree on every text page.

**Consequence.**
- `6000-lilith-scans-public-patents/MANIFEST.tsv` gains `patent_page`. It is the page of
  the patent each file shows; it differs from `page` for six us3807657 rescans.
- The v1 family map (`manifests/split_map_family.tsv`) keyed patents by filename. The 1-bit
  files are named `-1bit_`, so they never joined their page's family, and all 36 pages with
  three variants straddled buckets.
- `manifests/split_map_family_v2.tsv` keys patents by `patent` + `patent_page`. No patent
  page crosses buckets there.
