#!/usr/bin/env python3
"""Compare retained sample decodes with the stored files, separately per reader."""
import argparse
import csv
import json
from pathlib import Path


def table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'verify'])
    parser.add_argument('stored', type=Path)
    parser.add_argument('sample', type=Path)
    args = parser.parse_args()
    rows = table(args.sample / 'jxl-report.tsv') + table(args.sample / 'jxl-hdr-report.tsv')
    paths = [row['path'] for row in rows]
    assert paths and len(paths) == len(set(paths))
    out = args.sample / 'decode-parity'
    if args.mode == 'prepare':
        out.mkdir(exist_ok=False)
        (out / 'files.list').write_text(''.join(str(root / path) + '\n'
                                               for root in [args.stored, args.sample]
                                               for path in paths))
        return
    decoded = {}
    for name in ['native.tsv', 'libjxl.tsv']:
        for row in table(out / name):
            key = (row['path'], row['decoder'])
            assert key not in decoded
            assert row['status'] == 'ok' and not row['error'], key
            decoded[key] = row
    fields = ['width', 'height', 'channels', 'bits', 'orientation', 'xxh3',
              'metadata_bytes', 'metadata_xxh3', 'gm_status', 'gm_width',
              'gm_height', 'gm_channels', 'gm_bits', 'gm_xxh3']
    expected = set()
    for path in paths:
        for reader in ['zenjxl', 'jxl-rs', 'libjxl']:
            pair = []
            for root in [args.stored, args.sample]:
                key = (str(root / path), reader)
                expected.add(key)
                pair.append(tuple(decoded[key][field] for field in fields))
            assert pair[0] == pair[1], (path, reader)
    assert set(decoded) == expected
    summary = {'files': len(paths), 'readers': 3, 'decoded_rows': len(expected),
               'changed_decoded_samples_or_gainmaps': 0}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
