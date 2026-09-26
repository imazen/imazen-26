"""EXIF colour hints (Make/Model, ColorSpace, InteropIndex) for JPEGs: canonical vs earlier copies."""
import csv, struct, collections, sys
def app1_exif(d):
    i = 2
    while i + 4 <= len(d) and d[i] == 0xFF:
        m = d[i+1]
        if m in (0xDA, 0xD9): break
        l = struct.unpack(">H", d[i+2:i+4])[0]
        if m == 0xE1 and d[i+4:i+10] == b"Exif\0\0": return d[i+10:i+2+l]
        i += 2 + l
    return None
def parse(t):
    if not t or len(t) < 8: return {}
    E = "<" if t[:2] == b"II" else ">"
    out = {}
    def ifd(off, depth=0):
        if off + 2 > len(t) or depth > 3: return
        n = struct.unpack(E+"H", t[off:off+2])[0]
        for k in range(n):
            e = off + 2 + 12*k
            if e + 12 > len(t): return
            tag, ty, cnt = struct.unpack(E+"HHI", t[e:e+8]); v = t[e+8:e+12]
            if ty == 2:
                o = struct.unpack(E+"I", v)[0] if cnt > 4 else e + 8
                s = t[o:o+cnt].split(b"\0")[0].decode("latin1", "replace").strip()
            elif ty == 3: s = struct.unpack(E+"H", v[:2])[0]
            elif ty == 4: s = struct.unpack(E+"I", v)[0]
            else: s = None
            if tag in (0x8769, 0xA005) and isinstance(s, int): ifd(s, depth+1)
            out[{0x10F:"make",0x110:"model",0xA001:"colorspace",0x0001:"interop"}.get(tag, tag)] = s
    ifd(struct.unpack(E+"I", t[4:8])[0])
    return out
def info(p):
    try: x = parse(app1_exif(open(p, "rb").read()))
    except Exception as e: return {"err": str(e)}
    cs = x.get("colorspace"); io = x.get("interop")
    return {"make": x.get("make", ""), "model": x.get("model", ""),
            "colorspace": {1:"sRGB", 2:"AdobeRGB", 0xFFFF:"Uncalibrated"}.get(cs, str(cs) if cs is not None else "-"),
            "interop": io if isinstance(io, str) else "-"}
if __name__ == "__main__":
    ids = set(l.split()[0] for l in open(sys.argv[1]))
    w = csv.writer(open(sys.argv[2], "w"), delimiter="\t")
    w.writerow(["id","class","which","make","model","colorspace","interop","path"])
    seen = set()
    for m in csv.DictReader(open("matches.tsv"), delimiter="\t"):
        if m["id"] not in ids: continue
        if m["id"] not in seen:
            seen.add(m["id"]); i = info(m["canonical"])
            w.writerow([m["id"], m["class"], "canonical", i.get("make"), i.get("model"), i.get("colorspace"), i.get("interop"), m["canonical"]])
        if m["candidate"]:
            i = info(m["candidate"])
            w.writerow([m["id"], m["class"], "earlier", i.get("make"), i.get("model"), i.get("colorspace"), i.get("interop"), m["candidate"]])
