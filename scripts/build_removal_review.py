#!/usr/bin/env python3
"""Build the imazen-26 Removal Review page: the corpus contact sheet, set to the images
planned for render v4, where a click marks an image for removal.

Inputs:
  --contact-sheet  the published contact-sheet page (its embedded META table and its
                   sprite sheets, sheets/sheet_NN.webp, are reused unchanged)
  --extra-tsv      corpus-thumbs layout of extras/sheet_extra.webp (thumbnails that
                   replace contact-sheet cells: the 1214 camera original, DNG previews)
  --dupes          benchmarks/exact_dup_groups_2026-09-22.tsv
  --out            output HTML

Changes from the contact sheet:
  - byte-identical duplicates are retired: each group keeps its lowest id;
  - 1214 is its camera original (approved C2, not yet on R2);
  - the three DNGs show their embedded camera previews (zenraw#17 blocks a decode);
  - entries the split-leak audit found empty or broken carry a "suggested" flag.

Marks are stored by the page itself (artifact db collection `removals`, one document
per marked id); this script never seeds them.
"""
import argparse
import csv
import json
import re

C2_1214 = {
    "raw": "1200-lilith-interiors/1214_interiors_ornate-painted-ceiling_queen-s-grand-apartment-versailles_s23u_iso80-f2p2_20240424-123020_4000x3000.jpg",
    "w": 4000, "h": 3000, "bytes": 5593429, "orient": 6, "colour": "p3", "colourWhere": "",
}
DNG_IDS = {"1444", "1455", "1458"}
SUGGEST = {}
for i in ("8103", "8162", "8222", "8274", "8333", "8396", "8397"):
    SUGGEST[i] = "Capture of a bls.gov Access Denied page"
for i in ("8285", "8289", "8417", "8423", "8425"):
    SUGGEST[i] = "Broken layout: content squeezed into one column or mostly empty"
for i in ("6058", "6088", "6825", "6826"):
    SUGGEST[i] = "Blank page scan, paper show-through only"
