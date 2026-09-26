#!/usr/bin/env python3
"""Content keys that survive metadata-only rewrites.
JPEG: sha256 of everything from the first non-APPn/COM marker to the primary EOI.
PNG:  sha256 of IHDR payload + concatenated IDAT payloads.
HEIC: sha256 of the coded data of every hvc1 item (via iloc), in item-id order.
Other formats: sha256 of the whole file.
Usage: keys.py <list of paths on stdin> > keys.tsv   (path<TAB>kind<TAB>key<TAB>bytes)"""
import sys, struct, hashlib, os

def jpeg_key(d):
    pos = 2
    while pos + 4 <= len(d) and d[pos] == 0xFF:
        m = d[pos + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7: pos += 2; continue
        if 0xE0 <= m <= 0xEF or m == 0xFE:
            pos += 2 + struct.unpack(">H", d[pos + 2:pos + 4])[0]; continue
        break
    start = pos; p = pos
    while p + 2 <= len(d):
        if d[p] != 0xFF: return None
        m = d[p + 1]
        if m == 0xFF: p += 1; continue
        if m == 0xD9: return hashlib.sha256(d[start:p + 2]).hexdigest()
        if 0xD0 <= m <= 0xD7 or m == 0x01: p += 2; continue
        p += 2 + struct.unpack(">H", d[p + 2:p + 4])[0]
        if m == 0xDA:
            while p + 1 < len(d) and not (d[p] == 0xFF and d[p + 1] not in (0x00, 0xFF) and not 0xD0 <= d[p + 1] <= 0xD7):
                p += 1
    return None

def png_key(d):
    if d[:8] != b"\x89PNG\r\n\x1a\n": return None
    h = hashlib.sha256(); pos = 8
    while pos + 8 <= len(d):
        ln, ty = struct.unpack(">I4s", d[pos:pos + 8])
        if ty in (b"IHDR", b"IDAT"): h.update(d[pos + 8:pos + 8 + ln])
        if ty == b"IEND": break
        pos += 12 + ln
    return h.hexdigest()

def boxes(d, s, e):
    while s + 8 <= e:
        sz, ty = struct.unpack(">I4s", d[s:s + 8]); hdr = 8
        if sz == 1: sz = struct.unpack(">Q", d[s + 8:s + 16])[0]; hdr = 16
        elif sz == 0: sz = e - s
        if sz < hdr: return
        yield ty, s, s + hdr, s + sz
        s += sz

def heic_key(d):
    meta = next((b for b in boxes(d, 0, len(d)) if b[0] == b"meta"), None)
    if not meta: return None
    kids = {b[0]: b for b in boxes(d, meta[2] + 4, meta[3])}
    if b"iloc" not in kids or b"iinf" not in kids: return None
    # item types
    iinf = kids[b"iinf"]; v = d[iinf[2]]; p = iinf[2] + 4 + (2 if v == 0 else 4)
    types = {}
    for ty, s, bs, e in boxes(d, p, iinf[3]):
        v2 = d[bs]; q = bs + 4
        w = 2 if v2 < 3 else 4
        iid = int.from_bytes(d[q:q + w], "big"); q += w + 2
        types[iid] = d[q:q + 4]
    il = kids[b"iloc"]; q = il[2]; v = d[q]; q += 4
    osz, lsz = d[q] >> 4, d[q] & 15; bsz = d[q + 1] >> 4; isz = (d[q + 1] & 15) if v in (1, 2) else 0; q += 2
    if v < 2: n = struct.unpack(">H", d[q:q + 2])[0]; q += 2
    else: n = struct.unpack(">I", d[q:q + 4])[0]; q += 4
    rd = lambda size: (int.from_bytes(d[q:q + size], "big") if size else 0)
    h = hashlib.sha256(); items = []
    for _ in range(n):
        if v < 2: iid = struct.unpack(">H", d[q:q + 2])[0]; q += 2
        else: iid = struct.unpack(">I", d[q:q + 4])[0]; q += 4
        method = 0
        if v in (1, 2): method = struct.unpack(">H", d[q:q + 2])[0] & 15; q += 2
        q += 2  # data_reference_index
        base = rd(bsz); q += bsz
        ec = struct.unpack(">H", d[q:q + 2])[0]; q += 2
        ext = []
        for _ in range(ec):
            if isz: q += isz
            off = rd(osz); q += osz
            ln = rd(lsz); q += lsz
            ext.append((base + off, ln))
        if types.get(iid) == b"hvc1" and method == 0: items.append((iid, ext))
    if not items: return None
    for iid, ext in sorted(items):
        for off, ln in ext: h.update(d[off:off + ln])
    return h.hexdigest()

for line in sys.stdin:
    path = line.rstrip("\n")
    if not path: continue
    try:
        d = open(path, "rb").read()
        low = path.lower()
        if low.endswith((".jpg", ".jpeg")): kind, key = "jpeg", jpeg_key(d)
        elif low.endswith(".png"): kind, key = "png", png_key(d)
        elif low.endswith((".heic", ".heif")): kind, key = "heic", heic_key(d)
        else: kind, key = "file", None
        if key is None: kind, key = kind + "-whole", hashlib.sha256(d).hexdigest()
        print(f"{path}\t{kind}\t{key}\t{len(d)}", flush=True)
    except Exception as e:
        print(f"{path}\terror\t{type(e).__name__}: {e}\t0", flush=True)
