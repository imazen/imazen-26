#!/usr/bin/env python3
"""Compatibility census of a render v4 output: every distinct file of the PNG and JPEG XL layers
through the reader images of the compat matrix (Ubuntu LTS packages, a rolling distribution,
headless browsers), each reader's decode hashed and compared with ours (EXPORT-PLAN.md, "Gates").
The browsers run scripts/census_browser_batch.mjs: the adapter's canvas decode, with the file
served over loopback HTTP instead of a data: URL and one browser launch per chunk.

    render_v4_compat_census.py <render-dir> [--jobs 4] [--chunk 10] [--mem-budget 16] [--ids 11064,...]
                               [--outdir DIR]

The readers are the compat matrix's adapters (`/opt/adapters/<reader> <in> <out.png> <out.json>`)
in the images imazen26-compat:lts, :latest and :browsers, built from
../imazen-26--compat-matrix/tools/compat-matrix/docker (now imazen/image-compat). Each runs in a
container with no network, a read-only root, a disk-backed /tmp and capped CPU and memory, over
a chunk of files; the adapter decodes with the reader's plain path and writes the bitmap as PNG.
`tools/jxl-decode-check compare` then hashes every output (XXH3 of its own layout and of 8-bit
RGBA) and compares it with our decode of the file (zenpng or zenjxl) and, for a wide-gamut
file, with our decode of its sRGB twin, which is what a colour-managed reader should show.

Files with the same bytes in two layers are read once. Chunks hold at most --chunk files and
60 MP, and wait while the work disk has under 25 GB free. Writes under <render-dir>/compat-census/:
census.tsv (one row per file and reader; a rerun skips files it has), done.txt (finished chunks),
memory.tsv (each container's cap and peak), images.tsv (the reader images' ids) and summary.txt;
RUN.meta gets the results unless --outdir points elsewhere (a trial run).

Memory: each container gets a cap sized to the chunk's largest file, with no swap, and the caps
of the running containers plus the compare steps' estimates stay within --mem-budget GB. At the
cap the kernel kills the decoding process, the container's loop records the failure when the
adapter could not, and the files after it still run; a file the batch container left without a
result is run again in a container of its own. (On 2026-10-17, 12 containers of 8 GB each with docker's default swap allowance, as
much again, ran the host out of memory: Ubuntu 24.04's ffmpeg grows to the cap on JPEG XL files.)
"""
import argparse
import collections
import concurrent.futures
import contextlib
import csv
import itertools
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "jxl-decode-check", "target", "release", "jxl-decode-check")
LIBS = ("vips", "imagemagick", "pillow", "graphicsmagick", "gdkpixbuf", "opencv", "qt", "ffmpeg")
READERS = {
    "png": [("lts", r, ()) for r in ("pngtopam",) + LIBS] + [("latest", r, ()) for r in ("pngtopam",) + LIBS],
    "jxl": [("lts", r, ()) for r in ("djxl",) + LIBS] + [("latest", r, ()) for r in ("djxl",) + LIBS],
}
for fmt in READERS:
    READERS[fmt] += [("browsers", "browser", (engine, "canvas")) for engine in ("chromium", "firefox", "webkit")]
COLUMNS = ["sha256", "layer", "path", "image", "reader", "version", "status", "ms", "width", "height",
           "channels", "bits", "xxh3", "rgba8_xxh3", "same", "max_diff", "mean_diff", "diff_pixels",
           "srgb_twin_same", "srgb_twin_max_diff", "error"]


def role_name(image, reader, args):
    return "-".join([image, reader] + [a for a in args if a != "canvas"])


