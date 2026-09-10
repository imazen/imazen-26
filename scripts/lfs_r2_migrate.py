#!/usr/bin/env python3
"""lfs_r2_migrate.py — move a variant branch's Git LFS objects onto R2, and verify them.

Three idempotent steps:

  plan    read every LFS pointer on a ref, map its path to the R2 key that already
          holds the same bytes, and write a TSV: path, oid, size, src_key, src_size, status
  copy    server-side CopyObject each planned row to s3://<dst-bucket>/<dst-prefix><oid>
          (skips rows whose destination already exists at the right size)
  verify  ask the LFS server for a download URL per oid — exactly what a git-lfs client
          does — stream the bytes, and check sha256 + size against the pointer
  seed-cache
          fill a clone's .git/lfs/objects from the public mirror of the source keys
          (hash-verified), so `git lfs push` can run without fetching from GitHub LFS

Only the standard library plus the aws CLI (for plan --check-src and copy) are used.
Credentials for plan/copy come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY and the
endpoint from R2_ENDPOINT (or R2_ACCOUNT_ID). verify needs no credentials beyond the
ones embedded in the LFS URL.

Examples:
  scripts/lfs_r2_migrate.py plan --ref origin/variant/png-v3 \
      --map png-v3/=imazen-26-png-v3/ --src-bucket codec-corpus --check-src \
      --out ~/tmp/lfs-migration/png-v3.plan.tsv
  scripts/lfs_r2_migrate.py copy --plan ~/tmp/lfs-migration/png-v3.plan.tsv \
      --src-bucket codec-corpus --dst-bucket git-lfs --dst-prefix imazen-26/ --jobs 16
  scripts/lfs_r2_migrate.py verify --plan ~/tmp/lfs-migration/png-v3.plan.tsv \
      --lfs-url "$(git show origin/variant/png-v3:.lfsconfig | sed -n 's/^\\s*url = //p')"
"""
import argparse
import base64
import csv
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

POINTER_HEAD = b"version https://git-lfs.github.com/spec/v1"
LFS_MIME = "application/vnd.git-lfs+json"
# The public bucket domain sits behind Cloudflare's bot rules, which 403 the
# default Python-urllib user agent; identify ourselves instead.
USER_AGENT = "imazen-26 lfs_r2_migrate (+https://github.com/imazen/imazen-26)"
FIELDS = ["path", "oid", "size", "src_key", "src_size", "status"]


def endpoint_url():
    ep = os.environ.get("R2_ENDPOINT")
    if not ep:
        acct = os.environ.get("R2_ACCOUNT_ID")
        if not acct:
            sys.exit("set R2_ENDPOINT or R2_ACCOUNT_ID")
        ep = f"https://{acct}.r2.cloudflarestorage.com"
    return ep


