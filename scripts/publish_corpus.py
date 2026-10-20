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
import time
import urllib.request
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
    attributes = base / ".gitattributes"
    declared = source / ".gitattributes"
    lfs_rules = declared.read_text() if declared.exists() else ""
    attributes.write_text(
        "*.md text eol=lf\n*.tsv text eol=lf\n*.cff text eol=lf\n"
        "*.py text eol=lf\n*.yml text eol=lf\n"
        "*.jpg -text\n*.jpeg -text\n*.png -text\n*.heic -text\n"
        "*.dng -text\n*.jxl -text\n" + lfs_rules)
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


def check_tree(base, revision, branch):
    """Reject every unlisted path, including extensionless filesystem artifacts."""
    allowed = {"README.md", "DECODING.md", "CITATION.cff", "manifest.tsv", "CHANGELOG.md",
               ".gitattributes", ".lfsconfig", ".github/workflows/validate.yml",
               "tools/validate.py", "BRANCHES.tsv"}
    if branch != "main":
        manifest = subprocess.check_output(["git", "show", f"{revision}:manifest.tsv"], cwd=base, text=True)
        allowed.update(row["path"] for row in csv.DictReader(manifest.splitlines(), delimiter="\t"))
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", revision], cwd=base, text=True).splitlines()
    unexpected = set(paths) - allowed
    if unexpected:
        raise ValueError(f"unlisted committed paths: {len(unexpected)}; first: {min(unexpected)}")


def exclude_transient_files(base):
    exclude = base / ".git/info/exclude"
    text = exclude.read_text() if exclude.exists() else ""
    if ".fuse_hidden*" not in text.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(text + "\n.fuse_hidden*\n")


def push(base, branch):
    candidate = run(["jj", "log", "--no-graph", "-r", "@", "-T", "commit_id"], cwd=base, capture=True)
    check_tree(base, candidate, branch)
    old = subprocess.run(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
                         cwd=base, capture_output=True, text=True)
    if old.returncode == 0:
        run(["git", "merge-base", "--is-ancestor", old.stdout.strip(), candidate], cwd=base)
    run(["jj", "bookmark", "set", branch, "-r", "@"], cwd=base)
    run(["jj", "git", "push", "--bookmark", branch], cwd=base)
    revision = sha(base, branch)
    run(["git", "merge-base", "--is-ancestor", revision, f"origin/{branch}"], cwd=base)
    # Non-main data bookmarks need an explicit child; they may remain mutable after push.
    if sha(base, "@") == revision:
        run(["jj", "new", branch, "-m", "data: append the next publication batch"], cwd=base)
    return revision


def repositories(args):
    if not (args.receipts / "inputs.json").exists() or not (args.receipts / "lfs.json").exists():
        raise ValueError("input and public LFS verification are required first")
    for spec in plan(args):
        name = spec["repository"]
        base = args.repos / name
        if (args.receipts / f"{name}.json").exists():
            if not args.resume:
                raise ValueError("repository receipt already exists; use explicit resume")
            print(f"completed repository retained: {name}", flush=True)
            continue
        if base.exists():
            if not args.resume or not (base / ".workongoing").exists() or AGENT not in (base / ".workongoing").read_text():
                raise ValueError("existing repository is not an explicitly resumed owned checkout")
            origin = run(["git", "config", "--get", "remote.origin.url"], cwd=base, capture=True)
            if origin != f"https://github.com/imazen/{name}.git":
                raise ValueError("existing publication checkout has a different remote")
            visibility = run(["gh", "repo", "view", f"imazen/{name}", "--json", "visibility", "--jq", ".visibility"], capture=True)
            if visibility != "PRIVATE":
                raise ValueError("repository upload resume requires private staging")
            run(["jj", "git", "fetch"], cwd=base)
            root = sha(base, "main")
        else:
            base.mkdir(parents=True, exist_ok=False)
            refresh(base)
            run(["jj", "git", "init", "--colocate", base])
            run(["jj", "config", "set", "--repo", "snapshot.max-new-file-size", "100MiB"], cwd=base)
            # NAS-created directories use the share owner; trust only this newly created path.
            run(["git", "config", "--global", "--add", "safe.directory", base])
            run(["git", "config", "pack.threads", "4"], cwd=base)
            run(["git", "config", "core.compression", "1"], cwd=base)
            run(["git", "config", "pack.compression", "1"], cwd=base)
            run(["git", "config", "pack.window", "0"], cwd=base)
            exclude_transient_files(base)
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
        exclude_transient_files(base)
        for branch in spec["branches"]:
            prior = subprocess.run(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
                                   cwd=base, capture_output=True, text=True)
            start = f"{branch}@origin" if prior.returncode == 0 else root
            run(["jj", "new", start, "-m", f"data: add {branch} bucket"], cwd=base)
            metadata(base, args.stage / name / branch, args.version)
            selected = rows(args.stage / name / f"{branch}.sources.tsv")
            pending = []
            for row in selected:
                file = base / row["path"]
                if file.exists():
                    valid = file.read_bytes() == pointer(row) if spec["lfs"] else digest(file) == row["sha256"]
                    if not valid:
                        raise ValueError("resumed checkout has a changed encoded file")
                else:
                    pending.append(row)
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