def distinct_files(render, ids):
    """sha256 -> (layer, path, alternate reference or ''), first path per sha; plus every path.
    The alternate reference of a wide-gamut file is its sRGB twin, or for a JPEG-in-JXL file
    `=srgb:<colour>`: our decode of the file converted to sRGB by `jxl-decode-check compare`,
    because the twin comes from the PNG layer, another decode of the JPEG."""
    rows, pixels = {}, {}
    for layer in ("png-p3", "png-srgb", "jxl-p3", "jxl-srgb"):
        with open(os.path.join(render, "manifests", f"{layer}.tsv"), newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if ids and r["id"] not in ids:
                    continue
                rows[r["path"]] = (layer, r["sha256"], r["form"], r["colour"])  # the path starts with the layer
                pixels[r["sha256"]] = int(r["width"]) * int(r["height"])
    files, alias = {}, {}
    for path, (layer, sha, form, colour) in sorted(rows.items()):
        alias.setdefault(sha, []).append(path)
        if sha in files:
            continue
        alt = ""
        if layer.endswith("-p3"):
            twin = path.replace("-p3/", "-srgb/", 1)
            if twin in rows and rows[twin][1] != sha:
                alt = f"=srgb:{colour}" if form.startswith("jpeg-in-jxl") else twin
        files[sha] = (layer, path, alt)
    return files, alias, pixels


class MemoryBudget:
    """Reservations of GB against a total, granted in arrival order (a large one is not starved
    by small ones behind it); one larger than the total waits until it can run alone."""

    def __init__(self, total):
        self.total, self.used, self.queue = total, 0, collections.deque()
        self.cond = threading.Condition()

    @contextlib.contextmanager
    def hold(self, gb):
        gb = min(gb, self.total)
        me = object()
        with self.cond:
            self.queue.append(me)
            self.cond.wait_for(lambda: self.queue[0] is me and self.used + gb <= self.total)
            self.queue.popleft()
            self.used += gb
            self.cond.notify_all()
        try:
            yield gb
        finally:
            with self.cond:
                self.used -= gb
                self.cond.notify_all()


def container_gb(max_px, browser):
    """A reader container's memory cap, in half GB. Measured on 12 MP files (memory.tsv): the
    libraries peak at 0.6-0.75 GB (the adapter's statistics pass holds the output as numpy
    float64, 48 bytes a pixel), the browsers at up to 1.25 GB."""
    gb = 1.5 + 80e-9 * max_px if browser else 0.5 + 64e-9 * max_px
    return min(14, max(1, math.ceil(gb * 2) / 2))


def compare_gb(pxs):
    """`jxl-decode-check compare --jobs 4` holds our decode, its 8-bit copy, the sRGB twin's and
    the output's for up to four files at once."""
    return math.ceil(0.5 + 48e-9 * sum(sorted(pxs)[-4:]))


NAMES = itertools.count()
KILLS = "sed -n 's/^oom_kill //p' /sys/fs/cgroup/memory.events"


def run_role(render, rdir, image, reader, args, entries, gb, images, budget):
    """One container of the reader over entries [(i, path)]: (peak bytes, OOM kills, rc, seconds)."""
    tmp = rdir + ".tmp"
    os.makedirs(tmp, exist_ok=True)
    with open(os.path.join(rdir, "list.tsv"), "w") as f:
        f.writelines(f"{i}\t/r/{path}\n" for i, path in entries)
    if reader == "browser":
        # One browser launch per chunk (scripts/census_browser_batch.mjs): the adapter's
        # canvas decode over loopback HTTP, without a launch per file.
        script = f"node /x/census_browser_batch.mjs {args[0]} /o/list.tsv /o >/dev/null 2>&1"
    else:
        # The kernel kills the largest process at the cap, never this loop: an adapter it killed
        # (bash buffers the reader's stderr) gets its record here, and the next file runs.
        script = ('while IFS=$(printf "\\t") read -r i p; do '
                  f'k0=$({KILLS}); /opt/adapters/{reader} "$p" "/o/$i.png" "/o/$i.json" >/dev/null 2>&1; '
                  f'rc=$?; k1=$({KILLS}); [ -s "/o/$i.json" ] || printf \'{{"status":"crash","error_head":'
                  f'"the adapter exited %s without a result; %s processes killed at the {gb} GB memory cap"}}\\n\' '
                  '"$rc" "$((k1 - k0))" > "/o/$i.json"; done < /o/list.tsv')
    script += f"; {{ cat /sys/fs/cgroup/memory.peak; {KILLS}; }} > /o/memory.txt 2>/dev/null"
    name = f"cm-census-{os.getpid()}-{next(NAMES)}"
    cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", "--read-only",
           "-v", f"{tmp}:/tmp", "-e", "HOME=/tmp", "--user", f"{os.getuid()}:{os.getgid()}",
           "-e", f"CM_IMAGE_ID={images[image]}", "--pids-limit", "2048", "--cpus", "2",
           "--memory", f"{gb}g", "--memory-swap", f"{gb}g", "-v", f"{render}:/r:ro",
           "-v", f"{os.path.join(REPO, 'scripts')}:/x:ro",
           "-v", f"{rdir}:/o", "--entrypoint", "/usr/bin/nice", f"imazen26-compat:{image}",
           "-n", "19", "/bin/bash", "-c", script]
    with budget.hold(gb):
        t0 = time.time()
        try:
            rc = subprocess.run(cmd, capture_output=True, timeout=7200).returncode
        except subprocess.TimeoutExpired:  # the client's timeout doesn't stop the container
            subprocess.run(["docker", "kill", name], capture_output=True)
            rc = "timeout"
    shutil.rmtree(tmp, ignore_errors=True)
    secs = f"{time.time() - t0:.0f}"
    try:
        peak, kills = open(os.path.join(rdir, "memory.txt")).read().split()
        os.remove(os.path.join(rdir, "memory.txt"))
    except (OSError, ValueError):
        peak, kills = "", ""
    return peak, kills, rc, secs