def aws(*args, check=True):
    cmd = ["aws", "--endpoint-url", endpoint_url(), "--output", "json", "--region", "auto", *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[4:])}: {r.stderr.strip()}")
    return r


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_rows(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- plan

def list_pointers(ref):
    """Yield (path, oid, size) for every LFS pointer blob reachable from ref."""
    tree = subprocess.run(["git", "ls-tree", "-r", "-z", ref], capture_output=True, check=True).stdout
    entries = []
    for ent in tree.split(b"\0"):
        if not ent:
            continue
        meta, path = ent.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind == b"blob":
            entries.append((sha.decode(), path.decode()))
    proc = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    out = []
    for sha, path in entries:
        proc.stdin.write((sha + "\n").encode())
        proc.stdin.flush()
        header = proc.stdout.readline()
        _, _, size = header.split()
        body = proc.stdout.read(int(size))
        proc.stdout.read(1)  # trailing newline
        if not body.startswith(POINTER_HEAD):
            continue
        fields = dict(line.split(" ", 1) for line in body.decode().splitlines() if " " in line)
        oid = fields["oid"].split(":", 1)[1]
        out.append((path, oid, int(fields["size"])))
    proc.stdin.close()
    proc.wait()
    return out


def list_bucket_sizes(bucket, prefix):
    """key -> size for every object under prefix (paged list-objects-v2)."""
    sizes = {}
    token = None
    while True:
        args = ["s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix, "--max-keys", "1000"]
        if token:
            args += ["--continuation-token", token]
        d = json.loads(aws(*args).stdout or "{}")
        for o in d.get("Contents", []):
            sizes[o["Key"]] = o["Size"]
        token = d.get("NextContinuationToken")
        if not token:
            break
    return sizes


def cmd_plan(a):
    maps = []
    for m in a.map:
        src, dst = m.split("=", 1)
        maps.append((src, dst))
    rows = []
    for path, oid, size in list_pointers(a.ref):
        src_key = ""
        for src, dst in maps:
            if path.startswith(src):
                src_key = dst + path[len(src):]
                break
        rows.append({"path": path, "oid": oid, "size": size, "src_key": src_key,
                     "src_size": "", "status": "unmapped" if not src_key else "planned"})
    if a.check_src:
        prefixes = sorted({dst for _, dst in maps})
        sizes = {}
        for p in prefixes:
            sizes.update(list_bucket_sizes(a.src_bucket, p))
        for r in rows:
            if not r["src_key"]:
                continue
            s = sizes.get(r["src_key"])
            r["src_size"] = "" if s is None else s
            r["status"] = "missing" if s is None else ("ok" if s == r["size"] else "size-mismatch")
    write_rows(a.out, rows)
    summary(rows)


# ---------------------------------------------------------------- copy

def head_size(bucket, key):
    r = aws("s3api", "head-object", "--bucket", bucket, "--key", key, check=False)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)["ContentLength"]


def copy_one(row, a):
    dst_key = a.dst_prefix + row["oid"]
    want = int(row["size"])
    if head_size(a.dst_bucket, dst_key) == want:
        row["status"] = "present"
        return row
    src = f"{a.src_bucket}/{row['src_key']}"
    aws("s3api", "copy-object", "--bucket", a.dst_bucket, "--key", dst_key,
        "--copy-source", urllib.parse.quote(src, safe="/"))
    got = head_size(a.dst_bucket, dst_key)
    row["status"] = "copied" if got == want else f"copy-size-mismatch:{got}"
    return row


def cmd_copy(a):
    rows = [r for r in read_rows(a.plan) if r["status"] in ("ok", "planned", "copied", "present")]
    skipped = [r for r in read_rows(a.plan) if r not in rows]
    if skipped:
        print(f"skipping {len(skipped)} rows whose plan status is not ok", file=sys.stderr)
    done = []
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(copy_one, r, a): r for r in rows}
        for i, f in enumerate(as_completed(futs), 1):
            r = futs[f]
            try:
                done.append(f.result())
            except Exception as e:  # noqa: BLE001
                r["status"] = f"error:{e}"
                done.append(r)
            if i % 100 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}", file=sys.stderr, flush=True)
    write_rows(a.out or a.plan, done + skipped)
    summary(done)


# ---------------------------------------------------------------- verify

