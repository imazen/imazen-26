#!/usr/bin/env python3
"""Publish an approved prepared corpus using jj, bounded pushes and pinned branches.

Caller supplies run-heavy and the shared build lock. Publication has explicit phases:
verify-inputs, lfs, repositories, verify-git, expose, and release. Existing repository
directories are never overwritten, and each phase writes an exclusive receipt.
"""
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import lfs_r2_migrate
import r2_originals_sync
from validate_export_repo import pointer

AGENT = "codex-imazen26-finalize"
REPO = Path(__file__).resolve().parents[1]
CHUNK_BYTES = 1_200_000_000
WORKFLOW = """name: Validate dataset
on:
  push:
    branches: [main, train, validate, test]
  workflow_dispatch:
jobs:
  validate:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-11-arm, macos-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v7
        with:
          lfs: false
      - uses: actions/setup-python@v7
        with:
          python-version: '3.14'
      - run: python tools/validate.py --branch "${{ github.ref_name }}"
"""


def refresh(repo):
    (repo / ".workongoing").write_text(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        + f" {AGENT} approved corpus publication\n")


def run(args, cwd=None, capture=False, env=None):
    if cwd is not None and (cwd / ".workongoing").exists():
        refresh(cwd)
    print("RUN " + " ".join(map(str, args)), flush=True)
    result = subprocess.run(list(map(str, args)), cwd=cwd, env=env,
                            capture_output=capture, text=True, check=True)
    return result.stdout.strip() if capture else None


def rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


def plan(args):
    return json.loads((args.stage / "publication-plan.json").read_text())


def verify_inputs(args):
    result = []
    sets = {}
    for spec in plan(args):
        base = args.stage / spec["repository"]
        main = rows(base / "main/manifest.tsv")
        ids = {row["id"] for row in main}
        sets[spec["repository"]] = ids
        if len(main) != spec["files"] or len(ids) != spec["images"]:
            raise ValueError("publication counts changed")
        branch_paths = set()
        for branch in ["main", *spec["branches"]]:
            if digest(base / branch / "manifest.tsv") != spec["manifest_sha256"][branch]:
                raise ValueError("approved manifest hash changed")
            selected = rows(base / branch / "manifest.tsv")
            sources = rows(base / f"{branch}.sources.tsv")
            if [(r["path"], r["sha256"], r["bytes"]) for r in selected] != [
                    (r["path"], r["sha256"], r["bytes"]) for r in sources]:
                raise ValueError("private source map differs from public manifest")
            if branch != "main":
                if any(row["bucket"] != branch for row in selected):
                    raise ValueError("holdout membership changed")
                if branch_paths.intersection(r["path"] for r in selected):
                    raise ValueError("file appears in multiple buckets")
                branch_paths.update(r["path"] for r in selected)
        if branch_paths != {r["path"] for r in main}:
            raise ValueError("branch union differs from main catalogue")
        for n, row in enumerate(rows(base / "main.sources.tsv"), 1):
            source = Path(row["source"])
            if source.stat().st_size != int(row["bytes"]) or digest(source) != row["sha256"]:
                raise ValueError(f"source file changed: {row['path']}")
            if not spec["lfs"] and int(row["bytes"]) > 100 * 1024**2:
                raise ValueError("raw Git file exceeds 100 MiB")
            if n % 100 == 0:
                print(f"verified source {spec['repository']} {n}/{len(main)}", flush=True)
        result.append({"repository": spec["repository"], "files": len(main),
                       "bytes": sum(int(r["bytes"]) for r in main)})
    if not (sets["imazen-26-originals"] == sets["imazen-26-jxl-p3"]
            == sets["imazen-26-jxl-srgb"]) or sets["imazen-xl-26"] & sets["imazen-26-originals"]:
        raise ValueError("approved image membership parity changed")
    save(args.receipts / "inputs.json", result)


