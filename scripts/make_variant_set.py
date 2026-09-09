#!/usr/bin/env python3
"""make_variant_set.py — the ONE entrypoint for generating imazen-26 variant sets.

Implements VARIANTS-SPEC v2: selection via the measured procedures, sizes from the
canonical candidate grid, the 11-unit crop vocabulary, recorded kernels, and a
mandatory variants.tsv — and every run emits a registry entry under variant-sets/
so sets are born versioned.

Selection modes (choose one):
  --select all                      every in-split corpus image (use --split)
  --select reps  --reps-tsv X       a k-means representative manifest
                                    (image_path, crop_label, ... — krep-* schema)
  --select fps   --fps-tsv X --budget-gp B
                                    a farthest-point-sampling priority manifest
                                    (rank, cumulative_gp, image_path, scale_w,
                                    scale_h, ... — renders exactly the <=B prefix)

Sizes (ignored for --select fps, which carries its own targets):
  --preset picker11 | tiers4 | thumb     or --sizes 64,128,256  (must be rungs of
  the canonical grid; longest-side, downscale-only)

Crops: --crops none|c50|c25|both  (anchors center,tl,tr,bl,br at the fraction of
min-dimension; crop happens at native resolution, then the ladder applies)

Kernel: --kernel lanczos (PIL, gamma-space, the built-in path)
        --kernel mitchell|mitchell-sharp requires --renderer-cmd
        'CMD {src} {w} {h} {dst}' (e.g. a zenresize wrapper) — the tool refuses to
        fake kernels it cannot produce. HDR/linear-light also requires a renderer.

Deps: Pillow (the lanczos path). Some corpus sources are native .heic — install
      `pillow-heif` too (auto-registered if present, silently skipped if not,
      Image.open raises UnidentifiedImageError on a .heic source if missing).

Example (the jxl-ablation gap):
  ./scripts/make_variant_set.py --set-id jxlp0-ladder@2026-08-23 \
      --select reps --reps-tsv manifests/imazen26_representatives_K500_2026-06-14.tsv \
      --split train --preset picker11 --crops none --kernel lanczos \
      --images-root . --out /mnt/v/output/imazen-26-variants/jxlp0-ladder-2026-08-23
"""

import argparse
import csv
import hashlib
import os
import shlex
import subprocess
import sys

GRID = [32, 40, 48, 64, 80, 96, 128, 160, 192, 256, 320, 384, 512, 640, 768,
        896, 1024, 1280, 1536, 2048, 3072, 4096]
PRESETS = {
    "picker11": [64, 96, 128, 192, 256, 384, 512, 640, 768, 896, 1024],
    "tiers4": [128, 384, 768, 2048],
    "thumb": [128],
}
ANCHORS = ("center", "tl", "tr", "bl", "br")
SPLIT_OF = {0: "train", 2: "train", 4: "train", 6: "train", 8: "train",
            1: "validate", 3: "validate", 5: "validate", 7: "test", 9: "test"}
V2_COLS = ["origin_id", "origin_sha256", "op_chain", "kernel", "sharpen",
           "colorspace_path", "selection_method", "selection_param", "rank",
           "cumulative_gp", "generator", "generator_commit", "out_path",
           "out_sha256", "width", "height", "split"]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def leading_id(name):
    base = os.path.basename(name)
    tok = base.split("_")[0].split(".")[0]
    return tok if tok.isdigit() and len(tok) == 4 else None


def git_commit(root):
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def png_dims(p):
    """(width, height) from a PNG IHDR — no image library needed."""
    with open(p, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))