def run_chunk(render, work, n, chunk, images, out_lock, out_file, pixels, budget):
    # Readers' outputs share the disk with everything else: wait for room before starting.
    while shutil.disk_usage(work).free < 25e9:
        time.sleep(30)
    cdir = os.path.join(work, f"chunk-{n:05d}")
    shutil.rmtree(cdir, ignore_errors=True)
    os.makedirs(cdir)
    fmt = "jxl" if chunk[0][1][1].endswith(".jxl") else "png"
    entries = [(i, path) for i, (sha, (layer, path, alt)) in enumerate(chunk)]
    max_px = max(pixels[sha] for sha, _ in chunk)
    memory = []
    for image, reader, args in READERS[fmt]:
        role = role_name(image, reader, args)
        rdir = os.path.join(cdir, role)
        os.makedirs(rdir)
        gb = container_gb(max_px, reader == "browser")
        peak, kills, rc, secs = run_role(render, rdir, image, reader, args, entries, gb, images, budget)
        memory.append([n, role, "batch", len(entries), f"{max_px / 1e6:.1f}", gb, peak, kills, rc, secs])
        # A file the batch left without a result (the container died, or a browser took the
        # rest with it) runs again alone, in a fresh container.
        for i, path in entries:
            if not os.path.exists(os.path.join(rdir, f"{i}.json")):
                one = os.path.join(rdir, f"single-{i}")
                os.makedirs(one)
                peak, kills, rc, secs = run_role(render, one, image, reader, args, [(i, path)], gb, images, budget)
                memory.append([n, role, f"single-{i}", 1, f"{pixels[chunk[i][0]] / 1e6:.1f}", gb, peak, kills, rc, secs])
                for ext in ("json", "png"):
                    if os.path.exists(os.path.join(one, f"{i}.{ext}")):
                        os.replace(os.path.join(one, f"{i}.{ext}"), os.path.join(rdir, f"{i}.{ext}"))
                if not os.path.exists(os.path.join(rdir, f"{i}.json")):
                    with open(os.path.join(rdir, f"{i}.json"), "w") as f:
                        killed = f", killed at the container's {gb} GB memory cap" if kills not in ("", "0") else ""
                        json.dump({"status": "crash", "error_head": f"no json: container exit {rc}{killed}"}, f)
                shutil.rmtree(one, ignore_errors=True)
    # Compare every output with our decode of its file (and of the sRGB twin).
    lines, cells = [], []
    for image, reader, args in READERS[fmt]:
        role = role_name(image, reader, args)
        for i, (sha, (layer, path, alt)) in enumerate(chunk):
            png = os.path.join(cdir, role, f"{i}.png")
            meta = {}
            try:
                meta = json.load(open(os.path.join(cdir, role, f"{i}.json")))
            except (OSError, ValueError):
                meta = {"status": "crash", "error_head": "no json"}
            cells.append((sha, layer, path, image, reader if not args else f"{reader}-{args[0]}", meta, png))
            if meta.get("status") == "ok" and os.path.exists(png):
                ref = alt if alt.startswith("=") or not alt else f"{render}/{alt}"
                lines.append(f"{render}/{path}\t{png}\t{ref}\n")
    cmp_in = os.path.join(cdir, "compare.in")
    with open(cmp_in, "w") as f:
        f.writelines(lines)
    with budget.hold(compare_gb([pixels[sha] for sha, _ in chunk])):
        res = subprocess.run([TOOL, "compare", "--jobs", "4"], stdin=open(cmp_in), capture_output=True, text=True)
    compared = {}
    for row in csv.DictReader(res.stdout.splitlines(), delimiter="\t"):
        compared[row["output"]] = row
    rows = []
    for sha, layer, path, image, reader, meta, png in cells:
        c = compared.get(png, {})
        status = meta.get("status", "crash")
        error = str(meta.get("error_head", "")).replace("\t", " ")[:300]
        if status == "ok" and c.get("status") != "ok":
            status, error = "unreadable-output", (c.get("error") or "no compare row")[:300]
        rows.append([sha, layer, path, image, reader, str(meta.get("version", "")).replace("\t", " ")[:80],
                     status, str(meta.get("ms", "")), c.get("width", ""), c.get("height", ""),
                     c.get("channels", ""), c.get("bits", ""), c.get("xxh3", ""), c.get("rgba8_xxh3", ""),
                     c.get("same", ""), c.get("max_diff", ""), c.get("mean_diff", ""), c.get("diff_pixels", ""),
                     c.get("alt_same", ""), c.get("alt_max_diff", ""), error])
    with out_lock:
        with open(out_file, "a") as f:
            f.writelines("\t".join(r) + "\n" for r in rows)
        with open(os.path.join(os.path.dirname(out_file), "memory.tsv"), "a") as f:
            f.writelines("\t".join(map(str, m)) + "\n" for m in memory)
        with open(os.path.join(os.path.dirname(out_file), "done.txt"), "a") as f:
            f.write(f"{n}\n")
    shutil.rmtree(cdir, ignore_errors=True)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("render")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--chunk", type=int, default=10)
    ap.add_argument("--mem-budget", type=int, default=16,
                    help="GB for the running containers' caps and the compare steps together")
    ap.add_argument("--ids", default="")
    ap.add_argument("--work", default=os.path.expanduser("~/tmp/compat-census"))
    ap.add_argument("--outdir", default="", help="default <render-dir>/compat-census")
    a = ap.parse_args()
    render = os.path.abspath(a.render)
    ids = {i for i in a.ids.split(",") if i}
    files, alias, pixels = distinct_files(render, ids)
    images = {}
    for t in ("lts", "latest", "browsers"):
        images[t] = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", f"imazen26-compat:{t}"],
                                   capture_output=True, text=True, check=True).stdout.strip()
    outdir = a.outdir or os.path.join(render, "compat-census")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "images.tsv"), "w") as f:
        f.writelines(f"{t}\t{i}\n" for t, i in images.items())
    out_file = os.path.join(outdir, "census.tsv")
    if not os.path.exists(out_file):
        with open(out_file, "w") as f:
            f.write("\t".join(COLUMNS) + "\n")
    if not os.path.exists(os.path.join(outdir, "memory.tsv")):
        with open(os.path.join(outdir, "memory.tsv"), "w") as f:
            f.write("chunk\trole\tpass\tfiles\tmax_mp\tcap_gb\tpeak_bytes\toom_kills\texit\tseconds\n")
    # A chunk appends all its rows at once, so a file with rows is done (a rerun resumes).
    with open(out_file, newline="") as f:
        done = {r["sha256"] for r in csv.DictReader(f, delimiter="\t")}
    # Chunks of one format, PNG first, of at most --chunk files and 60 MP: every reader's output
    # of a chunk stays on disk until the chunk is compared.
    items = sorted(((sha, v) for sha, v in files.items() if sha not in done),
                   key=lambda kv: (kv[1][1].endswith(".jxl"), kv[1][1]))
    chunks, cur, mp = [], [], 0
    for kv in items:
        px = pixels[kv[0]]
        if cur and (len(cur) == a.chunk or mp + px > 60e6 or cur[0][1][1].endswith(".jxl") != kv[1][1].endswith(".jxl")):
            chunks.append(cur)
            cur, mp = [], 0
        cur.append(kv)
        mp += px
    if cur:
        chunks.append(cur)
    first = 1 + max([int(x) for x in open(os.path.join(outdir, "done.txt")).read().split()] or [-1]) \
        if os.path.exists(os.path.join(outdir, "done.txt")) else 0
    todo = [(first + n, c) for n, c in enumerate(chunks)]
    print(f"{len(files)} distinct files ({sum(len(v) for v in alias.values())} paths); {len(done)} done; "
          f"{len(todo)} chunks to run", file=sys.stderr, flush=True)
    os.makedirs(a.work, exist_ok=True)
    lock = threading.Lock()
    budget = MemoryBudget(a.mem_budget)
    t0 = time.time()
    finished = 0
    with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:
        futs = {pool.submit(run_chunk, render, a.work, n, c, images, lock, out_file, pixels, budget): n
                for n, c in todo}
        for fut in concurrent.futures.as_completed(futs):
            finished += 1
            try:
                rows = fut.result()
            except Exception as e:  # a chunk that failed stays out of done.txt and reruns
                print(f"chunk {futs[fut]} failed: {e}", file=sys.stderr, flush=True)
                continue
            el = time.time() - t0
            print(f"{finished}/{len(todo)} chunks ({rows} cells in chunk {futs[fut]}), {el / 60:.1f} min, "
                  f"eta {el / finished * (len(todo) - finished) / 60:.0f} min, {budget.used}/{budget.total} GB held",
                  file=sys.stderr, flush=True)
    # --ids limits decoding, while the review still needs aliases for the entire corpus.
    if ids:
        _, alias, _ = distinct_files(render, set())
    with open(os.path.join(outdir, "aliases.tsv"), "w") as f:
        f.write("sha256\tpath\n")
        f.writelines(f"{sha}\t{p}\n" for sha, ps in sorted(alias.items()) for p in ps)
    summarize(render, outdir, images, write_meta=not a.outdir)


