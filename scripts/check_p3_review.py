#!/usr/bin/env python3
"""Check that the public review serves the current P3 conversions and native bitmap hashes."""
import argparse
import csv
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "imazen-26-site-check"})
    return urllib.request.urlopen(request).read()


def rows(text):
    return list(csv.DictReader((line for line in text.splitlines() if not line.startswith("#")), delimiter="\t"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("site", type=Path)
    parser.add_argument("render", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    base = args.url.rstrip("/") + "/"
    remote_index = fetch(base + "data/index.json")
    if remote_index != (args.site / "data/index.json").read_bytes():
        raise ValueError("public index does not match the current local deployment")
    index = json.loads(remote_index)
    for cid in ["13005", "13006"]:
        image = next(image for image in index["images"] if image["id"] == cid)
        if image["col"] != "display-p3":
            raise ValueError("public tile still has the old colour")
    parts = []
    for name in index["hashesFiles"]:
        data = fetch(urllib.parse.urljoin(base, name))
        if data != (args.site / name).read_bytes():
            raise ValueError("public hash part differs from current deployment")
        parts.append(data)
    download = b"".join(parts)
    actual = rows(download.decode())
    keyed = {(r["path"], r["decoder"]): r for r in actual}
    if len(keyed) != len(actual):
        raise ValueError("duplicate public bitmap identities")
    expected = [r for r in rows((args.render / "decoded-xxh3.tsv").read_text())
                if r["path"].startswith(("png-p3/13000-", "jxl-p3/13000-"))
                and Path(r["path"]).name.startswith(("13005_", "13006_"))]
    if len(expected) != 8:
        raise ValueError("expected eight current native bitmap rows")
    for row in expected:
        new = keyed[row["path"], row["decoder"]]
        if new["xxh3"] != row["xxh3"] or new["status"] != "ok":
            raise ValueError("public bitmap hash is stale")
    result = {"url": base, "images": len(index["images"]), "converted_ids": ["13005", "13006"],
              "native_bitmap_rows_checked": len(expected), "download_bytes": len(download),
              "download_sha256": hashlib.sha256(download).hexdigest(), "unique_identities": len(keyed),
              "duplicate_identities": 0, "hash_parts": len(parts),
              "index_sha256": hashlib.sha256(remote_index).hexdigest()}
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