def crop_rect(w, h, label):
    if label == "full":
        return None
    kind, anchor = label.split("_", 1) if "_" in label else (label, "center")
    frac = 0.5 if kind == "c50" else 0.25
    side = max(1, int(min(w, h) * frac))
    pos = {"center": ((w - side) // 2, (h - side) // 2), "tl": (0, 0),
           "tr": (w - side, 0), "bl": (0, h - side), "br": (w - side, h - side)}
    x, y = pos[anchor]
    return (x, y, side, side)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set-id", required=True, help="<name>@<YYYY-MM-DD>")
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus-root", default=".")
    ap.add_argument("--images-root", default=None,
                    help="where class dirs hold bytes (default: corpus root)")
    ap.add_argument("--select", choices=["all", "reps", "fps", "list"], required=True)
    ap.add_argument("--list-file",
                    help="--select list: one source path per line, relative to "
                         "--images-root. For deriving a set from an existing "
                         "rendition layer (e.g. the 16-bit HDR renders) rather "
                         "than from corpus originals — those files are not in "
                         "CORPUS-MANIFEST, so their dimensions are read from the "
                         "PNG header and the origin id from the leading integer.")
    ap.add_argument("--reps-tsv")
    ap.add_argument("--fps-tsv")
    ap.add_argument("--budget-gp", type=float)
    ap.add_argument("--split", choices=["train", "validate", "test", "any"],
                    default="train")
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--sizes")
    ap.add_argument("--crops", choices=["none", "c50", "c25", "both"], default="none")
    ap.add_argument("--ratio", type=int,
                    help="fixed 1/N downscale instead of grid rungs. The candidate "
                         "grid (spec v2 s2) is longest-side and explicitly "
                         "'joinability, not a mandate'; an artifact-removal set is "
                         "defined by a RATIO to the source's block grid, not by a "
                         "rung, so it cannot use one. Emitted names stay grammar-"
                         "compliant (.scale<W>x<H>) and the ratio is recorded as "
                         "selection_param. Sources are cropped to a whole multiple "
                         "of N first (a partial MCU cannot have its AC cancelled).")
    ap.add_argument("--sources", choices=["all", "lossy"], default="all",
                    help="'lossy' keeps only jpg/jpeg/heic origins — the ones that "
                         "actually carry codec artifacts to remove.")
    ap.add_argument("--colorspace-path", default=None,
                    help="recorded verbatim in variants.tsv. Required with "
                         "--renderer-cmd: the generator cannot inspect what an "
                         "external renderer did, and guessing it would put an "
                         "unverified claim in the manifest.")
    ap.add_argument("--kernel", choices=["lanczos", "mitchell", "mitchell-sharp", "box"],
                    default="lanczos")
    ap.add_argument("--renderer-cmd",
                    help="external renderer: 'CMD {src} {w} {h} {dst}' (required "
                         "for non-lanczos kernels / linear-light paths)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = a.corpus_root.rstrip("/")
    images = (a.images_root or root).rstrip("/")
    if "@" not in a.set_id:
        sys.exit("--set-id must be <name>@<date>")
    if a.renderer_cmd and not a.colorspace_path:
        sys.exit("--renderer-cmd needs --colorspace-path (e.g. linear-light); the "
                 "generator will not record a colorspace it did not perform")
    if a.ratio is not None:
        if a.ratio < 2:
            sys.exit("--ratio must be >= 2")
        if a.preset or a.sizes:
            sys.exit("--ratio replaces --preset/--sizes; pass one or the other")
        if a.select == "fps":
            sys.exit("--select fps carries its own per-unit targets; --ratio conflicts")
    if a.kernel != "lanczos" and not a.renderer_cmd:
        sys.exit(f"--kernel {a.kernel} needs --renderer-cmd (PIL cannot produce it; "
                 "the tool does not fake kernels)")

    # id -> (class-relative path, native w, h) from the membership oracle
    with open(os.path.join(root, "CORPUS-MANIFEST.tsv"), newline="") as f:
        cm = {r["number"]: (r["path"], int(r["width"]), int(r["height"]))
              for r in csv.DictReader(f, delimiter="\t")}

    def unit_from(pathlike, crop_label):
        oid = leading_id(pathlike)
        if a.select == "list":
            # A rendition layer, not a corpus original: the path IS the source and
            # its dimensions are its own. The id still has to resolve, because the
            # split is inherited from it.
            if not oid or oid not in cm:
                sys.exit(f"cannot map to a corpus id: {pathlike}")
            w, h = png_dims(os.path.join(images, pathlike))
            if not w:
                sys.exit(f"not a readable PNG: {pathlike}")
            return (pathlike, crop_label, w, h)
        if not oid or oid not in cm:
            sys.exit(f"cannot map to a corpus id: {pathlike}")
        p, w, h = cm[oid]
        return (p, crop_label, w, h)

    if a.select == "fps":
        if not (a.fps_tsv and a.budget_gp):
            sys.exit("--select fps needs --fps-tsv and --budget-gp")
        with open(a.fps_tsv, newline="") as f:
            rows = [r for r in csv.DictReader(f, delimiter="\t")
                    if float(r["cumulative_gp"]) <= a.budget_gp]
        units = [unit_from(r["image_path"], "full") +
                 (int(r["scale_w"]), int(r["scale_h"]), r["rank"], r["cumulative_gp"])
                 for r in rows]
        sel_method, sel_param = "fps", f"{a.budget_gp}GP"
        sizes = None
    else:
        if a.ratio:
            sizes = None  # per-source, derived from the ratio below
        elif a.sizes:
            sizes = [int(x) for x in a.sizes.split(",")]
        elif a.preset:
            sizes = PRESETS[a.preset]
        else:
            sys.exit("--select all/reps needs --preset, --sizes or --ratio")
        if sizes is not None:
            off_grid = [s for s in sizes if s not in GRID]
            if off_grid:
                sys.exit(f"sizes {off_grid} are not rungs of the canonical grid {GRID}")
        if a.select == "list":
            if not a.list_file:
                sys.exit("--select list needs --list-file")
            src = [(l.strip(), "full") for l in open(a.list_file) if l.strip()]
            sel_method, sel_param = "list", os.path.basename(a.list_file)
        elif a.select == "reps":
            if not a.reps_tsv:
                sys.exit("--select reps needs --reps-tsv")
            with open(a.reps_tsv, newline="") as f:
                src = [(r.get("image_path") or r["url"], r.get("crop_label", "full"))
                       for r in csv.DictReader(f, delimiter="\t")]
            sel_method, sel_param = "kmeans", os.path.basename(a.reps_tsv)
        else:
            with open(os.path.join(root, "CORPUS-MANIFEST.tsv"), newline="") as f:
                rows_all = list(csv.DictReader(f, delimiter="\t"))
            if a.sources == "lossy":
                rows_all = [r for r in rows_all
                            if r["format"].lower() in ("jpg", "jpeg", "heic")]
            src = [(r["path"], "full") for r in rows_all]
            sel_method, sel_param = "all", a.split
        if a.crops != "none":
            kinds = {"c50": ["c50"], "c25": ["c25"], "both": ["c50", "c25"]}[a.crops]
            src = [(p, "full") for p, _ in src] + \
                  [(p, f"{k}_{an}") for p, _ in src for k in kinds for an in ANCHORS]
        units = [unit_from(p, cl) + (None, None, "", "") for p, cl in src]

    if a.split != "any":
        units = [u for u in units
                 if SPLIT_OF[int(leading_id(u[0])) % 10] == a.split]
    if not units:
        sys.exit("selection is empty after split filtering")

    Image = None
    if not a.dry_run and not a.renderer_cmd:
        from PIL import Image  # only the built-in lanczos path needs pillow
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()  # corpus has native .heic sources; PIL can't open them otherwise
        except ImportError:
            pass  # fine unless a selected source is actually HEIC — Image.open will then say so
    os.makedirs(a.out, exist_ok=True)
    gen_commit = git_commit(root)
    out_rows, total_px = [], 0
    for (path, crop_label, nat_w, nat_h, tw, th, rank, cgp) in units:
        src_path = os.path.join(images, path)
        if not a.dry_run and not os.path.isfile(src_path):
            sys.exit(f"missing source: {src_path}")
        oid = leading_id(path) or "0000"
        stem = os.path.splitext(os.path.basename(path))[0]
        origin_sha = sha256_file(src_path) if os.path.isfile(src_path) else ""
        ops = []
        cw, ch = nat_w, nat_h
        rect = None
        if crop_label != "full":
            rect = crop_rect(nat_w, nat_h, crop_label)
            cw, ch = rect[2], rect[3]
            ops.append(f"crop{rect[0]}.{rect[1]}.{rect[2]}.{rect[3]}")
        if a.ratio:
            # Whole blocks only: crop to a multiple of N, then divide. The
            # discarded edge is at most N-1 px per axis and is exactly where
            # partial-MCU artifacts live.
            bw, bh = (cw // a.ratio) * a.ratio, (ch // a.ratio) * a.ratio
            targets = ([(bw // a.ratio, bh // a.ratio)] if bw and bh else [])
            if not targets:
                sys.exit(f"{path}: {cw}x{ch} is smaller than one "
                         f"{a.ratio}x{a.ratio} block")
        elif tw:
            targets = [(tw, th)]
        else:
            targets = [(max(1, round(cw * s / max(cw, ch))),
                        max(1, round(ch * s / max(cw, ch))))
                       for s in sizes if s <= max(cw, ch)]
        if True:
            for (w, h) in targets:
                op_chain = ".".join(ops + [f"scale{w}x{h}"])
                out_name = f"{stem}.{op_chain}.png"
                dst = os.path.join(a.out, out_name)
                if not a.dry_run and not os.path.exists(dst):
                    if a.renderer_cmd:
                        cmd = [t.format(src=src_path, w=w, h=h, dst=dst,
                                        cx=rect[0] if rect else 0,
                                        cy=rect[1] if rect else 0,
                                        cw=cw, ch=ch)
                               for t in shlex.split(a.renderer_cmd)]
                        subprocess.run(cmd, check=True)
                    else:
                        with Image.open(src_path) as im:
                            im = im.convert("RGB")
                            if rect:
                                im = im.crop((rect[0], rect[1],
                                              rect[0] + rect[2], rect[1] + rect[3]))
                            im.resize((w, h), Image.LANCZOS).save(dst)
                # An external renderer that disagrees with the recorded target
                # would put wrong dimensions in the manifest silently. Read them
                # back from the PNG header (IHDR is fixed-offset) and fail loud.
                if not a.dry_run:
                    got = png_dims(dst)
                    if got != (w, h):
                        sys.exit(f"{dst}: renderer wrote {got[0]}x{got[1]}, "
                                 f"manifest says {w}x{h} — refusing to record it")
                total_px += w * h
                out_rows.append({
                    "origin_id": oid, "origin_sha256": origin_sha,
                    "op_chain": op_chain, "kernel": a.kernel,
                    "sharpen": "1" if a.kernel.endswith("sharp") else "0",
                    "colorspace_path": a.colorspace_path or "gamma-srgb",
                    "selection_method": sel_method,
                    "selection_param": (f"1/{a.ratio}" if a.ratio else sel_param),
                    "rank": rank, "cumulative_gp": cgp,
                    "generator": "make_variant_set.py", "generator_commit": gen_commit,
                    "out_path": out_name,
                    "out_sha256": "" if a.dry_run else sha256_file(dst),
                    "width": w, "height": h,
                    "split": SPLIT_OF[int(oid) % 10]})

    vt = os.path.join(a.out, "variants.tsv")
    with open(vt, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=V2_COLS, delimiter="\t", lineterminator="\n")
        wtr.writeheader()
        [wtr.writerow(r) for r in out_rows]

    reg = os.path.join(root, "variant-sets", a.set_id)
    os.makedirs(reg, exist_ok=True)
    with open(os.path.join(reg, "files.tsv"), "w", newline="") as f:
        f.write("file\tsha256\tbytes\twidth\theight\n")
        for r in out_rows:
            p = os.path.join(a.out, r["out_path"])
            sz = "" if a.dry_run else str(os.path.getsize(p))
            f.write(f"{r['out_path']}\t{r['out_sha256']}\t{sz}\t{r['width']}\t{r['height']}\n")
    setmd = os.path.join(reg, "SET.md")
    if not os.path.exists(setmd):
        with open(setmd, "w") as f:
            f.write(f"""# {a.set_id}

- **Files:** {len(out_rows)} renditions, {total_px / 1e9:.3f} GP total.
- **Selection:** {sel_method} ({sel_param}); split={a.split}; crops={a.crops}.
- **Render:** kernel={a.kernel}, generator=make_variant_set.py@{gen_commit}.
- **Storage:** {a.out} (register mirrors here when synced).
- **Consumers:** (fill in as projects adopt this set)
- **Status:** active.
""")
    print(f"{a.set_id}: {len(out_rows)} renditions, {total_px/1e9:.3f} GP -> {a.out}")
    print(f"registry: {reg}/  (SET.md {'created' if not a.dry_run else 'skeleton'}, files.tsv)")
    if a.dry_run:
        print("DRY RUN: nothing rendered; hashes/bytes blank")


if __name__ == "__main__":
    main()
