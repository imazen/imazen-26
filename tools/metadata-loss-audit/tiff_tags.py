#!/usr/bin/env python3
"""List every TIFF/DNG tag (IFD chain, SubIFDs, Exif IFD) as ifd-path/tag -> count+value digest.
Usage: tiff_tags.py a.dng b.dng   → tags only in a, only in b, and changed values."""
import sys, struct, hashlib
SIZES = {1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8,13:4,16:8,17:8,18:8}
def tags(p):
    return tags_from_bytes(open(p, "rb").read())
def tags_from_bytes(d):
    E = "<" if d[:2] == b"II" else ">"; out = {}; seen = set()
    def walk(off, path, depth=0):
        while off and off + 2 <= len(d) and off not in seen and depth < 8:
            seen.add(off); n = struct.unpack(E+"H", d[off:off+2])[0]
            for k in range(n):
                e = off + 2 + 12*k; tag, ty, cnt = struct.unpack(E+"HHI", d[e:e+8])
                sz = SIZES.get(ty, 1) * cnt
                v = d[e+8:e+8+sz] if sz <= 4 else d[struct.unpack(E+"I", d[e+8:e+12])[0]:][:sz]
                big = tag in (0x0111, 0x0117, 0x0144, 0x0145, 0x927C, 0x02BC, 0x8773, 0xC68D, 0xC68C)
                out[f"{path}/{tag:04x}"] = (ty, cnt, "" if big else hashlib.sha256(v).hexdigest()[:12])
                if tag in (0x014A,):
                    for i in range(cnt): walk(struct.unpack(E+"I", v[4*i:4*i+4])[0], f"{path}/sub{i}", depth+1)
                if tag in (0x8769, 0xA005, 0x8825):
                    walk(struct.unpack(E+"I", v[:4])[0], f"{path}/{tag:04x}", depth+1)
            nxt = off + 2 + 12*n; off = struct.unpack(E+"I", d[nxt:nxt+4])[0] if nxt + 4 <= len(d) else 0
            path = path + "+"
    walk(struct.unpack(E+"I", d[4:8])[0], "ifd0")
    return out
def main():
    a, b = tags(sys.argv[1]), tags(sys.argv[2])
    for k in sorted(set(a) | set(b)):
        if k not in b: print("only-a", k, a[k])
        elif k not in a: print("only-b", k, b[k])
        elif a[k] != b[k]: print("changed", k, a[k], "->", b[k])
if __name__ == "__main__":
    main()