def sync_docs(args):
    """Append approved membership guidance and refresh the branch pins before exposure."""
    if any(not (args.receipts / f"{spec['repository']}.json").exists() for spec in plan(args)):
        raise ValueError("all four repository upload receipts are required first")
    for spec in plan(args):
        name = spec["repository"]
        base = args.repos / name
        receipt_path = args.receipts / f"{name}.json"
        receipt = json.loads(receipt_path.read_text())
        previous = json.loads(receipt_path.read_text())
        for branch in [*spec["branches"], "main"]:
            desired = (args.stage / name / branch / "README.md").read_bytes()
            old = subprocess.check_output(["git", "show", f"{receipt['refs'][branch]}:README.md"], cwd=base)
            if old == desired:
                continue
            run(["jj", "new", branch, "-m", "docs: align source guidance with XL membership"], cwd=base)
            (base / "README.md").write_bytes(desired)
            if branch == "main":
                with (base / "BRANCHES.tsv").open("w") as stream:
                    stream.write("branch\tcommit\tmanifest_sha256\n")
                    for bucket in spec["branches"]:
                        stream.write(f"{bucket}\t{receipt['refs'][bucket]}\t{spec['manifest_sha256'][bucket]}\n")
            receipt["refs"][branch] = push(base, branch)
        if receipt != previous:
            save(args.receipts / f"{name}.before-readme.json", previous)
            receipt_path.rename(args.receipts / f"{name}.upload.json")
            save(receipt_path, receipt)


def verify_git(args):
    for spec in plan(args):
        name = spec["repository"]
        base = args.repos / name
        receipt = json.loads((args.receipts / f"{name}.json").read_text())
        reachable = subprocess.check_output(["git", "rev-list", *receipt["refs"].values()], cwd=base, text=True).splitlines()
        for commit in reachable:
            # A branch's manifest identifies its bucket; main's full catalogue has no data paths.
            branches = subprocess.check_output(["git", "show", f"{commit}:manifest.tsv"], cwd=base, text=True)
            buckets = {r["bucket"] for r in csv.DictReader(branches.splitlines(), delimiter="\t")}
            check_tree(base, commit, next(iter(buckets)) if len(buckets) == 1 else "main")
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
        visibility = run(["gh", "repo", "view", f"imazen/{name}", "--json", "visibility", "--jq", ".visibility"], capture=True)
        if visibility != "PUBLIC":
            run(["gh", "repo", "edit", f"imazen/{name}", "--visibility", "public",
                 "--accept-visibility-change-consequences"])
        run(["gh", "api", f"repos/imazen/{name}/actions/permissions", "--method", "PUT", "-F", "enabled=true"])
        receipt = json.loads((args.receipts / f"{name}.verified.json").read_text())
        checks = json.loads(run(["gh", "run", "list", "-R", f"imazen/{name}", "--workflow", "validate.yml",
                                "--branch", "main", "--limit", "10", "--json", "headSha"], capture=True))
        if any(x["headSha"] == receipt["refs"]["main"] for x in checks):
            continue
        for attempt in range(6):
            dispatched = subprocess.run(["gh", "workflow", "run", "validate.yml", "-R", f"imazen/{name}",
                                         "--ref", "main"], capture_output=True, text=True)
            print(dispatched.stdout + dispatched.stderr, end="", flush=True)
            if dispatched.returncode == 0:
                break
            # Actions can list a newly enabled workflow before indexing its dispatch trigger.
            if attempt == 5 or not ("HTTP 422" in dispatched.stderr and "workflow_dispatch" in dispatched.stderr):
                dispatched.check_returncode()
            print("Waiting 5 seconds for Actions workflow registration", flush=True)
            time.sleep(5)
    save(args.receipts / "public.json", {"repositories": [s["repository"] for s in plan(args)]})


