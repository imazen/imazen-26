#!/usr/bin/env python3
"""Make the public R2 originals prefix match the manifests (EXPORT-PLAN.md, step 2).

Subcommands:

  plan <staging-dir> [--out plan.tsv]
      Read-only. Lists codec-corpus/imazen-26-unprocessed/ through the Cloudflare API and
      compares every object with the manifests and the staged files: `put` for a manifest
      path whose staged bytes differ from the object (its ETag recomputed locally: the MD5,
      or for a multipart upload the MD5 of the parts' MD5s at s5cmd's 50 MiB part size) or
      that has no object. An object no
      manifest lists is a document when git tracks its path in this repository (README.md,
      CORPUS-MANIFEST.tsv, the class folders' MANIFEST.tsv, PROVENANCE.md, LICENSE.md and
      so on): `put` the repository's copy when it differs. Under KEEP (the patent scans'
      source PDFs, which ACCESS.md lists) it stays: `keep`. Anything else: `delete`.

  checkpoint <src-bucket>/<src-prefix> <dst-bucket>/<dst-prefix> [--resume]
      Server-side copy of every object under the source prefix (s5cmd; keys with a space go
      through a local file), then a size and MD5 check of every copy. Run before `apply` into
      the private bucket, and again after it. --resume copies only what is missing.

  apply <plan.tsv> --owner-go
      Uploads every `put` (Content-Type by extension), then deletes every `delete`. The
      write credential is a temporary one scoped to the public prefix.

  verify
      Downloads every object under the public prefix and checks its sha256 and size against
      the manifests (documents against the repository's copies), and that the prefix holds
      exactly the manifest paths, the documents and KEEP.

Credentials come from ~/.config/cloudflare/r2-credentials. `plan` and `verify` only read.
"""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUCKET = "codec-corpus"
PREFIX = "imazen-26-unprocessed/"
TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".heic": "image/heic",
         ".dng": "image/x-adobe-dng", ".pdf": "application/pdf",
         ".md": "text/markdown; charset=utf-8", ".tsv": "text/tab-separated-values; charset=utf-8",
         ".py": "text/x-python; charset=utf-8"}
# Objects no manifest lists that stay as they are: the patent scans' source PDFs (ACCESS.md).
KEEP = ("6000-lilith-scans-public-patents/pdfs/",)


def creds():
    out = {}
    with open(os.path.expanduser("~/.config/cloudflare/r2-credentials")) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.removeprefix("export ").strip()] = v.strip().strip("'\"")
    return out


def api(c, path, method="GET", body=None):
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{c['R2_ACCOUNT_ID']}{path}", method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {c['R2_API_TOKEN']}", "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req))
    if not d.get("success"):
        raise SystemExit(f"Cloudflare API error on {path}: {d.get('errors')}")
    return d


def listing(c, bucket, prefix):
    objs, cursor = {}, None
    while True:
        q = {"prefix": prefix, "per_page": "1000"}
        if cursor:
            q["cursor"] = cursor
        d = api(c, f"/r2/buckets/{bucket}/objects?" + urllib.parse.urlencode(q))
        for o in d["result"]:
            objs[o["key"]] = (int(o.get("size") or 0), (o.get("etag") or "").strip('"'))
        info = d.get("result_info") or {}
        cursor = info.get("cursor")
        if not info.get("is_truncated"):
            return objs


def temp_env(c, bucket, permission, prefixes=None, ttl=7200):
    body = {"bucket": bucket, "parentAccessKeyId": c["R2_ACCESS_KEY_ID"],
            "parentSecretAccessKey": c["R2_SECRET_ACCESS_KEY"], "permission": permission,
            "ttlSeconds": ttl}
    if prefixes:
        body["prefixes"] = prefixes
    r = api(c, "/r2/temp-access-credentials", "POST", body)["result"]
    return dict(os.environ, AWS_ACCESS_KEY_ID=r["accessKeyId"], AWS_SECRET_ACCESS_KEY=r["secretAccessKey"],
                AWS_SESSION_TOKEN=r["sessionToken"], AWS_REGION="auto")


def endpoint(c):
    return f"https://{c['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"