for i in ("8113", "8114", "8171", "8172", "8230", "8231", "8282", "8283", "8341", "8342", "8414", "8415"):
    SUGGEST[i] = "lkml.org capture of its Not Found page (dense text, but not the page the URL names)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contact-sheet", required=True)
    ap.add_argument("--extra-tsv", required=True)
    ap.add_argument("--dupes", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--previews", help="corpus-thumbs --preview output dir (<id>.webp + previews.tsv)")
    ap.add_argument("--packs-out", help="where to write packs/pack_NN.webp (concatenated previews) for the full-screen viewer")
    ap.add_argument("--pack-mb", type=float, default=12.0)
    a = ap.parse_args()

    page = open(a.contact_sheet, encoding="utf-8").read()
    m = re.search(r'<script id="meta" type="application/json">(.*?)</script>', page, re.S)
    meta = json.loads(m.group(1))
    cols = meta["cols"]
    ix = {c: i for i, c in enumerate(cols)}

    retire = {}
    for r in csv.DictReader(open(a.dupes), delimiter="\t"):
        ids = sorted(r["ids"].split(","))
        for other in ids[1:]:
            retire[other] = ids[0]

    extra = {}
    for r in csv.DictReader(open(a.extra_tsv), delimiter="\t"):
        if not r["error"]:
            extra[r["id"]] = (int(r["col"]), int(r["row"]))

    items, retired = [], []
    for row in meta["items"]:
        row = list(row)
        i = row[ix["id"]]
        if i in retire:
            retired.append([i, retire[i], row[ix["folder"]], row[ix["title"]], row[ix["bucket"]]])
            continue
        if i == "1214":
            for k, v in C2_1214.items():
                row[ix[k]] = v
            row[ix["sdr"]] = ""
        if i in extra:
            row[ix["sheet"]] = "x"
            row[ix["col"]], row[ix["row"]] = extra[i]
        if i in DNG_IDS or i == "1214":
            assert i in extra, f"no extra thumbnail for {i}"
        row.append(SUGGEST.get(i, ""))
        items.append(row)
    missing = set(SUGGEST) - {r[ix["id"]] for r in items}
    assert not missing, f"suggested ids not in the set: {sorted(missing)}"

    extra_cols = ["suggest"]
    if a.previews:
        import os
        dims = {r["id"]: (int(r["w"]), int(r["h"])) for r in csv.DictReader(open(os.path.join(a.previews, "previews.tsv")), delimiter="\t")}
        os.makedirs(a.packs_out, exist_ok=True)
        cap = int(a.pack_mb * 1e6)
        pack, buf, index = 0, bytearray(), {}
        for row in sorted(items, key=lambda r: r[ix["id"]]):
            i = row[ix["id"]]
            data = open(os.path.join(a.previews, f"{i}.webp"), "rb").read()
            if buf and len(buf) + len(data) > cap:
                open(os.path.join(a.packs_out, f"pack_{pack:02d}.webp"), "wb").write(buf)
                pack, buf = pack + 1, bytearray()
            index[i] = (pack, len(buf), len(data)) + dims[i]
            buf += data
        if buf:
            open(os.path.join(a.packs_out, f"pack_{pack:02d}.webp"), "wb").write(buf)
        for row in items:
            row.extend(index[row[ix["id"]]])
        extra_cols += ["pk", "po", "pl", "pw", "ph"]
        print(f"{pack + 1} packs -> {a.packs_out}")
    out_meta = {"cols": cols + extra_cols, "items": items, "prefix": meta["prefix"], "retired": retired}
    blob = json.dumps(out_meta, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("@@META@@", blob).replace("@@N@@", f"{len(items):,}").replace("@@R@@", str(len(retired)))
    open(a.out, "w", encoding="utf-8").write(html)
    print(f"{len(items)} images, {len(retired)} retired, {len(SUGGEST)} suggested -> {a.out}")


TEMPLATE = r"""<title>imazen-26 Removal Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* Layout: the contact sheet's sticky filter bar over a tile grid; a click marks a tile, the corner button opens the detail drawer. */
:root{
  --ground:#EEF0EF; --surface:#FFFFFF; --well:#E2E6E4; --ink:#161A1D; --muted:#5B656B; --rule:#D3D9D7;
  --accent:#1D5FA8; --accent-soft:#DCE8F5; --accent-ink:#FFFFFF;
  --p3:#7A45C7; --p3-soft:#EDE4FA; --hdr:#A8650D; --hdr-soft:#F8ECD9; --lost:#B23A2B; --lost-soft:#F7E0DC; --lost-ink:#FFFFFF; --rot:#3F6B5B; --rot-soft:#DDEDE6;
  --sug:#7A5A00; --sug-soft:#FBF0CF;
  --v-bg:#000000; --v-bar:rgb(0 0 0 / .6); --v-ink:#FFFFFF; --v-dim:#B4BCC2; --v-line:rgb(255 255 255 / .32); --v-btn:rgb(255 255 255 / .1); --v-mark:#C9372C;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --cond:"IBM Plex Sans Condensed","IBM Plex Sans","Arial Narrow",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --s:150px;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#101315; --surface:#171B1E; --well:#1F2528; --ink:#E3E8EA; --muted:#94A1A7; --rule:#2B3337;
    --accent:#6FA6E0; --accent-soft:#16283A; --accent-ink:#0A1622;
    --p3:#B89AF0; --p3-soft:#2A2140; --hdr:#E0A955; --hdr-soft:#33271A; --lost:#EB8474; --lost-soft:#3A2220; --lost-ink:#1A0D0B; --rot:#8CC5AE; --rot-soft:#1B2E27;
    --sug:#E6C35C; --sug-soft:#332A10;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --ground:#101315; --surface:#171B1E; --well:#1F2528; --ink:#E3E8EA; --muted:#94A1A7; --rule:#2B3337;
  --accent:#6FA6E0; --accent-soft:#16283A; --accent-ink:#0A1622;
  --p3:#B89AF0; --p3-soft:#2A2140; --hdr:#E0A955; --hdr-soft:#33271A; --lost:#EB8474; --lost-soft:#3A2220; --lost-ink:#1A0D0B; --rot:#8CC5AE; --rot-soft:#1B2E27;
  --sug:#E6C35C; --sug-soft:#332A10;
  color-scheme:dark;
}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.45}
.wrap{padding-left:max(16px, env(safe-area-inset-left, 0px));padding-right:max(16px, env(safe-area-inset-right, 0px));padding-block:18px 48px;max-width:1600px;margin:0 auto}
header.top{display:grid;gap:6px}
h1{font-family:var(--cond);font-weight:600;font-size:1.9rem;letter-spacing:.01em;margin:0;text-wrap:balance}
.lede{color:var(--muted);margin:0;max-width:78ch}
.retired{color:var(--muted);font-size:.85rem;max-width:90ch}
.retired summary{cursor:pointer;color:var(--ink);font-weight:500}
.retired ul{margin:6px 0 0;padding-left:18px;columns:2 22rem}
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--ground);padding-block:10px;margin-top:10px;border-bottom:1px solid var(--rule);display:grid;gap:8px}
.row{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center}
.group{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
.glabel{font-family:var(--cond);font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-right:2px}
input[type=search],select,.reason{font:inherit;background:var(--surface);color:var(--ink);border:1px solid var(--rule);border-radius:4px;padding:5px 8px;max-width:100%}
input[type=search]{width:16rem}
.chip{font:500 .8rem/1.2 var(--sans);border:1px solid var(--rule);background:var(--surface);color:var(--ink);padding:4px 9px;border-radius:999px;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.chip:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.count{font-family:var(--mono);font-size:.82rem;color:var(--muted);font-variant-numeric:tabular-nums}
.count b{color:var(--ink);font-weight:500}
.count b.rm{color:var(--lost)}
.linkbtn{font:500 .8rem var(--sans);background:none;border:0;color:var(--accent);cursor:pointer;padding:4px}
.store{font-size:.8rem;color:var(--muted);display:inline-flex;gap:6px;align-items:center}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted);flex:none}
.store[data-s="live"] .dot{background:var(--rot)} .store[data-s="off"] .dot,.store[data-s="error"] .dot{background:var(--hdr)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(calc(var(--s) + 14px),1fr));gap:10px;margin-top:14px}
.tile{position:relative;content-visibility:auto;contain-intrinsic-size:auto calc(var(--s) + 52px)}
.pick{width:100%;height:100%;background:var(--surface);border:1px solid var(--rule);border-radius:4px;padding:7px;display:flex;flex-direction:column;gap:6px;cursor:pointer;text-align:left;font:inherit;color:inherit}
.pick:hover{border-color:var(--accent)}
.thumb{display:block;width:var(--s);height:var(--s);max-width:100%;align-self:center;background-repeat:no-repeat;background-size:calc(var(--s) * 10) auto;background-position:calc(var(--c) * var(--s) * -1) calc(var(--r) * var(--s) * -1)}
.cap{display:flex;flex-wrap:wrap;gap:3px 4px;align-items:center;min-height:18px}
.id{font-family:var(--mono);font-size:.8rem;font-weight:500;margin-right:auto}
.b{font:600 .66rem/1 var(--sans);letter-spacing:.04em;padding:3px 5px;border-radius:3px;background:var(--well);color:var(--muted);text-transform:uppercase;font-style:normal}
.b.p3{background:var(--p3-soft);color:var(--p3)} .b.hdr{background:var(--hdr-soft);color:var(--hdr)} .b.rot{background:var(--rot-soft);color:var(--rot)} .b.sug{background:var(--sug-soft);color:var(--sug)}
.ttl{display:block;font-size:.78rem;color:var(--muted);overflow-wrap:anywhere;line-height:1.3}
.flag{display:none;position:absolute;top:12px;left:12px;font:600 .7rem/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;background:var(--lost);color:var(--lost-ink);padding:4px 7px;border-radius:3px;pointer-events:none}
.info{position:absolute;top:10px;right:10px;width:26px;height:26px;border-radius:50%;border:1px solid var(--rule);background:var(--surface);color:var(--ink);font:600 .8rem/1 var(--mono);cursor:pointer;display:grid;place-items:center;opacity:.92}
.info:hover{border-color:var(--accent);color:var(--accent)}
.tile.marked .pick{border-color:var(--lost);background:var(--lost-soft);box-shadow:inset 0 0 0 1px var(--lost)}
.tile.marked .thumb{opacity:.35}
.tile.marked .flag{display:block}
.empty{color:var(--muted);padding:40px 0;text-align:center}
.panel{position:fixed;z-index:10;top:0;right:0;bottom:0;width:min(460px,100%);background:var(--surface);border-left:1px solid var(--rule);box-shadow:-8px 0 24px rgb(0 0 0 / .12);padding:calc(env(safe-area-inset-top,0px) + 16px) calc(env(safe-area-inset-right,0px) + 18px) calc(env(safe-area-inset-bottom,0px) + 18px) 18px;overflow-y:auto;display:flex;flex-direction:column;gap:12px}
.panel h2{font-family:var(--cond);font-weight:600;font-size:1.35rem;margin:0;text-wrap:balance}
.phead{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.pnav{display:flex;gap:6px}
.pbtn{font:500 .85rem var(--sans);border:1px solid var(--rule);background:var(--surface);color:var(--ink);border-radius:4px;padding:5px 10px;cursor:pointer}
.markbtn{font:600 .9rem var(--sans);border:1px solid var(--lost);background:var(--surface);color:var(--lost);border-radius:6px;padding:9px 12px;cursor:pointer}
.markbtn[aria-pressed="true"]{background:var(--lost);color:var(--lost-ink)}
.big{--s:256px;width:256px;height:256px;max-width:100%;align-self:center;background-color:var(--well)}
.sugnote{background:var(--sug-soft);color:var(--sug);border-radius:4px;padding:6px 9px;font-size:.85rem}
dl{display:grid;grid-template-columns:auto 1fr;gap:5px 14px;margin:0;font-size:.88rem}
dt{color:var(--muted)} dd{margin:0;overflow-wrap:anywhere}
.mono{font-family:var(--mono);font-size:.85em;font-variant-numeric:tabular-nums}
.links{display:grid;gap:6px}
.links a{color:var(--accent);font-weight:500}
.note{color:var(--muted);font-size:.8rem;margin:0}
.keys{color:var(--muted);font-size:.78rem;margin:0}
.copybox{width:100%;min-height:140px;font:12px/1.45 var(--mono);border:1px solid var(--rule);border-radius:4px;padding:8px;background:var(--surface);color:var(--ink)}
.vopen{font:500 .8rem var(--sans);background:var(--accent);color:var(--accent-ink);border:0;border-radius:999px;padding:5px 11px;cursor:pointer}
.viewer{position:fixed;inset:0;z-index:20;background:var(--v-bg);color:var(--v-ink);display:grid;grid-template-rows:auto minmax(0,1fr) auto}
.vtop,.vbot{display:flex;align-items:center;gap:10px;background:var(--v-bar);z-index:3}
.vtop{padding:calc(env(safe-area-inset-top,0px) + 8px) max(12px, env(safe-area-inset-right,0px)) 8px max(12px, env(safe-area-inset-left,0px))}
.vbot{padding:8px max(12px, env(safe-area-inset-right,0px)) calc(env(safe-area-inset-bottom,0px) + 10px) max(12px, env(safe-area-inset-left,0px));justify-content:space-between;flex-wrap:wrap}
.vtitle{flex:1;min-width:0;font:500 .9rem/1.3 var(--sans);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vpos{font:500 .8rem var(--mono);color:var(--v-dim);font-variant-numeric:tabular-nums}
.vbtn{font:600 .9rem var(--sans);border:1px solid var(--v-line);background:var(--v-btn);color:var(--v-ink);border-radius:8px;padding:9px 14px;cursor:pointer;text-decoration:none;display:inline-block}
.vbtn.mark[aria-pressed="true"]{background:var(--v-mark);border-color:var(--v-mark)}
.vbtn:focus-visible,.vnav:focus-visible{outline:2px solid var(--v-ink);outline-offset:2px}
.vstage{position:relative;overflow:hidden;touch-action:none;user-select:none;-webkit-user-select:none;cursor:grab}
.vstage img{position:absolute;left:50%;top:50%;max-width:100%;max-height:100%;transform:translate(-50%,-50%);transform-origin:center;-webkit-user-drag:none}
.vmsg{position:absolute;inset:0;display:grid;place-items:center;color:var(--v-dim);font-size:.9rem;pointer-events:none}
.vframe{position:absolute;inset:0;border:5px solid var(--v-mark);pointer-events:none;display:none;z-index:2}
.vflag{position:absolute;top:14px;left:14px;z-index:2;display:none;font:600 .75rem/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;background:var(--v-mark);color:var(--v-ink);padding:5px 8px;border-radius:3px;pointer-events:none}
.viewer.is-marked .vframe,.viewer.is-marked .vflag{display:block}
.vhint{color:var(--v-dim);font-size:.75rem}
.vnav{position:absolute;top:50%;transform:translateY(-50%);width:44px;height:72px;border:0;background:var(--v-btn);color:var(--v-ink);font-size:1.6rem;cursor:pointer;z-index:2;border-radius:6px}
.vnav.prev{left:max(8px, env(safe-area-inset-left,0px))} .vnav.next{right:max(8px, env(safe-area-inset-right,0px))}
@media (hover:none){.vnav{display:none}}
@media (max-width:560px){:root{--s:104px} input[type=search]{width:100%} .panel{top:auto;height:82%;width:100%;border-left:0;border-top:1px solid var(--rule);border-radius:10px 10px 0 0} .flag{top:10px;left:10px}}
@media (prefers-reduced-motion:no-preference){.pick{transition:border-color .12s,background-color .12s}}
</style>

<div class="wrap">
  <header class="top">
    <h1>imazen-26 Removal Review</h1>
    <p class="lede">The @@N@@ images planned for render v4, thumbnailed from the originals with orientation applied and colour converted to sRGB. Click a tile to mark it for removal, and click again to unmark it. Marks save to this page as you go; nothing is removed until they're processed. The <b>⤢</b> button opens a full-screen viewer: swipe or use the arrow keys to move, <kbd>x</kbd> or the button marks, double-tap zooms, and <b>Original</b> opens the file itself.</p>
    <details class="retired"><summary>@@R@@ byte-identical duplicates already retired (each group keeps its lowest id)</summary><ul id="retired"></ul></details>
  </header>

  <div class="bar" role="search">
    <div class="row">
      <input id="q" type="search" placeholder="Search id, subject, place…" aria-label="Search">
      <select id="folder" aria-label="Class"><option value="">All classes</option></select>
      <select id="sort" aria-label="Sort">
        <option value="id">Sort: id</option>
        <option value="bytes">Sort: largest file</option>
        <option value="px">Sort: most pixels</option>
      </select>
      <select id="size" aria-label="Tile size">
        <option value="" selected>Auto tile size</option>
        <option value="104">Small tiles</option>
        <option value="150">Medium tiles</option>
        <option value="220">Large tiles</option>
      </select>
      <span class="count" id="count" aria-live="polite"></span>
      <button class="linkbtn" id="reset" type="button">Clear filters</button>
      <button class="vopen" id="viewall" type="button">View full screen</button>
      <button class="linkbtn" id="copy" type="button">Copy marked list</button>
      <span class="store" id="store" data-s="connecting"><span class="dot"></span><span id="store-text">Connecting to saved marks…</span></span>
    </div>
    <div class="row">
      <div class="group" data-key="review"><span class="glabel">Review</span></div>
      <div class="group" data-key="format"><span class="glabel">Format</span></div>
      <div class="group" data-key="bucket"><span class="glabel">Bucket</span></div>
      <div class="group" data-key="colour"><span class="glabel">Colour</span></div>
      <div class="group" data-key="trait"><span class="glabel">Traits</span></div>
    </div>
    <textarea class="copybox" id="copybox" readonly hidden aria-label="Marked images as text"></textarea>
  </div>

  <div class="grid" id="grid"></div>
  <p class="empty" id="empty" hidden>No images match these filters.</p>
</div>

<aside class="panel" id="panel" hidden aria-label="Image details"></aside>

<div class="viewer" id="viewer" hidden role="dialog" aria-modal="true" aria-label="Full-screen view">
  <div class="vtop"><span class="vtitle" id="vtitle"></span><span class="vpos" id="vpos"></span><button class="vbtn" id="vclose" type="button">Close</button></div>
  <div class="vstage" id="vstage"><img id="vimg" alt=""><div class="vmsg" id="vmsg">Loading…</div><div class="vframe"></div><span class="vflag">Remove</span><button class="vnav prev" id="vprev" type="button" aria-label="Previous image">‹</button><button class="vnav next" id="vnext" type="button" aria-label="Next image">›</button></div>
  <div class="vbot"><button class="vbtn mark" id="vmark" type="button" aria-pressed="false">Mark for removal</button><span class="vhint">Swipe to move · double-tap to zoom · swipe down to close</span><span style="display:flex;gap:8px"><button class="vbtn" id="vinfo" type="button">Details</button><a class="vbtn" id="vorig" target="_blank" rel="noopener">Original ↗</a></span></div>
</div>

<script id="meta" type="application/json">@@META@@</script>
<script>
(() => {
  const META = JSON.parse(document.getElementById('meta').textContent);
  const C = META.cols, P = META.prefix;
  const DNG_NOTE = 'Thumbnail from the camera\'s embedded full-size preview: neither zenraw backend decodes this DNG yet (zenraw#17). DNGs stay in the originals and are left out of the v4 layers.';
  const items = META.items.map(a => {
    const o = {}; C.forEach((c, i) => o[c] = a[i]);
    o.px = o.w * o.h;
    o.text = (o.id + ' ' + o.title + ' ' + o.place + ' ' + o.folder).toLowerCase();
    return o;
  });
  const byId = new Map(items.map(o => [o.id, o]));
  const TOTAL = items.length;
  const COLOUR = { untagged: 'Untagged (sRGB assumed)', srgb: 'sRGB profile', p3: 'Display P3 profile', p3pq: 'Display P3 in the camera file; the corpus file carries the tmap\'s PQ profile (fixed by the whitelist-v2 swap)', adobe: 'Adobe RGB (1998) profile', lineargray: 'Display P3 in the camera file; the corpus file carries the gain map\'s "Linear Gray" profile (fixed by the whitelist-v2 swap)', camera: 'Camera raw (DNG colour matrices)', srgbexif: 'sRGB declared in EXIF (ColorSpace = 1), no ICC profile', r98: 'sRGB declared by the camera (EXIF Interop R98), restored by the whitelist-v2 swap', unknown: 'Nothing declared' };
  const FORMAT = { jpeg: 'JPEG', png: 'PNG', heic: 'HEIC', dng: 'DNG' };
  const groups = {
    review: [['marked', 'Marked'], ['unmarked', 'Not marked'], ['suggested', 'Suggested']],
    format: [['jpeg', 'JPEG'], ['png', 'PNG'], ['heic', 'HEIC'], ['dng', 'DNG']],
    bucket: [['train', 'Train'], ['validate', 'Validate'], ['test', 'Test']],
    colour: [['untagged', 'Untagged'], ['srgb', 'sRGB'], ['p3any', 'Display P3'], ['other', 'Other profile']],
    trait: [['rot', 'Rotated'], ['hdr', 'HDR'], ['prog', 'Progressive'], ['alpha', 'Alpha'], ['tile', 'Tile-only colour']],
  };
  const KEYS = Object.keys(groups);
  const state = { q: '', folder: '', sort: 'id', size: '' };
  for (const k of KEYS) state[k] = new Set();
  try {
    const saved = JSON.parse(localStorage.getItem('i26-removal-view') || 'null');
    if (saved) { for (const k of ['q', 'folder', 'sort', 'size']) if (typeof saved[k] === 'string') state[k] = saved[k]; for (const k of KEYS) if (Array.isArray(saved[k])) state[k] = new Set(saved[k]); }
  } catch (e) {}
  const saveView = () => { try { const v = { q: state.q, folder: state.folder, sort: state.sort, size: state.size }; for (const k of KEYS) v[k] = [...state[k]]; localStorage.setItem('i26-removal-view', JSON.stringify(v)); } catch (e) {} };

  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  const retUl = $('retired');
  for (const [id, keep, folder, title, bucket] of META.retired) {
    const li = document.createElement('li');
    li.innerHTML = `<span class="mono">${esc(id)}</span> duplicates <span class="mono">${esc(keep)}</span> · ${esc(title || folder)} (${esc(bucket)})`;
    retUl.append(li);
  }

  // ---------- marks ----------
  const MARKS = new Map();              // id -> {reason, at}
  const inflight = new Map();           // id -> pending write count
  const chains = new Map();
  let db = null, canWrite = null, storeState = 'connecting';

  const folderSel = $('folder');
  for (const f of [...new Set(items.map(o => o.folder))]) {
    const n = items.filter(o => o.folder === f).length;
    const opt = document.createElement('option');
    opt.value = f; opt.textContent = `${f} (${n})`;
    folderSel.append(opt);
  }
  for (const [key, opts] of Object.entries(groups)) {
    const g = document.querySelector(`.group[data-key="${key}"]`);
    for (const [v, label] of opts) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip'; b.textContent = label; b.dataset.v = v;
      b.setAttribute('aria-pressed', state[key].has(v));
      b.addEventListener('click', () => {
        state[key].has(v) ? state[key].delete(v) : state[key].add(v);
        b.setAttribute('aria-pressed', state[key].has(v));
        apply();
      });
      g.append(b);
    }
  }

  const colourKey = o => (o.colour === 'untagged' || o.colour === 'unknown') ? 'untagged' : (o.colour === 'srgb' || o.colour === 'srgbexif' || o.colour === 'r98') ? 'srgb' : (o.colour === 'p3' || o.colour === 'p3pq' || o.colour === 'lineargray') ? 'p3any' : 'other';
  const traits = o => {
    const t = [];
    if (o.orient > 1) t.push('rot');
    if (o.hdr === 'gainmap' || o.hdr === 'params' || o.hdr === 'lost') t.push('hdr');
    if (o.progressive) t.push('prog');
    if (o.alpha) t.push('alpha');
    if (o.colourWhere === 'tile') t.push('tile');
    return t;
  };
  items.forEach(o => { o.ck = colourKey(o); o.traits = traits(o); });

  const sheetUrl = o => o.sheet === 'x' ? 'extras/sheet_extra.webp' : `sheets/sheet_${String(o.sheet).padStart(2, '0')}.webp`;
  const grid = $('grid');
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) { const t = e.target; t.style.backgroundImage = `url("${t.dataset.url}")`; io.unobserve(t); }
  }, { rootMargin: '700px' }) : null;
  const thumbFor = (o, cls) => {
    const d = document.createElement('span');
    d.className = cls;
    d.style.setProperty('--c', o.col);
    d.style.setProperty('--r', o.row);
    d.dataset.url = sheetUrl(o);
    return d;
  };
  const badges = o => {
    const out = [`<i class="b">${FORMAT[o.format] || o.format}</i>`];
    if (o.ck === 'p3any') out.push('<i class="b p3">P3</i>');
    if (o.traits.includes('hdr')) out.push('<i class="b hdr">HDR</i>');
    if (o.orient > 1) out.push(`<i class="b rot">rot ${o.orient}</i>`);
    if (o.suggest) out.push('<i class="b sug">Suggested</i>');
    return out.join('');
  };

  const tiles = new Map();
  for (const o of items) {
    const wrap = document.createElement('div');
    wrap.className = 'tile'; wrap.dataset.id = o.id;
    const pick = document.createElement('button');
    pick.type = 'button'; pick.className = 'pick';
    pick.setAttribute('aria-pressed', 'false');
    pick.setAttribute('aria-label', `${o.id} ${o.title || o.folder}: mark for removal`);
    if (o.suggest) pick.title = 'Suggested: ' + o.suggest;
    const th = thumbFor(o, 'thumb');
    const cap = document.createElement('span');
    cap.className = 'cap';
    cap.innerHTML = `<span class="id">${o.id}</span>${badges(o)}`;
    const ttl = document.createElement('span');
    ttl.className = 'ttl'; ttl.textContent = o.title || o.folder;
    const flag = document.createElement('span');
    flag.className = 'flag'; flag.textContent = 'Remove';
    pick.append(th, cap, ttl, flag);
    pick.addEventListener('click', () => toggleMark(o.id));
    const info = document.createElement('button');
    info.type = 'button'; info.className = 'info'; info.textContent = '⤢';
    info.setAttribute('aria-label', `View ${o.id} full screen`);
    info.addEventListener('click', e => { e.stopPropagation(); openViewer(o.id); });
    wrap.append(pick, info);
    tiles.set(o.id, wrap);
    if (io) io.observe(th); else th.style.backgroundImage = `url("${th.dataset.url}")`;
  }

  function paintTile(id) {
    const t = tiles.get(id); if (!t) return;
    const on = MARKS.has(id);
    t.classList.toggle('marked', on);
    const pick = t.querySelector('.pick');
    pick.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  let visible = [];
  function apply() {
    const q = state.q.trim().toLowerCase();
    const rv = state.review;
    visible = items.filter(o =>
      (!q || o.text.includes(q)) &&
      (!state.folder || o.folder === state.folder) &&
      (!state.format.size || state.format.has(o.format)) &&
      (!state.bucket.size || state.bucket.has(o.bucket)) &&
      (!state.colour.size || state.colour.has(o.ck)) &&
      [...state.trait].every(t => o.traits.includes(t)) &&
      (!rv.has('marked') || MARKS.has(o.id)) &&
      (!rv.has('unmarked') || !MARKS.has(o.id)) &&
      (!rv.has('suggested') || !!o.suggest));
    const key = state.sort === 'bytes' ? (a, b) => b.bytes - a.bytes : state.sort === 'px' ? (a, b) => b.px - a.px : (a, b) => a.id.localeCompare(b.id);
    visible.sort(key);
    const frag = document.createDocumentFragment();
    const show = new Set(visible.map(o => o.id));
    for (const o of visible) frag.append(tiles.get(o.id));
    for (const [id, t] of tiles) t.hidden = !show.has(id);
    grid.append(frag);
    $('empty').hidden = visible.length > 0;
    if (state.size) document.documentElement.style.setProperty('--s', state.size + 'px');
    else document.documentElement.style.removeProperty('--s');
    updateCount();
    saveView();
  }
  function updateCount() {
    $('count').innerHTML = `Showing <b>${visible.length.toLocaleString()}</b> of ${TOTAL.toLocaleString()} · <b class="rm">${MARKS.size}</b> marked`;
  }

  $('q').value = state.q; folderSel.value = state.folder; $('sort').value = state.sort; $('size').value = state.size;
  $('q').addEventListener('input', e => { state.q = e.target.value; apply(); });
  folderSel.addEventListener('change', e => { state.folder = e.target.value; apply(); });
  $('sort').addEventListener('change', e => { state.sort = e.target.value; apply(); });
  $('size').addEventListener('change', e => { state.size = e.target.value; apply(); });
  $('reset').addEventListener('click', () => {
    state.q = ''; state.folder = '';
    for (const k of KEYS) state[k].clear();
    $('q').value = ''; folderSel.value = '';
    document.querySelectorAll('.chip').forEach(c => c.setAttribute('aria-pressed', 'false'));
    apply();
  });

  // ---------- saving ----------
  function storeText() {
    const box = $('store'); box.dataset.s = storeState;
    $('store-text').textContent = {
      connecting: 'Connecting to saved marks…',
      live: 'Marks save to this page',
      off: 'Saving isn\'t available in this view; marks stay on this screen',
      readonly: 'Read-only: only editors save marks',
      error: 'Lost the connection to saved marks; reload to reconnect',
      failed: 'A mark didn\'t save; click it again to retry'
    }[storeState] || storeState;
  }
  function toggleMark(id, force) {
    if (storeState === 'readonly') return;
    const on = force === undefined ? !MARKS.has(id) : force;
    if (on) MARKS.set(id, { reason: (MARKS.get(id) || {}).reason || '', at: new Date().toISOString() });
    else MARKS.delete(id);
    paintTile(id); updateCount();
    if (current === id) paintPanelMark();
    if (vId === id) paintViewerMark();
    persist(id);
  }
  function persist(id) {
    if (!db || canWrite === false) return;
    inflight.set(id, (inflight.get(id) || 0) + 1);
    const prev = chains.get(id) || Promise.resolve();
    const next = prev.then(async () => {
      const m = MARKS.get(id), o = byId.get(id);
      const ref = db.collection('removals').doc(id);
      try {
        if (m) await ref.set({ id, path: o.raw || '', folder: o.folder, title: o.title || '', bucket: o.bucket, remove: true, reason: m.reason || '', suggested: o.suggest || '', at: m.at, v: 1 });
        else await ref.delete();
        if (storeState === 'failed') { storeState = 'live'; storeText(); }
      } catch (e) {
        if (e && e.code === 'invalid_argument' && canWrite !== true) { canWrite = false; storeState = 'readonly'; }
        else storeState = 'failed';
        storeText();
      } finally {
        inflight.set(id, inflight.get(id) - 1);
      }
    });
    chains.set(id, next.catch(() => {}));
  }
  function applySnapshot(snap) {
    const server = new Map();
    for (const d of snap.docs) {
      if (!d.exists || !byId.has(d.id)) continue;
      const v = d.data();
      if (v && v.remove) server.set(d.id, { reason: typeof v.reason === 'string' ? v.reason : '', at: v.at || '' });
    }
    const ids = new Set([...server.keys(), ...MARKS.keys()]);
    for (const id of ids) {
      if (inflight.get(id)) continue;
      const s = server.get(id);
      if (s) MARKS.set(id, s); else MARKS.delete(id);
      paintTile(id);
    }
    updateCount();
    if (current) paintPanelMark();
    if (vId) paintViewerMark();
    if (state.review.size) apply();
  }

  // ---------- details ----------
  const panel = $('panel');
  let current = null, reasonTimer = null;
  const mb = n => (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + ' MB';
  function paintPanelMark() {
    const b = panel.querySelector('.markbtn'); if (!b) return;
    const on = MARKS.has(current);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.textContent = on ? 'Marked for removal: click to keep' : 'Mark for removal';
    const r = panel.querySelector('.reason');
    if (r) { r.disabled = !on || storeState === 'readonly'; if (document.activeElement !== r) r.value = on ? (MARKS.get(current).reason || '') : ''; }
  }
  function openDetail(id) {
    const o = byId.get(id);
    if (!o) return;
    current = id;
    const sdrStem = o.sdr === '=' ? o.raw.replace(/\.[^.]+$/, '') : o.sdr;
    const links = [];
    if (sdrStem) links.push(`<a href="${P.png}${encodeURI(sdrStem)}.sdr.png" target="_blank" rel="noopener">Full-size render (PNG, orientation applied)</a>`);
    if (o.hdrUrl && sdrStem) links.push(`<a href="${P.png}${encodeURI(sdrStem)}.hdr.png" target="_blank" rel="noopener">HDR render (16-bit PQ PNG)</a>`);
    if (o.id !== '1214' && o.raw) links.push(`<a href="${P.raw}${encodeURI(o.raw)}" target="_blank" rel="noopener">Original file (${FORMAT[o.format] || o.format}, ${mb(o.bytes)})</a>`);
    const hdr = o.hdr === 'gainmap' ? 'Gain map present' : o.hdr === 'lost' ? 'Gain map in the camera file; restored by the whitelist-v2 swap' : o.hdr === 'params' ? 'Gain map present; Apple\'s HDR parameters restored by the whitelist-v2 swap' : 'No';
    const note = o.format === 'dng' ? DNG_NOTE : o.id === '1214' ? 'Shown as its camera original (the approved swap). It reaches R2 with the whitelist-v2 upload, so there\'s no download link yet.' : 'HEIC originals download instead of displaying in a browser.';
    panel.innerHTML = `
      <div class="phead">
        <h2>${esc(o.title || o.folder)}</h2>
        <div class="pnav">
          <button class="pbtn" type="button" data-nav="-1" aria-label="Previous image">‹</button>
          <button class="pbtn" type="button" data-nav="1" aria-label="Next image">›</button>
          <button class="pbtn" type="button" data-close aria-label="Close details">Close</button>
        </div>
      </div>`;
    const big = thumbFor(o, 'thumb big');
    big.style.backgroundImage = `url("${big.dataset.url}")`;
    panel.append(big);
    const mk = document.createElement('div');
    mk.style.display = 'grid'; mk.style.gap = '6px';
    mk.innerHTML = `${o.suggest ? `<p class="sugnote">Suggested: ${esc(o.suggest)}</p>` : ''}
      <button class="markbtn" type="button" aria-pressed="false">Mark for removal</button>
      <button class="pbtn" type="button" data-view>View full screen</button>
      <input class="reason" type="text" placeholder="Reason (optional, saved with the mark)" aria-label="Reason for removal">
      <p class="keys"><kbd>x</kbd> marks or keeps · <kbd>←</kbd> <kbd>→</kbd> move · <kbd>Esc</kbd> closes</p>`;
    panel.append(mk);
    const body = document.createElement('div');
    body.innerHTML = `
      <dl>
        <dt>Id</dt><dd class="mono">${o.id}</dd>
        ${o.place ? `<dt>Place</dt><dd>${esc(o.place)}</dd>` : ''}
        <dt>Class</dt><dd>${esc(o.folder)}</dd>
        <dt>Format</dt><dd>${FORMAT[o.format] || o.format}${o.progressive ? ', progressive' : ''}${o.alpha ? ', with alpha' : ''}${o.bits ? `, ${o.bits}-bit` : ''}</dd>
        <dt>Size</dt><dd class="mono">${o.w.toLocaleString()} × ${o.h.toLocaleString()} · ${mb(o.bytes)}</dd>
        <dt>Bucket</dt><dd>${o.bucket}</dd>
        <dt>Orientation</dt><dd>${o.orient > 1 ? `EXIF ${o.orient} (applied in the thumbnail)` : 'Upright'}</dd>
        <dt>Colour</dt><dd>${COLOUR[o.colour] || o.colour}${o.colourWhere === 'tile' ? ' (on the grid tiles only)' : ''}</dd>
        <dt>HDR</dt><dd>${hdr}</dd>
        ${o.license ? `<dt>License</dt><dd>${esc(o.license)}${o.source ? ` · ${esc(o.source)}` : ''}</dd>` : ''}
      </dl>
      <div class="links" style="margin-top:14px">${links.join('')}</div>
      <p class="note" style="margin-top:10px">${note}</p>`;
    panel.append(body);
    panel.hidden = false;
    panel.querySelector('[data-close]').addEventListener('click', closeDetail);
    panel.querySelectorAll('[data-nav]').forEach(b => b.addEventListener('click', () => step(+b.dataset.nav)));
    panel.querySelector('.markbtn').addEventListener('click', () => toggleMark(current));
    panel.querySelector('[data-view]').addEventListener('click', () => { const id = current; closeDetail(); openViewer(id); });
    const r = panel.querySelector('.reason');
    r.addEventListener('input', () => {
      const m = MARKS.get(current); if (!m) return;
      m.reason = r.value;
      const id = current;
      clearTimeout(reasonTimer); reasonTimer = setTimeout(() => persist(id), 800);
    });
    paintPanelMark();
    try { history.replaceState(null, '', '#' + id); } catch (e) {}
  }
  function closeDetail() {
    panel.hidden = true; current = null;
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
  }
  function step(d) {
    if (!current) return;
    const list = visible.length ? visible : items;
    const i = list.findIndex(o => o.id === current);
    const next = list[(i + d + list.length) % list.length];
    if (next) openDetail(next.id);
  }
  document.addEventListener('keydown', e => {
    if (panel.hidden || !viewer.hidden) return;
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) { if (e.key === 'Escape') e.target.blur(); return; }
    if (e.key === 'Escape') closeDetail();
    else if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'x' || e.key === 'X') toggleMark(current);
  });

  // ---------- full-screen viewer ----------
  const viewer = $('viewer'), vstage = $('vstage'), vimg = $('vimg'), vmsg = $('vmsg');
  let vList = [], vI = 0, vId = null, vLoad = 0, z = 1, dx = 0, dy = 0, lastFocus = null;
  const PACKS = new Map(), URLS = new Map();
  const hasPreviews = items.length && items[0].pk !== undefined;
  function packBuf(pk) {
    if (PACKS.has(pk)) { const p = PACKS.get(pk); PACKS.delete(pk); PACKS.set(pk, p); return p; }
    const p = fetch(`packs/pack_${String(pk).padStart(2, '0')}.webp`).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); });
    p.catch(() => PACKS.delete(pk));
    PACKS.set(pk, p);
    while (PACKS.size > 3) PACKS.delete(PACKS.keys().next().value);
    return p;
  }
  async function previewUrl(o) {
    if (URLS.has(o.id)) { const u = URLS.get(o.id); URLS.delete(o.id); URLS.set(o.id, u); return u; }
    const buf = await packBuf(o.pk);
    const url = URL.createObjectURL(new Blob([buf.slice(o.po, o.po + o.pl)], { type: 'image/webp' }));
    URLS.set(o.id, url);
    while (URLS.size > 16) { const k = URLS.keys().next().value; if (k === vId) { const u = URLS.get(k); URLS.delete(k); URLS.set(k, u); continue; } URL.revokeObjectURL(URLS.get(k)); URLS.delete(k); }
    return url;
  }
  const setT = (anim) => { vimg.style.transition = anim ? 'transform .18s ease' : 'none'; vimg.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(${z})`; };
  function paintViewerMark() {
    const on = MARKS.has(vId);
    viewer.classList.toggle('is-marked', on);
    const b = $('vmark'); b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.textContent = on ? 'Marked for removal' : 'Mark for removal';
    b.disabled = storeState === 'readonly';
  }
  async function vShow(i) {
    if (!vList.length) return;
    vI = (i + vList.length) % vList.length;
    const o = vList[vI]; vId = o.id;
    z = 1; dx = 0; dy = 0; setT(false);
    $('vtitle').innerHTML = `<span class="mono">${esc(o.id)}</span> · ${esc(o.title || o.folder)}`;
    $('vpos').textContent = `${(vI + 1).toLocaleString()} / ${vList.length.toLocaleString()}`;
    const orig = $('vorig');
    if (o.raw && o.id !== '1214') { orig.hidden = false; orig.href = P.raw + encodeURI(o.raw); orig.textContent = (o.format === 'heic' || o.format === 'dng') ? 'Original ↗ (downloads)' : 'Original ↗'; }
    else orig.hidden = true;
    paintViewerMark();
    try { history.replaceState(null, '', '#' + o.id); } catch (e) {}
    if (!hasPreviews) { vimg.removeAttribute('src'); vmsg.textContent = 'Previews are not in this version of the page.'; vmsg.hidden = false; return; }
    const ticket = ++vLoad;
    vmsg.textContent = 'Loading…'; vmsg.hidden = false; vimg.style.opacity = '0';
    try {
      const url = await previewUrl(o);
      if (ticket !== vLoad) return;
      vimg.onload = () => { if (ticket === vLoad) { vmsg.hidden = true; vimg.style.opacity = '1'; } };
      vimg.src = url; vimg.alt = `${o.id} ${o.title || o.folder}`;
    } catch (e) {
      if (ticket === vLoad) { vmsg.textContent = 'This preview didn\'t load. Use Original to open the file.'; vmsg.hidden = false; }
    }
    for (const d of [1, -1, 2]) { const n = vList[(vI + d + vList.length) % vList.length]; if (n) previewUrl(n).catch(() => {}); }
  }
  function openViewer(id) {
    vList = (visible.length ? visible : items).slice();
    const i = Math.max(0, vList.findIndex(o => o.id === id));
    lastFocus = document.activeElement;
    viewer.hidden = false;
    document.body.style.overflow = 'hidden';
    if (window.matchMedia && window.matchMedia('(hover: hover)').matches && document.documentElement.requestFullscreen) {
      try { const p = document.documentElement.requestFullscreen(); if (p && p.catch) p.catch(() => {}); } catch (e) {}
    }
    vShow(i);
    $('vclose').focus();
  }
  function closeViewer() {
    viewer.hidden = true; vId = null; vLoad++;
    document.body.style.overflow = '';
    if (document.fullscreenElement && document.exitFullscreen) { try { const p = document.exitFullscreen(); if (p && p.catch) p.catch(() => {}); } catch (e) {} }
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  $('viewall').addEventListener('click', () => { const l = visible.length ? visible : items; if (l.length) openViewer(l[0].id); });
  $('vclose').addEventListener('click', closeViewer);
  $('vprev').addEventListener('click', () => vShow(vI - 1));
  $('vnext').addEventListener('click', () => vShow(vI + 1));
  $('vmark').addEventListener('click', () => { if (vId) toggleMark(vId); });
  $('vinfo').addEventListener('click', () => { const id = vId; closeViewer(); openDetail(id); });
  const pts = new Map();
  let sx = 0, sy = 0, st = 0, pdx = 0, pdy = 0, pinch = null, lastTap = 0, moved = false;
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  vstage.addEventListener('pointerdown', e => {
    if (e.target.closest('.vnav')) return;
    vstage.setPointerCapture(e.pointerId);
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) { sx = e.clientX; sy = e.clientY; st = performance.now(); pdx = dx; pdy = dy; moved = false; }
    else if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: dist(a, b) || 1, z }; }
  });
  vstage.addEventListener('pointermove', e => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2 && pinch) { const [a, b] = [...pts.values()]; z = Math.min(6, Math.max(1, pinch.z * dist(a, b) / pinch.d)); if (z === 1) { dx = 0; dy = 0; } moved = true; setT(false); return; }
    const mx = e.clientX - sx, my = e.clientY - sy;
    if (Math.abs(mx) > 6 || Math.abs(my) > 6) moved = true;
    if (z > 1) { dx = pdx + mx; dy = pdy + my; }
    else { dx = mx; dy = my > 0 && Math.abs(my) > Math.abs(mx) ? my : 0; }
    setT(false);
  });
  function endPointer(e) {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    if (pts.size) return;
    if (pinch) { pinch = null; return; }
    const mx = e.clientX - sx, my = e.clientY - sy, dt = performance.now() - st;
    if (z === 1) {
      if (Math.abs(mx) > 60 && Math.abs(mx) > Math.abs(my)) { vShow(vI + (mx < 0 ? 1 : -1)); return; }
      if (my > 100 && my > Math.abs(mx)) { closeViewer(); return; }
      dx = 0; dy = 0; setT(true);
    }
    if (!moved && dt < 300) {
      const now = performance.now();
      if (now - lastTap < 320) {
        lastTap = 0;
        if (z > 1) { z = 1; dx = 0; dy = 0; }
        else { const r = vstage.getBoundingClientRect(); z = 2.5; dx = (r.left + r.width / 2 - e.clientX) * 1.5; dy = (r.top + r.height / 2 - e.clientY) * 1.5; }
        setT(true);
      } else lastTap = now;
    }
  }
  vstage.addEventListener('pointerup', endPointer);
  vstage.addEventListener('pointercancel', e => { pts.delete(e.pointerId); pinch = null; if (z === 1) { dx = 0; dy = 0; setT(true); } });
  vstage.addEventListener('wheel', e => { if (!e.ctrlKey) return; e.preventDefault(); z = Math.min(6, Math.max(1, z * (e.deltaY < 0 ? 1.15 : 1 / 1.15))); if (z === 1) { dx = 0; dy = 0; } setT(false); }, { passive: false });
  document.addEventListener('keydown', e => {
    if (viewer.hidden) return;
    if (e.key === 'Escape') { e.preventDefault(); closeViewer(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); vShow(vI + 1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); vShow(vI - 1); }
    else if (e.key === 'x' || e.key === 'X') { if (vId) toggleMark(vId); }
    else if (e.key === 'z' || e.key === 'Z') { if (z > 1) { z = 1; dx = 0; dy = 0; } else z = 2.5; setT(true); }
  });

  // ---------- copy ----------
  $('copy').addEventListener('click', () => {
    const ids = [...MARKS.keys()].sort();
    const lines = ['id\tclass\ttitle\treason'];
    for (const id of ids) { const o = byId.get(id); lines.push([id, o.folder, o.title || '', (MARKS.get(id).reason || '').replace(/\s+/g, ' ')].join('\t')); }
    const text = lines.join('\n');
    const box = $('copybox'), btn = $('copy');
    const fallback = () => { box.hidden = false; box.value = text; box.focus(); box.select(); btn.textContent = 'Copy from the box below'; };
    try { navigator.clipboard.writeText(text).then(() => { btn.textContent = `Copied ${ids.length}`; setTimeout(() => btn.textContent = 'Copy marked list', 1800); }, fallback); } catch (e) { fallback(); }
  });

  apply();
  storeText();
  const h = location.hash.replace('#', '');
  if (/^\d{4}$/.test(h)) openDetail(h);

  (async () => {
    const c = window.claude;
    if (!c || typeof c.use !== 'function') { storeState = 'off'; storeText(); return; }
    try { db = await c.use('db'); } catch (e) { db = null; }
    if (!db) { storeState = 'off'; storeText(); return; }
    try { const user = await c.use('user'); if (user && typeof user.canEdit === 'function') canWrite = await user.canEdit(); } catch (e) { canWrite = null; }
    storeState = canWrite === false ? 'readonly' : 'live';
    storeText();
    db.collection('removals').onSnapshot(applySnapshot, () => { storeState = 'error'; storeText(); });
    if (canWrite !== false) for (const id of MARKS.keys()) persist(id);
  })();
})();
</script>
"""

if __name__ == "__main__":
    main()