def client_check(args):
    """Fetch fresh public data branches, plus XL objects through the Git LFS client."""
    if not (args.receipts / "public.json").exists():
        raise ValueError("public exposure must precede anonymous consumer checks")
    results = []
    for spec in plan(args):
        name = spec["repository"]
        base = args.repos.parent / "consumer-checks" / name
        base.mkdir(parents=True, exist_ok=False)
        refresh(base)
        run(["jj", "git", "init", "--colocate", base])
        run(["git", "config", "--global", "--add", "safe.directory", base])
        run(["jj", "config", "set", "--repo", "snapshot.max-new-file-size", "100MiB"], cwd=base)
        run(["jj", "git", "remote", "add", "origin", f"https://github.com/imazen/{name}.git"], cwd=base)
        branch = "train" if spec["lfs"] else "test"
        selected_branches = spec["branches"] if spec["lfs"] else [branch]
        command = ["jj", "git", "fetch"]
        for selected in selected_branches:
            command += ["--branch", selected]
        run(command, cwd=base)
        run(["jj", "new", f"{branch}@origin", "-m", "test: verify published consumer checkout"], cwd=base)
        receipt = json.loads((args.receipts / f"{name}.verified.json").read_text())
        if sha(base, f"{branch}@origin") != receipt["refs"][branch]:
            raise ValueError("fresh consumer checkout differs from the pinned commit")
        public_manifest = f"https://raw.githubusercontent.com/imazen/{name}/{receipt['refs'][branch]}/manifest.tsv"
        request = urllib.request.Request(public_manifest, headers={"User-Agent": "imazen-26 publication"})
        with urllib.request.urlopen(request, timeout=90) as response:
            public_hash = hashlib.file_digest(response, "sha256").hexdigest()
        if public_hash != spec["manifest_sha256"][branch]:
            raise ValueError("anonymous public manifest differs from the approved bytes")
        run(["python3", "tools/validate.py", "--branch", branch], cwd=base)
        object_count = 0
        if spec["lfs"]:
            run(["git", "lfs", "fetch", "--all", "origin"], cwd=base)
            for row in rows(args.stage / name / "main/manifest.tsv"):
                oid = row["sha256"]
                file = base / ".git/lfs/objects" / oid[:2] / oid[2:4] / oid
                if file.stat().st_size != int(row["bytes"]) or digest(file) != oid:
                    raise ValueError("Git LFS client object differs from the approved bytes")
                object_count += 1
        if run(["jj", "diff", "--summary"], cwd=base, capture=True):
            raise ValueError("consumer validation changed its checkout")
        (base / ".workongoing").unlink()
        results.append({"repository": name, "branch": branch, "commit": receipt["refs"][branch],
                        "branch_files": len(rows(base / "manifest.tsv")), "lfs_files": object_count,
                        "anonymous_manifest_sha256": public_hash})
    save(args.receipts / "consumer-checks.json", results)


def release(args):
    if not (args.receipts / "consumer-checks.json").exists():
        raise ValueError("fresh public consumer checks are required before tagging")
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
        remote_tag = run(["gh", "api", f"repos/imazen/{name}/git/ref/tags/{tag}",
                          "--jq", ".object.sha"], capture=True)
        published = json.loads(run(["gh", "release", "view", tag, "-R", f"imazen/{name}",
                                    "--json", "tagName,isDraft,isPrerelease,url"], capture=True))
        visibility = run(["gh", "repo", "view", f"imazen/{name}", "--json", "visibility", "--jq", ".visibility"], capture=True)
        request = urllib.request.Request(f"https://raw.githubusercontent.com/imazen/{name}/{tag}/README.md",
                                         headers={"User-Agent": "imazen-26 publication"})
        with urllib.request.urlopen(request, timeout=90) as response:
            public_readme = response.read()
        if (remote_tag != receipt["refs"]["main"] or visibility != "PUBLIC"
                or published["isDraft"] or published["isPrerelease"] or published["tagName"] != tag
                or public_readme != (args.stage / name / "main/README.md").read_bytes()):
            raise ValueError("remote release, tag, visibility or public README verification failed")
        save(args.receipts / f"{name}.release.json", {**published, "commit": remote_tag,
             "readme_sha256": hashlib.sha256(public_readme).hexdigest(), "visibility": visibility})
    save(args.receipts / "released.json", {"version": args.version, "repositories": [s["repository"] for s in plan(args)]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["verify-inputs", "lfs", "repositories", "sync-docs", "verify-git", "expose", "client-check", "release"])
    parser.add_argument("stage", type=Path)
    parser.add_argument("repos", type=Path)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("--version", default="2026.10.19")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.receipts.mkdir(parents=True, exist_ok=True)
    {"verify-inputs": verify_inputs, "lfs": lfs, "repositories": repositories, "sync-docs": sync_docs,
     "verify-git": verify_git, "expose": expose, "client-check": client_check,
     "release": release}[args.phase](args)


if __name__ == "__main__":
    main()