def manifests():
    rows = {}
    for b in ("train", "validate", "test"):
        with open(os.path.join(REPO, "manifests", f"{b}.tsv"), newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                rows[r["path"]] = (r["sha256"], int(r["bytes_actual"]))
    return rows


def tracked():
    """Paths git tracks in this repository: the documents whose published copies follow it.
    The class folders can hold local image copies, which git ignores."""
    out = subprocess.run(["git", "-C", REPO, "ls-files", "-z"], capture_output=True, check=True).stdout
    return set(out.decode().split("\0")) - {""}


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


S5CMD_PART = 50 << 20  # s5cmd's default --part-size (MiB), which every put here uses


def etag_like(path, etag):
    """The local file's ETag in the form of `etag`: its MD5, or for a multipart ETag
    (`<md5>-<parts>`) the MD5 of each part's MD5 at s5cmd's part size."""
    if "-" not in etag:
        return md5(path)
    h = hashlib.md5()
    parts = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(S5CMD_PART), b""):
            h.update(hashlib.md5(block).digest())
            parts += 1
    return f"{h.hexdigest()}-{parts}"


def s5cmd(c, env, commands, check=True):
    with tempfile.NamedTemporaryFile("w", suffix=".s5", dir=os.path.expanduser("~/tmp"), delete=False) as f:
        f.write("\n".join(commands) + "\n")
        batch = f.name
    try:
        r = subprocess.run(["s5cmd", "--endpoint-url", endpoint(c), "--numworkers", "16", "run", batch],
                           env=env, capture_output=True, text=True)
    finally:
        os.remove(batch)
    if check and r.returncode != 0:
        raise SystemExit(f"s5cmd failed:\n{r.stderr[-4000:]}")
    return r.stdout


def cmd_plan(a, c):
    man = manifests()
    objs = listing(c, BUCKET, PREFIX)
    rows = []
    for path, (sha, size) in sorted(man.items()):
        local = os.path.join(a.staging, path)
        if not os.path.isfile(local) or os.path.getsize(local) != size:
            raise SystemExit(f"staged file missing or wrong size: {path}")
        key = PREFIX + path
        have = objs.get(key)
        if have is None or have[1] != etag_like(local, have[1]):
            rows.append(("put", key, size, md5(local), local))
    docs = tracked()
    for key, (size, etag) in sorted(objs.items()):
        rel = key[len(PREFIX):]
        if rel in man:
            continue
        if rel in docs:
            local = os.path.join(REPO, rel)
            m = md5(local)
            if m != etag:
                rows.append(("put", key, os.path.getsize(local), m, local))
        elif rel.startswith(KEEP):
            rows.append(("keep", key, size, etag, ""))
        else:
            rows.append(("delete", key, size, etag, ""))
    with open(a.out, "w") as f:
        f.write("action\tkey\tbytes\tmd5\tlocal\n")
        f.writelines("\t".join(map(str, r)) + "\n" for r in rows)
    puts = [r for r in rows if r[0] == "put"]
    dels = [r for r in rows if r[0] == "delete"]
    keeps = [r for r in rows if r[0] == "keep"]
    print(f"{len(objs)} objects now; {len(man)} manifest paths; put {len(puts)} "
          f"({sum(r[2] for r in puts) / 1e9:.2f} GB); delete {len(dels)} ({sum(r[2] for r in dels) / 1e9:.2f} GB); "
          f"keep {len(keeps)} -> {a.out}")


