"""Walk roots; for every PNG record dims and which colour chunks it has (reads chunk headers only)."""
import os, sys, struct
COL = {b"iCCP", b"sRGB", b"gAMA", b"cHRM", b"cICP", b"mDCV", b"cLLI"}
def scan(p):
    with open(p, "rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n": return None
        found = []; ihdr = None
        while True:
            h = f.read(8)
            if len(h) < 8: break
            ln, ty = struct.unpack(">I4s", h)
            if ty == b"IHDR": ihdr = f.read(13); f.seek(4, 1); continue
            if ty in COL: found.append(ty.decode())
            if ty in (b"IDAT", b"IEND"): break
            f.seek(ln + 4, 1)
    w, hh, bd, ct = struct.unpack(">IIBB", ihdr[:10]) if ihdr else (0, 0, 0, 0)
    return w, hh, bd, ct, ",".join(found)
for root in sys.argv[1:]:
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in ("target", ".git", "node_modules")]
        for n in fn:
            if n.lower().endswith(".png"):
                p = os.path.join(dp, n)
                try: r = scan(p)
                except Exception as e: r = None
                if r: print(f"{p}\t{os.path.getsize(p)}\t{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\t{r[4]}", flush=True)
