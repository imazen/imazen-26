#!/usr/bin/env python3
"""Record a built tool, its lock, and runtime package source identities."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("binary", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    graph = json.loads(args.metadata.read_text())
    packages = []
    for package in sorted(graph["packages"], key=lambda row: (row["name"], row["id"])):
        row = {key: package[key] for key in ("name", "version", "source", "manifest_path")}
        if package["source"] is None:
            root = Path(package["manifest_path"]).parent
            inputs = [Path(package["manifest_path"]), *sorted((root / "src").rglob("*.rs"))]
            if (root / "build.rs").exists():
                inputs.append(root / "build.rs")
            sha = hashlib.sha256()
            for path in inputs:
                sha.update(str(path.relative_to(root)).encode() + b"\0")
                sha.update(path.read_bytes())
            row["rust_and_manifest_sha256"] = sha.hexdigest()
            revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                      capture_output=True, text=True)
            row["checkout_parent"] = revision.stdout.strip() if revision.returncode == 0 else None
        packages.append(row)
    result = {"binary": str(args.binary), "binary_sha256": digest(args.binary),
              "manifest_sha256": digest(args.manifest),
              "cargo_lock_sha256": digest(args.manifest.parent / "Cargo.lock"),
              "metadata_sha256": digest(args.metadata), "packages": packages}
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "packages"}))


if __name__ == "__main__":
    main()
