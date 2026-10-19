# metadata-loss-audit

Compares each corpus file with earlier copies of the same image, to find metadata lost
or changed on the way in. Results: `benchmarks/metadata_audit_earlier_copies_2026-09-25.md`.
Plain Python 3, standard library only; run from an output directory.

| script | does |
|---|---|
| `keys.py` | content key per file (JPEG scan data, PNG `IHDR`+`IDAT`, HEIC `hvc1` item data); paths on stdin |
| `match.py` | pairs canonical and earlier files by content key, name fallback for the rest → `matches.tsv` |
| `compare.py` | diffs colour/orientation/HDR/EXIF/XMP signals of each pair, from `corpus-signal-probe` output |
| `heif_props.py` | HEIF item → (type, `colr`/`auxC`/`irot`/`clli` properties) |
| `heic_diff.py` | per-item property diff of every HEIC against its pre-rewrite backup → `heic_prop_diff.tsv` |
| `exif_colour.py` | EXIF Make/Model/`ColorSpace`/Interop index for a list of JPEG ids |
| `tiff_tags.py` | tag-by-tag diff of two TIFF/DNG files |
| `png_scan.py` | walks roots, records each PNG's size and colour chunks (reads chunk headers only) |
| `oracle_check.py` | third-party re-check of whitelist-v2 outputs: exiftool tag values and `-validate`, `djpeg` and `heif-dec` pixels, `heif-info` structure, gain-map and motion-photo extraction |
| `jpeg_segs.py` | a JPEG's APPn/COM/DHT segment list and trailer length, for old-vs-new structure diffs |

```
find <canonical tree> -type f | python3 keys.py > canonical_keys.tsv
find <earlier trees>  -type f | python3 keys.py > candidate_keys.tsv
python3 match.py canonical_keys.tsv candidate_keys.tsv > matches.tsv
# probe the matched earlier copies with tools/corpus-signal-probe → cand_signal.tsv
python3 compare.py; python3 heic_diff.py
```

`compare.py` reads the signal index path and `cand_list.tsv`/`cand_signal.tsv` from the
current directory; the 2026-09-25 inputs and outputs are in
`/mnt/v/output/imazen-26-variants/metadata-audit-2026-09-25/`.

## Removal review

`strip_review.py` compares every original's source and published bytes with native
inventories and ExifTool. It saves part differences, metadata field names and GPS
presence/Colorado flags. Metadata values and native inventory labels/details stay
in memory. Source and public-object hashes must match their provenance records.
Private source paths belong in a caller-supplied JSON configuration.

```sh
just --justfile tools/metadata-loss-audit/justfile discover config.json
just --justfile tools/metadata-loss-audit/justfile review config.json 1000,1044
just --justfile tools/metadata-loss-audit/justfile review config.json
```

Configuration keys: `staging`, `matches`, `camera_manifest`, `camera_copies`,
`archive_bucket`, `archive_prefix`, `public_base`, `inventory`, `inventory_commit`,
`out`, and `workers`. The native CLI needs stdin support and RAW inventory. Local
inputs are read only; an unavailable pre-pass copy is read from the originals
archive into memory with `s5cmd cat`. Public objects are read live and verified.

The Colorado classifier uses the inclusive bounding box of the [Census state
geometry](https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/0).
No image position is sent to that service. A pilot's `--only` ids are explicit;
missing ids and per-file failures fail the run. `resume` accepts only completed
records from the same script version. Replaced report files retain timestamped
backups. The HTML index links every file's part and field tables and the summaries.

An incomplete GPS position keeps its structural and field comparison visible, with an
explicit classification error. `just --justfile tools/metadata-loss-audit/justfile render CONFIG`
rebuilds pages from saved value-free records and preserves the original audit provenance;
it records the renderer hash separately and never reopens an image.

A partial position is outside Colorado when its known axis is outside the state
bounding box; otherwise it remains unclassified. `repair CONFIG` retries failed
records, preserves successful records and prior audit provenance, and refuses a
changed manifest. Each record retains the hash of the tool that audited it.

`inventory_routes.py` checks an explicit TSV of `id`, `layer`, absolute `path`, and
`sha256`. It writes a status for every route and sanitized structural TSV rows. Only
fixed label prefixes from the export allow-list survive; arbitrary native labels and
details stay in memory. Any read, hash, inventory or unknown-part failure fails the run.
The nine-route pilot covers all four original formats and every current SDR JXL kind.

GPS grouping uses ExifTool document and metadata-group identity. CopyN is a tag
instance label, not a position identity; direction references must remain with their
coordinates. `reclassify-gps CONFIG` rechecks source hashes and classifications while
retaining the original inventory/field audit provenance. It fails on ambiguous
coordinate carriers instead of selecting one.