def lfs(args):
    if not (args.receipts / "inputs.json").exists():
        raise ValueError("full source verification is required before R2 writes")
    base = args.stage / "imazen-xl-26"
    selected = rows(base / "main.sources.tsv")
    c = r2_originals_sync.creds()
    env = r2_originals_sync.temp_env(c, "codec-corpus", "object-read-write",
                                   ["lfs/imazen-26/"], ttl=7200)
    url = run(["git", "config", "-f", base / "main/.lfsconfig", "--get", "lfs.url"], capture=True)
    verified = []
    for row in selected:
        key = "lfs/imazen-26/" + row["sha256"]
        head = subprocess.run(["aws", "--endpoint-url", r2_originals_sync.endpoint(c),
                               "s3api", "head-object", "--bucket", "codec-corpus", "--key", key],
                              env=env, capture_output=True, text=True)
        if head.returncode:
            if "404" not in head.stderr and "Not Found" not in head.stderr:
                raise RuntimeError("R2 object check failed: " + head.stderr)
            run(["aws", "--endpoint-url", r2_originals_sync.endpoint(c), "s3api", "put-object",
                 "--bucket", "codec-corpus", "--key", key, "--body", row["source"]], env=env)
        elif json.loads(head.stdout)["ContentLength"] != int(row["bytes"]):
            raise ValueError("existing content-addressed object has incorrect size")
        objects = lfs_r2_migrate.batch(url, [{"oid": row["sha256"], "size": row["bytes"]}])["objects"]
        if len(objects) != 1 or "error" in objects[0]:
            raise ValueError("LFS batch did not return the requested object")
        status = lfs_r2_migrate.fetch_hash(objects[0]["actions"]["download"]["href"],
                                         row["sha256"], int(row["bytes"]))
        if status != "verified":
            raise ValueError("public LFS object verification failed: " + status)
        verified.append({k: row[k] for k in ["path", "sha256", "bytes"]})
        print(f"public LFS verified {len(verified)}/{len(selected)}", flush=True)
    save(args.receipts / "lfs.json", verified)


def metadata(base, source, version):
    for file in source.iterdir():
        if not file.is_file():
            raise ValueError("unexpected metadata directory")
        shutil.copy2(file, base / file.name)
    (base / "tools").mkdir(exist_ok=True)
    shutil.copy2(REPO / "scripts/validate_export_repo.py", base / "tools/validate.py")
    (base / ".github/workflows").mkdir(parents=True, exist_ok=True)
    (base / ".github/workflows/validate.yml").write_text(WORKFLOW)
    (base / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### QUEUED BREAKING CHANGES\n\nNone.\n\n"
        f"## [{version}] - 2026-10-19\n\n### Added\n\n"
        "- Initial dataset publication with family-preserving train, validate and test branches.\n")


def sha(base, revision):
    return run(["jj", "--ignore-working-copy", "log", "--no-graph", "-r", revision,
                "-T", "commit_id"], cwd=base, capture=True)


def push(base, branch):
    run(["jj", "bookmark", "set", branch, "-r", "@"], cwd=base)
    run(["jj", "git", "push", "--bookmark", branch], cwd=base)
    revision = sha(base, branch)
    run(["git", "merge-base", "--is-ancestor", revision, f"origin/{branch}"], cwd=base)
    return revision


