#!/usr/bin/env python3
"""Validate a corpus export's manifest and its branch's files or LFS pointers."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


def pointer(row):
    return ("version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{row['sha256']}\nsize {row['bytes']}\n").encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    with Path("manifest.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    paths = set()
    encoded = 0
    lfs = Path(".lfsconfig").exists()
    for row in rows:
        path = PurePosixPath(row["path"])
        if path.is_absolute() or ".." in path.parts or row["path"] in paths:
            raise ValueError("unsafe or duplicate manifest path")
        paths.add(row["path"])
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) or int(row["bytes"]) <= 0:
            raise ValueError("invalid file hash or length")
        if row["bucket"] not in {"train", "validate", "test"}:
            raise ValueError("invalid holdout bucket")
        provenance = json.loads(row["provenance_json"])
        if provenance["id"] != row["id"] or provenance["split"] != row["bucket"]:
            raise ValueError("provenance identity or bucket mismatch")
        file = Path(row["path"])
        if args.branch == "main":
            if file.exists():
                raise ValueError("main must contain documentation only")
            continue
        if row["bucket"] != args.branch:
            raise ValueError("data branch contains another holdout bucket")
        if lfs:
            if file.read_bytes() != pointer(row):
                raise ValueError(f"LFS pointer mismatch: {file}")
        else:
            if file.stat().st_size != int(row["bytes"]):
                raise ValueError(f"file length mismatch: {file}")
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != row["sha256"]:
                raise ValueError(f"encoded SHA-256 mismatch: {file}")
        encoded += 1
    extras = {str(file.as_posix()) for file in Path(".").rglob("*")
              if file.is_file() and ".git" not in file.parts and ".jj" not in file.parts
              and file.suffix.lower() in {".jxl", ".png", ".jpg", ".jpeg", ".heic", ".dng"}}
    if extras != (set() if args.branch == "main" else paths):
        raise ValueError("encoded file membership differs from the manifest")
    print(f"validated {len(rows)} manifest records and {encoded} branch files"
          + (" (LFS pointer validation; object bytes verified at publication)" if lfs else ""))


if __name__ == "__main__":
    main()
