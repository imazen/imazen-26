# Progressive JPEG alternatives measured, 2026-10-19

Artifacts checked on dev: `/mnt/v/output/imazen-26/progressive-lossless-measure-2026-10-19/`.
The reference renderer is retained there with SHA256
`28e0d99e732a5092abd6f621280fc65b3eb345fe2f8b44414d25f976a53fe7c3`.
Its exact build commit was not established; these are candidate size measurements,
not the final current-main redo. `measurement.meta` preserves that limitation and its lockfile.

The twelve PNG-twin encodes pass native pixel/metadata readback in both JXL families.
Both families produced the same bytes for these sRGB sources. Every file is below
104,857,600 bytes. Excluding XL ids 11455, 11458, 11521, 11540 and 12402, the projected
repository totals are 6,297,804,440 bytes for jxl-p3 and 4,903,867,897 bytes for jxl-srgb,
each below 10,000,000,000 bytes. The numbered redo and its full gates are recorded separately.

| Export id | Bytes in each JXL family |
| --- | ---: |
| 12003 | 8,769,541 |
| 12005 | 15,527,959 |
| 12009 | 4,345,858 |
| 12012 | 3,516,642 |
| 12013 | 10,588,266 |
| 12022 | 9,210,944 |
| 12203 | 17,159,638 |
| 12204 | 7,802,128 |
| 12207 | 47,241,291 |
| 12212 | 9,874,560 |
| 12402 | 68,717,977 |
| 12409 | 47,766,167 |

A progressive-to-sequential lossless JPEG transform succeeded on all twelve originals:
quantization tables and component coefficient payloads remained identical, JPEG decoded
pixels had maximum difference zero, and the original/rewritten coefficient JXL pixels agreed.
All twelve rewritten JPEGs acquired reconstruction data and were rebuilt byte-for-byte by
both the native decoder and libjxl v0.12. Native inventory checked all 36 original JPEG,
sequential JPEG and sequential JXL inputs and confirmed each JXL's `jbrd` part.
This is a measured alternative, not the shipped path. The diagnostic implementation is
`1699c213`; `sequential-full.tsv` has SHA256
`647f1819e3864f01d52757fdbda2420e8579e2306a065a08f3ffde4562f11288`.
The oracle run's source hashes remain in `sequential-oracle/summary.json`; a later
coverage guard rejects empty, duplicate or incomplete case lists.

Resource records: six small candidates, 748 s, run-heavy peak RSS 8.42 GiB,
minimum available 38,506 MiB; two large candidates, 505 s, peak RSS 4.99 GiB,
minimum available 43,059 MiB. Full sequential diagnostics: 42 s, peak RSS 3.46 GiB,
minimum available 43,726 MiB. Native inventory/libjxl oracle: 15 s, peak RSS 0.40 GiB,
minimum available 46,411 MiB.

Final JXL redo 5 is applied in
`/mnt/tower/output/imazen-26-render-v4-2026-10-15/`; its `jxl-redo-5-evidence/`
retains the three-reader/twin, inventory, byte-scan and promotion reports.
`before-jxl-redo-5/` retains all 24 replaced files and the earlier reports/manifests.
The 24 current-main encodes exactly match the measured candidates above. All
72 affected JXL bitmap hashes now match the PNG twins; the other 17,204 full-table
rows are unchanged. The new `decoded-xxh3.tsv` SHA-256 is
`1c3b4d68d02ba6ea891658b9e77e06005de64dd93aa70e384d0e26ebc55ba14b`.

Measurement and sequential-diagnostic artifacts are mirrored at
`/mnt/tower/output/imazen-26-progressive-lossless-measure-2026-10-19/`;
three reproducible random file hashes were verified against dev's local copy.
The current-main encode took 926 s, run-heavy peak RSS 12.65 GiB, minimum
available 37,648 MiB; its final combined gate took 254 s, peak RSS 1.34 GiB,
minimum available 48,649 MiB. Full validation is in the
[render record](render_v4_validation_2026-10-15.md#2026-10-19-lossless-progressive-jpeg-twins-jxl-redo-5).
