#!/usr/bin/env python3
"""Run each owned checkout's compatibility gate and retain every failure log."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roots', type=Path, help='JSON array of checkout paths')
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    results = []
    for root in map(Path, json.loads(args.roots.read_text())):
        with (args.out / (root.name + '.log')).open('w') as log:
            result = subprocess.run(['just', 'beta-cohort-check'], cwd=root,
                                    stdout=log, stderr=subprocess.STDOUT)
        results.append({'repo': root.name, 'exit': result.returncode})
        (args.out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(results[-1]), flush=True)
    return int(any(row['exit'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