def cmd_checkpoint(a, c):
    sb, sp = a.src.split("/", 1)
    db, dp = a.dst.split("/", 1)
    src = listing(c, sb, sp)
    if listing(c, db, dp) and not a.resume:
        raise SystemExit(f"refusing: {a.dst} is not empty (--resume copies only what is missing)")
    # The root key: temporary credentials are scoped to one bucket, a copy spans two.
    env = dict(os.environ, AWS_ACCESS_KEY_ID=c["R2_ACCESS_KEY_ID"], AWS_SECRET_ACCESS_KEY=c["R2_SECRET_ACCESS_KEY"],
               AWS_REGION="auto")
    env.pop("AWS_SESSION_TOKEN", None)
    have = listing(c, db, dp)
    todo = [k for k in sorted(src) if have.get(dp + k[len(sp):], (None,))[0] != src[k][0]]
    # s5cmd's server-side copy sends a key with a space unencoded in x-amz-copy-source, which R2
    # answers with NoSuchKey (2026-10-16, 31 keys): those go through a local file instead.
    s5cmd(c, env, [f'cp "s3://{sb}/{k}" "s3://{db}/{dp}{k[len(sp):]}"' for k in todo if " " not in k])
    spaced = [k for k in todo if " " in k]
    if spaced:
        with tempfile.TemporaryDirectory(dir=os.path.expanduser("~/tmp")) as tmp:
            s5cmd(c, env, [f'cp "s3://{sb}/{k}" "{tmp}/{i}"' for i, k in enumerate(spaced)])
            s5cmd(c, env, [f'cp "{tmp}/{i}" "s3://{db}/{dp}{k[len(sp):]}"' for i, k in enumerate(spaced)])
    dst = listing(c, db, dp)
    # A copy must match its source in size, and in MD5 wherever both ETags are single-part MD5s.
    bad = []
    for k, (size, etag) in src.items():
        got = dst.get(dp + k[len(sp):])
        if got is None or got[0] != size or ("-" not in etag and "-" not in got[1] and got[1] != etag):
            bad.append(k)
    print(f"copied {len(todo)} objects ({len(spaced)} through a local file); {dp} holds {len(dst)} objects "
          f"({sum(v[0] for v in dst.values()) / 1e9:.2f} GB) for {len(src)} source objects; {len(bad)} mismatches")
    if bad:
        raise SystemExit(bad[:10])


def cmd_apply(a, c):
    if not a.owner_go:
        raise SystemExit("refusing: apply changes public objects; pass --owner-go once the owner said go")
    with open(a.plan) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    env = temp_env(c, BUCKET, "object-read-write", [PREFIX])
    puts = [r for r in rows if r["action"] == "put"]
    dels = [r for r in rows if r["action"] == "delete"]
    for r in puts:
        if md5(r["local"]) != r["md5"]:
            raise SystemExit(f"staged file changed since the plan: {r['local']}")
    cmds = []
    for r in puts:
        ctype = TYPES.get(os.path.splitext(r["key"])[1].lower(), "application/octet-stream")
        cmds.append(f'cp --content-type "{ctype}" "{r["local"]}" "s3://{BUCKET}/{r["key"]}"')
    if cmds:
        s5cmd(c, env, cmds)
    print(f"put {len(puts)}")
    if dels:
        s5cmd(c, env, [f'rm "s3://{BUCKET}/{r["key"]}"' for r in dels])
    print(f"deleted {len(dels)}")


def cmd_verify(a, c):
    man = manifests()
    objs = listing(c, BUCKET, PREFIX)
    keys = {k[len(PREFIX):] for k in objs}
    tracked_paths = tracked()
    docs = {k for k in keys - set(man) if k in tracked_paths}
    for k in sorted(docs):
        man[k] = (hashlib.sha256(open(os.path.join(REPO, k), "rb").read()).hexdigest(),
                  os.path.getsize(os.path.join(REPO, k)))
    extra = sorted(k for k in keys - set(man) if not k.startswith(KEEP))
    missing = sorted(set(man) - keys)
    bad = []
    for path, (sha, size) in sorted(man.items()):
        if path in missing:
            continue
        url = "https://codec-corpus.r2.imazen.org/" + urllib.parse.quote(PREFIX + path)
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        h = hashlib.sha256()
        n = 0
        with urllib.request.urlopen(req) as resp:
            for block in iter(lambda: resp.read(1 << 20), b""):
                h.update(block)
                n += len(block)
        if h.hexdigest() != sha or n != size:
            bad.append(path)
    print(f"{len(objs)} objects; extra {len(extra)}; missing {len(missing)}; sha256/size mismatches {len(bad)}")
    for p in (extra + missing + bad)[:20]:
        print("  ", p)
    sys.exit(1 if extra or missing or bad else 0)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("staging"); p.add_argument("--out", default="r2_plan.tsv")
    p = sub.add_parser("checkpoint"); p.add_argument("src"); p.add_argument("dst")
    p.add_argument("--resume", action="store_true")
    p = sub.add_parser("apply"); p.add_argument("plan"); p.add_argument("--owner-go", action="store_true")
    sub.add_parser("verify")
    a = ap.parse_args()
    c = creds()
    {"plan": cmd_plan, "checkpoint": cmd_checkpoint, "apply": cmd_apply, "verify": cmd_verify}[a.cmd](a, c)


if __name__ == "__main__":
    main()
