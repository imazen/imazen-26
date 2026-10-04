#!/usr/bin/env python3
"""index_html.py <matrix_dir> <fixtures_dir> — emit index.html.

Two sections:
  1. Verdict table: fixture rows x adapter columns, colour-coded.
  2. Contact sheet: for every fixture with a non-ok status or a non-correct
     verdict, the hypothesis renders (correct + stored) and every adapter's
     actual output thumbnail, plus an amplified diff vs the correct hyp.
     Thumbnails are materialized under <matrix_dir>/sheet/ as JPEG (alpha
     flattened on grey) so the html is self-contained next to the run.
"""
import csv, sys, html, os, collections

try:
    from PIL import Image, ImageChops
except ImportError:
    Image = None

d, fd = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(f"{d}/matrix.tsv"), delimiter="\t"))
fixtures = {r["fixture"]: r for r in csv.DictReader(open(f"{fd}/fixtures.tsv"), delimiter="\t")}
adapters = sorted({r["adapter"] for r in rows})
fids = []
for r in rows:
    if r["fixture"] not in fids:
        fids.append(r["fixture"])

cellmap = collections.defaultdict(dict)
for r in rows:
    cellmap[r["fixture"]][r["adapter"]] = r

def cell(f, a):
    r = cellmap[f].get(a)
    if r is None:
        return '<td class="na">·</td>'
    if r["status"] != "ok":
        return f'<td class="err" title="{html.escape(r["error"][:120])}">ERR</td>'
    v = r["verdict"]
    if r["correct"] == "true":
        return f'<td class="ok" title="d1={r["d1"]} d2={r["d2"]}">✓ {html.escape(v[:10])}</td>'
    if v in ("other", "n/a"):
        return f'<td class="amb" title="d1={r["d1"]} d2={r["d2"]}">{html.escape(v[:10])}</td>'
    return f'<td class="bad" title="{html.escape(v)} d1={r["d1"]} d2={r["d2"]}">{html.escape(v[:10])}</td>'

# ---------- contact sheet ----------
sheet_dir = os.path.join(d, "sheet")
THUMB = 160

def thumb(src, name):
    """Write a <=THUMB px JPEG thumb under sheet/; return rel src or None."""
    if Image is None or not os.path.isfile(src):
        return None
    dst = os.path.join(sheet_dir, name + ".jpg")
    if not os.path.exists(dst):
        os.makedirs(sheet_dir, exist_ok=True)
        try:
            im = Image.open(src)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGBA", im.size, (128, 128, 128, 255))
                im = Image.alpha_composite(bg, im).convert("RGB")
            else:
                im = im.convert("RGB")
            if max(im.size) > THUMB:
                im.thumbnail((THUMB, THUMB), Image.LANCZOS)
            im.save(dst, quality=72)
        except Exception:
            return None
    return "sheet/" + name + ".jpg"

def diffthumb(out_png, ref_png, name):
    """Amplified |out - ref| diff thumb."""
    if Image is None or not (os.path.isfile(out_png) and os.path.isfile(ref_png)):
        return None
    dst = os.path.join(sheet_dir, name + ".jpg")
    if not os.path.exists(dst):
        try:
            a = Image.open(out_png).convert("RGB")
            b = Image.open(ref_png).convert("RGB")
            if a.size != b.size:
                a = a.resize(b.size)
            df = ImageChops.difference(a, b).point(lambda v: min(255, v * 8))
            if max(df.size) > THUMB:
                df.thumbnail((THUMB, THUMB), Image.LANCZOS)
            df.save(dst, quality=72)
        except Exception:
            return None
    return "sheet/" + name + ".jpg"

def hyp_png(fid, names):
    for n in names:
        p = os.path.join(fd, "hyps", fid, n + ".png")
        if os.path.isfile(p):
            return p
    return None

sheet_rows = []
for f in fids:
    cells = cellmap[f]
    interesting = any(
        r["status"] != "ok" or (r["verdict"] not in ("other", "n/a") and r["correct"] != "true")
        or r["verdict"] == "indistinguishable"
        for r in cells.values()
    )
    if not interesting:
        continue
    tr = [f'<tr><td><a href="#t-{f}">{f}</a></td>']
    ref = hyp_png(f, ("correct", "managed-correct", "correct-stored"))
    for lab, path in (("correct", ref), ("stored", hyp_png(f, ("stored",)))):
        s = thumb(path, f"{f}-hyp-{lab}") if path else None
        tr.append(f'<td><div class="lab">{lab}</div><img loading="lazy" src="{s}">' if s else f'<td><div class="lab">{lab}</div>')
    for a in adapters:
        r = cells.get(a)
        if r is None or r["status"] != "ok":
            continue
        outp = os.path.join(d, a, f + ".png")
        s = thumb(outp, f"{f}-{a}")
        dt = diffthumb(outp, ref, f"{f}-{a}-diff") if ref else None
        v = r["verdict"]
        klass = "ok" if r["correct"] == "true" else ("amb" if v in ("other", "n/a") else "bad")
        imgs = f'<img loading="lazy" src="{s}">' if s else ""
        if dt:
            imgs += f'<img loading="lazy" class="diff" src="{dt}">'
        tr.append(f'<td class="{klass}"><div class="lab">{a}: {html.escape(v[:12])}</div>{imgs}')
    sheet_rows.append("".join(tr) + "</tr>")

out = ['<!doctype html><meta charset="utf-8"><title>compat matrix</title>',
       '<style>td,th{font:11px monospace;padding:2px 5px;border:1px solid #ccc;vertical-align:top}',
       'img{max-width:160px;display:block}img.diff{border:1px dashed #888}',
       '.lab{font-size:10px;color:#444}.ok{background:#cfe8cf}.err{background:#f3c9c9}',
       '.amb{background:#f7e9b8}.bad{background:#e8a0a0}.na{background:#eee}',
       'th.w{writing-mode:vertical-rl;max-width:30px}</style>',
       '<h1>imazen-26 compat matrix</h1>',
       f'<p>{len(sheet_rows)} fixtures with non-ok or non-correct cells are shown '
       'in the contact sheet below the verdict table.</p>',
       '<table><tr><th>fixture</th>']
out += [f'<th class="w">{a}</th>' for a in adapters]
out.append('</tr>')
for f in fids:
    fx = fixtures.get(f, {})
    out.append(f'<tr id="t-{f}"><td title="{html.escape(fx.get("signal_desc",""))}">{f}</td>')
    out += [cell(f, a) for a in adapters]
    out.append('</tr>')
out.append('</table><h2>Contact sheet (non-ok / non-correct / indistinguishable)</h2><table>')
out += sheet_rows
out.append('</table>')
open(f"{d}/index.html", "w").write("\n".join(out))
print(f"wrote {d}/index.html ({len(sheet_rows)} sheet rows)")
