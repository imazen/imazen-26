# Metadata removal review — 2026-10-19

All 2,115 manifest originals have source/public native-inventory comparisons, metadata
field-name differences and live public-object SHA-256 verification. No shipped file changed.
291 sources have GPS position metadata: 48 inside Colorado, 243 outside its inclusive state
bounding box. The shipped originals have none. Two partial source positions (11211, 11628)
are conclusively outside on their known axis; no classification is unresolved.

- Review: http://dev.lan:3300/imazen-26/strip-review-2026-10-19/index.html
- Local, checked on dev: `/mnt/v/output/imazen-26/strip-review-2026-10-19/`
- Tower mirror: `/mnt/tower/output/imazen-26-strip-review-2026-10-19/`
- `SHA256SUMS` SHA-256: `6a352637bb9328a2987902d516508682a23fb501fd5f33a59a9f4d9343f8b15c`
- `summary.json` binds manifests, inventory binary/commit, ExifTool version and
  [Census state geometry](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/0).
  Per-file records retain their audit-tool hashes; the two repaired records and their
  previous versions are preserved. No position or metadata value was serialized.
- Inventory: zenpipe `841a171c`; review tool `7f285dae`, partial-position classifier
  `1f8a3c63`. Encoded-part differences describe bytes, including recompression, rather
  than asserting a decoded-pixel change. Nested parts can overlap their parent.
- Full pass: run-heavy, 565 s, peak RSS 0.50 GiB, minimum available 46,573 MiB;
  two partial positions initially unclassified. Retry: 5 s, peak RSS 0.17 GiB,
  minimum available 46,907 MiB; 2,115/2,115 complete, zero errors.

Run with `tools/metadata-loss-audit/justfile`; private source/archive paths are supplied
in a local configuration, not committed. The page supplies per-file JSON, structural
differences and field-name tables, plus aggregate part/tag and field summaries. The owner
reviews those removals before deciding whether the export policy should change.
