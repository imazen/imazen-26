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