def repositories(args):
    if not (args.receipts / "inputs.json").exists() or not (args.receipts / "lfs.json").exists():
        raise ValueError("input and public LFS verification are required first")
    for spec in plan(args):
        name = spec["repository"]
        base = args.repos / name
        base.mkdir(parents=True, exist_ok=False)
        refresh(base)
        run(["jj", "git", "init", "--colocate", base])
        run(["jj", "config", "set", "--repo", "snapshot.max-new-file-size", "100MiB"], cwd=base)
        run(["git", "config", "pack.threads", "4"], cwd=base)
        run(["gh", "repo", "create", f"imazen/{name}", "--private", "--description",
             "imazen-26 image corpus: " + spec["layer"]])
        run(["gh", "api", f"repos/imazen/{name}/actions/permissions", "--method", "PUT", "-F", "enabled=false"])
        run(["jj", "git", "remote", "add", "origin", f"https://github.com/imazen/{name}.git"], cwd=base)
        metadata(base, args.stage / name / "main", args.version)
        run(["python3", "tools/validate.py", "--branch", "main"], cwd=base)
        run(["jj", "describe", "-m", "docs: introduce dataset and decoding guidance"], cwd=base)
        root = push(base, "main")
        run(["gh", "repo", "edit", f"imazen/{name}", "--default-branch", "main"])
        refs = {}
        for branch in spec["branches"]:
            run(["jj", "new", root, "-m", f"data: add {branch} bucket"], cwd=base)
            metadata(base, args.stage / name / branch, args.version)
            pending = rows(args.stage / name / f"{branch}.sources.tsv")
            chunks, chunk, size = [], [], 0
            for row in pending:
                cost = len(pointer(row)) if spec["lfs"] else int(row["bytes"])
                if chunk and size + cost > CHUNK_BYTES:
                    chunks.append(chunk)
                    chunk, size = [], 0
                chunk.append(row)
                size += cost
            if chunk or not chunks:
                chunks.append(chunk)
            for part, chunk in enumerate(chunks, 1):
                refresh(base)
                for row in chunk:
                    file = base / row["path"]
                    file.parent.mkdir(parents=True, exist_ok=True)
                    if spec["lfs"]:
                        file.write_bytes(pointer(row))
                    else:
                        shutil.copyfile(row["source"], file)
                        if digest(file) != row["sha256"]:
                            raise ValueError("copied image hash mismatch")
                if part == len(chunks):
                    run(["python3", "tools/validate.py", "--branch", branch], cwd=base)
                run(["jj", "describe", "-m", f"data: add {branch} bucket ({part}/{len(chunks)})"], cwd=base)
                refs[branch] = push(base, branch)
                print(f"PUSHED {name} {branch} {part}/{len(chunks)}", flush=True)
        run(["jj", "new", "main", "-m", "docs: pin the published holdout branch commits"], cwd=base)
        with (base / "BRANCHES.tsv").open("w") as stream:
            stream.write("branch\tcommit\tmanifest_sha256\n")
            for branch in spec["branches"]:
                stream.write(f"{branch}\t{refs[branch]}\t{spec['manifest_sha256'][branch]}\n")
        refs["main"] = push(base, "main")
        save(args.receipts / f"{name}.json", {"repository": name, "refs": refs,
             "manifest_sha256": spec["manifest_sha256"], "files": spec["files"], "bytes": spec["bytes"]})


def verify_git(args):
    for spec in plan(args):
        name = spec["repository"]
        base = args.repos / name
        receipt = json.loads((args.receipts / f"{name}.json").read_text())
        for branch, commit in receipt["refs"].items():
            remote = run(["gh", "api", f"repos/imazen/{name}/git/ref/heads/{branch}",
                          "--jq", ".object.sha"], capture=True)
            if remote != commit:
                raise ValueError("remote branch differs from publication receipt")
            data = subprocess.check_output(["git", "show", f"{commit}:manifest.tsv"], cwd=base)
            if hashlib.sha256(data).hexdigest() != spec["manifest_sha256"][branch]:
                raise ValueError("committed manifest differs from approved manifest")
            if branch == "main":
                continue
            selected = rows(args.stage / name / branch / "manifest.tsv")
            proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=base,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                for row in selected:
                    proc.stdin.write(f"{commit}:{row['path']}\n".encode())
                    proc.stdin.flush()
                    header = proc.stdout.readline().split()
                    if len(header) != 3 or header[1] != b"blob":
                        raise ValueError("committed image blob missing")
                    remaining = int(header[2])
                    if spec["lfs"]:
                        if remaining != len(pointer(row)) or proc.stdout.read(remaining) != pointer(row):
                            raise ValueError("committed LFS pointer mismatch")
                    else:
                        if remaining != int(row["bytes"]):
                            raise ValueError("committed encoded size mismatch")
                        h = hashlib.sha256()
                        while remaining:
                            block = proc.stdout.read(min(1 << 20, remaining))
                            if not block:
                                raise ValueError("truncated Git blob stream")
                            h.update(block)
                            remaining -= len(block)
                        if h.hexdigest() != row["sha256"]:
                            raise ValueError("committed encoded SHA-256 mismatch")
                    if proc.stdout.read(1) != b"\n":
                        raise ValueError("invalid Git batch delimiter")
            finally:
                proc.stdin.close()
                proc.stdout.close()
                if proc.wait() != 0:
                    raise ValueError("Git object verification process failed")
            print(f"verified committed bytes {name} {branch}: {len(selected)} files", flush=True)
        save(args.receipts / f"{name}.verified.json", receipt)