def batch(lfs_url, objects, operation="download"):
    u = urllib.parse.urlsplit(lfs_url)
    headers = {"Accept": LFS_MIME, "Content-Type": LFS_MIME, "User-Agent": USER_AGENT}
    if u.username:
        cred = f"{urllib.parse.unquote(u.username)}:{urllib.parse.unquote(u.password or '')}"
        headers["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    clean = urllib.parse.urlunsplit((u.scheme, u.hostname + (f":{u.port}" if u.port else ""), u.path, u.query, ""))
    body = json.dumps({"operation": operation, "transfers": ["basic"],
                       "objects": [{"oid": o["oid"], "size": int(o["size"])} for o in objects]}).encode()
    req = urllib.request.Request(clean.rstrip("/") + "/objects/batch", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_hash(href, want_oid, want_size):
    h = hashlib.sha256()
    n = 0
    req = urllib.request.Request(href, headers={"Accept": "*/*", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
    got = h.hexdigest()
    if got != want_oid:
        return f"sha256-mismatch:{got}"
    if n != want_size:
        return f"size-mismatch:{n}"
    return "verified"


def cmd_verify(a):
    rows = read_rows(a.plan)
    if a.limit:
        rows = rows[: a.limit]
    results = {}
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = {}
        for i in range(0, len(rows), 100):
            chunk = rows[i:i + 100]
            resp = batch(a.lfs_url, chunk)
            by_oid = {o["oid"]: o for o in resp.get("objects", [])}
            for r in chunk:
                o = by_oid.get(r["oid"])
                if o is None:
                    results[r["oid"]] = "not-in-batch-response"
                elif "error" in o:
                    results[r["oid"]] = f"batch-error:{o['error'].get('code')}:{o['error'].get('message')}"
                else:
                    href = o["actions"]["download"]["href"]
                    futs[ex.submit(fetch_hash, href, r["oid"], int(r["size"]))] = r["oid"]
        for i, f in enumerate(as_completed(futs), 1):
            oid = futs[f]
            try:
                results[oid] = f.result()
            except urllib.error.HTTPError as e:
                results[oid] = f"http-{e.code}"
            except Exception as e:  # noqa: BLE001
                results[oid] = f"error:{e}"
            if i % 100 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)}", file=sys.stderr, flush=True)
    for r in rows:
        r["status"] = results.get(r["oid"], "not-attempted")
    write_rows(a.out or a.plan, rows)
    summary(rows)
    bad = [r for r in rows if r["status"] != "verified"]
    sys.exit(1 if bad else 0)


# ---------------------------------------------------------------- seed-cache

def seed_one(row, a):
    oid = row["oid"]
    want = int(row["size"])
    dest = os.path.join(a.git_dir, "lfs", "objects", oid[:2], oid[2:4], oid)
    if os.path.exists(dest) and os.path.getsize(dest) == want:
        row["status"] = "cached"
        return row
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = a.public_base.rstrip("/") + "/" + urllib.parse.quote(row["src_key"])
    h = hashlib.sha256()
    n = 0
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            out.write(chunk)
            n += len(chunk)
    if h.hexdigest() != oid or n != want:
        os.unlink(tmp)
        row["status"] = f"mismatch:sha={h.hexdigest()[:12]}:size={n}"
        return row
    os.replace(tmp, dest)
    row["status"] = "seeded"
    return row


def cmd_seed_cache(a):
    rows = read_rows(a.plan)
    done = []
    with ThreadPoolExecutor(a.jobs) as ex:
        futs = {ex.submit(seed_one, r, a): r for r in rows}
        for i, f in enumerate(as_completed(futs), 1):
            r = futs[f]
            try:
                done.append(f.result())
            except Exception as e:  # noqa: BLE001
                r["status"] = f"error:{e}"
                done.append(r)
            if i % 100 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}", file=sys.stderr, flush=True)
    write_rows(a.out or a.plan, done)
    summary(done)
    sys.exit(1 if any(r["status"] not in ("seeded", "cached") for r in done) else 0)


def summary(rows):
    counts = {}
    total = 0
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        total += int(r["size"] or 0)
    print(f"rows={len(rows)} bytes={total} ({total / 1e9:.2f} GB) " +
          " ".join(f"{k}={v}" for k, v in sorted(counts.items())))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("--ref", required=True)
    s.add_argument("--map", action="append", default=[], help="branch-prefix=r2-prefix (repeatable)")
    s.add_argument("--src-bucket")
    s.add_argument("--check-src", action="store_true", help="list the source prefixes and compare sizes")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("copy")
    s.add_argument("--plan", required=True)
    s.add_argument("--src-bucket", required=True)
    s.add_argument("--dst-bucket", required=True)
    s.add_argument("--dst-prefix", default="")
    s.add_argument("--jobs", type=int, default=16)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_copy)
    s = sub.add_parser("verify")
    s.add_argument("--plan", required=True)
    s.add_argument("--lfs-url", required=True)
    s.add_argument("--jobs", type=int, default=8)
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("seed-cache")
    s.add_argument("--plan", required=True)
    s.add_argument("--public-base", required=True, help="e.g. https://codec-corpus.r2.imazen.org")
    s.add_argument("--git-dir", required=True, help="the clone's .git directory")
    s.add_argument("--jobs", type=int, default=8)
    s.add_argument("--out")
    s.set_defaults(fn=cmd_seed_cache)
    a = p.parse_args()
    if a.cmd == "plan" and a.check_src and not a.src_bucket:
        p.error("--check-src needs --src-bucket")
    a.fn(a)


if __name__ == "__main__":
    main()
