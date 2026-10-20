#!/usr/bin/env python3
"""Mirror validation evidence to a new directory and verify three sampled files."""
import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    destination = args.destination
    if not source.is_dir() or destination.resolve().is_relative_to(source):
        raise ValueError("source must be a directory outside the destination")
    destination.mkdir(parents=True, exist_ok=False)
    subprocess.run(["rsync", "-a", "--no-owner", "--no-group",
                    "--exclude=target/", "--exclude=.git/",
                    "--exclude=.jj/", "--exclude=.workongoing", "--exclude=__pycache__/",
                    str(source) + "/", str(destination) + "/"], check=True)
    files = sorted(path for path in destination.rglob("*")
                   if path.is_file() and not path.is_symlink())
    selected = random.Random(20261019).sample(files, min(3, len(files)))
    checked = []
    for target in selected:
        relative = target.relative_to(destination)
        original = source / relative
        digest = sha256(original)
        if digest != sha256(target):
            raise ValueError(f"mirror hash mismatch: {relative}")
        checked.append({"path": str(relative), "sha256": digest})
    result = {"source": str(source), "destination": str(destination),
              "regular_files": len(files), "sampled_sha256": checked,
              "excluded": ["target/", ".git/", ".jj/", ".workongoing", "__pycache__/"]}
    with (destination / "archive-verification.json").open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