def summarize(render, outdir, images, write_meta=True):
    """summary.txt (per reader and format: decoded, equal to ours, errors) and RUN.meta lines."""
    with open(os.path.join(outdir, "census.tsv"), newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    per = {}
    for r in rows:
        k = (r["image"], r["reader"], "jxl" if r["path"].endswith(".jxl") else "png")
        c = per.setdefault(k, {"n": 0, "ok": 0, "same": 0, "close": 0, "versions": set()})
        c["n"] += 1
        c["ok"] += r["status"] == "ok"
        c["same"] += r["same"] in ("native", "rgba8")
        c["close"] += r["same"] == "no" and r["max_diff"] != "" and int(r["max_diff"]) <= 1
        c["versions"].add(r["version"][:60])
    lines = [f"{len(rows)} decodes of {len({r['sha256'] for r in rows})} distinct files by {len({k[:2] for k in per})} readers"]
    for (image, reader, fmt), c in sorted(per.items()):
        lines.append(f"{image} {reader} {fmt}: {c['ok']} of {c['n']} decoded, {c['same']} equal to ours, "
                     f"{c['close']} within 1 code value; {' | '.join(sorted(c['versions']))}")
    open(os.path.join(outdir, "summary.txt"), "w").write("\n".join(lines) + "\n")
    if not write_meta:
        return
    tools = ["scripts/render_v4_compat_census.py", "scripts/census_browser_batch.mjs", "tools/jxl-decode-check"]
    commit = subprocess.run(["git", "-C", REPO, "log", "-1", "--format=%H", "--"] + tools, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", REPO, "status", "--porcelain", "--"] + tools, capture_output=True, text=True).stdout
    with open(os.path.join(render, "RUN.meta"), "a") as f:
        f.write(f"census_date\t{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
        f.write(f"census_tool_commit\t{commit}\n")
        f.write(f"census_tool_dirty\t{len(dirty.splitlines())}\n")
        for t, i in images.items():
            f.write(f"census_image_{t}\t{i}\n")
        f.writelines(f"census_summary\t{l}\n" for l in lines)


if __name__ == "__main__":
    main()