def expose(args):
    for spec in plan(args):
        name = spec["repository"]
        if not (args.receipts / f"{name}.verified.json").exists():
            raise ValueError("committed bytes must be verified before exposure")
        run(["gh", "repo", "edit", f"imazen/{name}", "--visibility", "public",
             "--accept-visibility-change-consequences"])
        run(["gh", "api", f"repos/imazen/{name}/actions/permissions", "--method", "PUT", "-F", "enabled=true"])
        run(["gh", "workflow", "run", "validate.yml", "-R", f"imazen/{name}", "--ref", "main"])
    save(args.receipts / "public.json", {"repositories": [s["repository"] for s in plan(args)]})


def release(args):
    for spec in plan(args):
        name = spec["repository"]
        base = args.repos / name
        receipt = json.loads((args.receipts / f"{name}.verified.json").read_text())
        checks = json.loads(run(["gh", "run", "list", "-R", f"imazen/{name}", "--branch", "main",
                                "--limit", "10", "--json", "headSha,status,conclusion"], capture=True))
        if not any(x["headSha"] == receipt["refs"]["main"] and x["conclusion"] == "success" for x in checks):
            raise ValueError("main CI must succeed before dataset tagging")
        tag = "v" + args.version
        run(["jj", "tag", "set", tag, "-r", "main"], cwd=base)
        run(["jj", "git", "push", "--tag", tag], cwd=base)
        note = args.receipts / f"{name}.release.md"
        with note.open("x") as stream:
            stream.write(f"Initial imazen-26 publication: {spec['images']} image IDs, {spec['files']} files, {spec['bytes']:,} encoded bytes.\n\n")
            stream.write("`main` and this tag contain documentation and the full catalogue. Image files are on `train`, `validate` and `test`. Validate and test are holdouts: exclude them from fitting, tuning and default selection. Related sources and renditions keep one bucket.\n\n")
            for branch in spec["branches"]:
                stream.write(f"- [{branch}](https://github.com/imazen/{name}/tree/{receipt['refs'][branch]}) — `{receipt['refs'][branch]}`; manifest SHA-256 `{spec['manifest_sha256'][branch]}`\n")
            stream.write("\n[Decoding guide](https://github.com/imazen/" + name + "/blob/" + receipt["refs"]["main"] + "/DECODING.md). ")
            stream.write("XL uses the public R2-backed Git LFS endpoint.\n" if spec["lfs"] else "Image bytes are stored directly in Git.\n")
            stream.write("\nPer-file licences and original source/attribution URLs are retained in `manifest.tsv`. See the [validation record](https://github.com/imazen/imazen-26/blob/main/benchmarks/current_main_recheck_2026-10-19.pointer.md).\n")
        run(["gh", "release", "create", tag, "-R", f"imazen/{name}", "--verify-tag",
             "--title", args.version, "--notes-file", note, "--generate-notes"])
    save(args.receipts / "released.json", {"version": args.version, "repositories": [s["repository"] for s in plan(args)]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["verify-inputs", "lfs", "repositories", "verify-git", "expose", "release"])
    parser.add_argument("stage", type=Path)
    parser.add_argument("repos", type=Path)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("--version", default="2026.10.19")
    args = parser.parse_args()
    args.receipts.mkdir(parents=True, exist_ok=True)
    {"verify-inputs": verify_inputs, "lfs": lfs, "repositories": repositories,
     "verify-git": verify_git, "expose": expose, "release": release}[args.phase](args)


if __name__ == "__main__":
    main()
