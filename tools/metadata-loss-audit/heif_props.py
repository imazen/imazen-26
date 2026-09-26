import struct
def boxes(d, s, e):
    while s + 8 <= e:
        sz, ty = struct.unpack(">I4s", d[s:s+8]); hdr = 8
        if sz == 1: sz = struct.unpack(">Q", d[s+8:s+16])[0]; hdr = 16
        elif sz == 0: sz = e - s
        if sz < hdr: return
        yield ty.decode("latin1"), s, s + hdr, s + sz
        s += sz
def desc(icc):
    if len(icc) < 132: return f"<{len(icc)}B>"
    n = struct.unpack(">I", icc[128:132])[0]
    for k in range(min(n, 64)):
        e = 132 + 12*k
        if icc[e:e+4] == b"desc":
            off, sz = struct.unpack(">II", icc[e+4:e+12]); t = icc[off:off+sz]
            if t[:4] == b"desc": l = struct.unpack(">I", t[8:12])[0]; return t[12:12+l-1].decode("latin1")
            if t[:4] == b"mluc": l, o = struct.unpack(">II", t[20:28]); return t[o:o+l].decode("utf-16-be")
    return "?"
def props(path):
    return props_from_bytes(open(path, "rb").read())
def props_from_bytes(d):
    meta = next(b for b in boxes(d, 0, len(d)) if b[0] == "meta")
    kids = {b[0]: b for b in boxes(d, meta[2] + 4, meta[3])}
    iinf = kids["iinf"]; v = d[iinf[2]]; p = iinf[2] + 4 + (2 if v == 0 else 4)
    items = {}
    for ty, s, bs, e in boxes(d, p, iinf[3]):
        v2 = d[bs]; q = bs + 4; w = 2 if v2 < 3 else 4
        iid = int.from_bytes(d[q:q+w], "big"); q += w + 2; items[iid] = d[q:q+4].decode("latin1")
    ib = {b[0]: b for b in boxes(d, kids["iprp"][2], kids["iprp"][3])}
    pr = []
    for ty, s, bs, e in boxes(d, ib["ipco"][2], ib["ipco"][3]):
        x = ty
        if ty == "colr":
            ct = d[bs:bs+4].decode("latin1")
            x = f"colr:{ct}:{desc(d[bs+4:e])}" if ct in ("prof", "rICC") else f"colr:nclx:{struct.unpack('>HHH', d[bs+4:bs+10])}"
        elif ty == "auxC": x = "auxC:" + d[bs+4:e].split(b"\0")[0].decode("latin1")
        elif ty == "irot": x = f"irot:{d[bs] & 3}"
        elif ty == "clli": x = "clli:%d/%d" % struct.unpack(">HH", d[bs:bs+4])
        pr.append(x)
    ipma = ib["ipma"]; v = d[ipma[2]]; fl = struct.unpack(">I", d[ipma[2]:ipma[2]+4])[0] & 0xFFFFFF
    q = ipma[2] + 4; n = struct.unpack(">I", d[q:q+4])[0]; q += 4
    out = {}
    for _ in range(n):
        iid = int.from_bytes(d[q:q+(2 if v < 1 else 4)], "big"); q += 2 if v < 1 else 4
        cnt = d[q]; q += 1; lst = []
        for _ in range(cnt):
            if fl & 1: idx = struct.unpack(">H", d[q:q+2])[0] & 0x7FFF; q += 2
            else: idx = d[q] & 0x7F; q += 1
            if idx and not pr[idx-1].startswith(("hvcC", "ispe", "pixi")): lst.append(pr[idx-1])
        out[iid] = (items.get(iid, "?"), tuple(lst))
    return out
