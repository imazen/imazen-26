#!/usr/bin/env python3
"""The export's byte-scan gate (EXPORT-PLAN.md, Gates): no nested media, no location data.

Scans every file's raw bytes, independent of any decoder, for:

  nested media  a JPEG stream (an SOI opening a real marker segment), PNG, GIF, RIFF/WebP
                or ISO BMFF `ftyp` signature anywhere but where the format puts its own;
                an embedded video's `mpvd`, `moov` or `mdat` box (in a HEIF, any top-level
                box but ftyp/meta/mdat/free/skip/idat)
  location      an EXIF GPS IFD pointer (tag 0x8825) in any TIFF header found in the file,
                QuickTime `©xyz` and 3GPP `loci` atoms with a plausible size, XMP/EXIF GPS
                field names, and ISO 6709 coordinate strings

Some nesting is the format's own and is expected: the gain-map JPEG an UltraHDR file's
MPF index lists (one extra SOI per MPF entry), a DNG's previews, and the images inside
a PDF. Everything else is a finding. A file with any finding fails the gate.

A finding listed for the file's id in manifests/byte_scan_allowlist.tsv (id, finding prefix,
reason) is reported as allowed and does not fail the gate.

Usage: byte_scan.py <tree> [--out byte_scan.tsv] [--allowlist FILE]   (exit 1 on any finding)
"""
import argparse
import os
import re
import struct
import sys

SIGS = {
    "png": re.compile(re.escape(b"\x89PNG\r\n\x1a\n")),
    "gif": re.compile(rb"GIF8[79]a"),
    "riff": re.compile(rb"RIFF....WEBP", re.S),
    "ftyp": re.compile(rb"ftyp(?:isom|mp4[12]|qt  |heic|heix|mif1|msf1|avif|M4V |3gp[0-9])"),
}
SOI = re.compile(rb"\xff\xd8\xff")
# Markers that may follow a JPEG's SOI, and that may follow its first segment.
FIRST_MARKERS = set(range(0xE0, 0xF0)) | {0xDB, 0xC4, 0xC0, 0xC1, 0xC2, 0xFE, 0xDD}
NEXT_MARKERS = FIRST_MARKERS | {0xDA}
VIDEO_BOXES = (b"mpvd", b"moov", b"mdat")
HEIF_TOP = {b"ftyp", b"meta", b"mdat", b"free", b"skip", b"idat"}
LOCATION = {
    "GPS field name": re.compile(rb"GPS(?:Latitude|Longitude|Altitude|Position|Coordinates|DestLatitude|DestLongitude)"),
    "ISO 6709 string": re.compile(rb"[+-][0-8]\d\.\d{3,}[+-](?:0\d\d|1[0-7]\d|180)\.\d{3,}"),
}


def jpeg_starts(d):
    """Offsets of SOIs that open a real marker segment followed by another marker."""
    out = []
    for m in SOI.finditer(d):
        p = m.start()
        if p + 6 > len(d) or d[p + 3] not in FIRST_MARKERS:
            continue
        ln = struct.unpack(">H", d[p + 4:p + 6])[0]
        q = p + 4 + ln
        if ln >= 2 and q + 1 < len(d) and d[q] == 0xFF and d[q + 1] in NEXT_MARKERS:
            out.append(p)
    return out


def atoms(d, name, min_size, max_size):
    """Offsets of `name` boxes whose size field is plausible."""
    out = []
    for m in re.finditer(re.escape(name), d):
        p = m.start() - 4
        if p >= 0:
            size = struct.unpack(">I", d[p:p + 4])[0]
            if min_size <= size <= min(max_size, len(d) - p):
                out.append(p)
    return out


def iso6709_after(d, at, span=64):
    return re.search(rb"[+-]\d", d[at:at + span]) is not None


def gps_pointers(d):
    """Offsets of TIFF headers in `d` whose IFD0 holds a GPS IFD pointer (0x8825)."""
    hits = []
    for m in re.finditer(rb"(?:II\*\x00|MM\x00\*)", d):
        t = m.start()
        e = "<" if d[t] == 0x49 else ">"
        try:
            ifd = t + struct.unpack(e + "I", d[t + 4:t + 8])[0]
            n = struct.unpack(e + "H", d[ifd:ifd + 2])[0]
            if n == 0 or n > 512:
                continue
            for i in range(n):
                tag = struct.unpack(e + "H", d[ifd + 2 + 12 * i:ifd + 4 + 12 * i])[0]
                if tag == 0x8825:
                    hits.append(t)
        except struct.error:
            continue
    return hits


def mpf_images(d):
    """Number of images an MPF index (APP2 "MPF\\0") lists, or 1 without one."""
    pos = 2
    while pos + 4 <= len(d) and d[pos] == 0xFF:
        m = d[pos + 1]
        if m in (0xDA, 0xD9):
            break
        ln = struct.unpack(">H", d[pos + 2:pos + 4])[0]
        if m == 0xE2 and d[pos + 4:pos + 8] == b"MPF\x00":
            t = pos + 8
            e = "<" if d[t] == 0x49 else ">"
            ifd = t + struct.unpack(e + "I", d[t + 4:t + 8])[0]
            n = struct.unpack(e + "H", d[ifd:ifd + 2])[0]
            for i in range(n):
                tag, _, _, value = struct.unpack(e + "HHII", d[ifd + 2 + 12 * i:ifd + 14 + 12 * i])
                if tag == 0xB001:  # NumberOfImages, a LONG held in the value field
                    return value
            return 1
        pos += 2 + ln
    return 1


def heif_top_boxes(d):
    out, pos = [], 0
    while pos + 8 <= len(d):
        size, ty = struct.unpack(">I4s", d[pos:pos + 8])
        if size == 1:
            size = struct.unpack(">Q", d[pos + 8:pos + 16])[0]
        elif size == 0:
            size = len(d) - pos
        if size < 8:
            out.append((pos, b"????"))
            break
        out.append((pos, ty))
        pos += size
    return out


def scan(path):
    d = open(path, "rb").read()
    ext = os.path.splitext(path)[1].lower()
    out = []
    if ext not in (".dng", ".pdf"):  # their previews and page images are the format's own
        own = {".png": "png", ".gif": "gif", ".webp": "riff", ".heic": "ftyp", ".avif": "ftyp"}.get(ext)
        for name, rx in SIGS.items():
            at = [m.start() for m in rx.finditer(d)]
            if name == own:
                at = [a for a in at if a != (4 if name == "ftyp" else 0)]
            if at:
                out.append(f"nested {name} at {at[:5]}")
        soi = jpeg_starts(d)
        expected = (mpf_images(d) if ext in (".jpg", ".jpeg") else 0)
        if len(soi) > expected:
            out.append(f"{len(soi) - expected} JPEG stream(s) beyond the expected {expected}, SOIs at {soi[:5]}")
        if ext in (".heic", ".avif"):
            for pos, ty in heif_top_boxes(d):
                if ty not in HEIF_TOP:
                    out.append(f"top-level {ty.decode('latin1')!r} box at {pos}")
        else:
            for box in VIDEO_BOXES:
                hits = atoms(d, box, 8, 1 << 40)
                if hits:
                    out.append(f"{box.decode()} box at {hits[:5]}")
    for t in gps_pointers(d):
        out.append(f"EXIF GPS pointer in the TIFF header at {t}")
    for p in atoms(d, b"\xa9xyz", 12, 512):
        if iso6709_after(d, p + 8):
            out.append(f"QuickTime \u00a9xyz location atom at {p}")
    for p in atoms(d, b"loci", 22, 4096):
        out.append(f"3GPP loci atom at {p}")
    for name, rx in LOCATION.items():
        m = rx.search(d)
        if m:
            out.append(f"{name} at {m.start()}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("--out", default="-")
    ap.add_argument("--allowlist", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "manifests", "byte_scan_allowlist.tsv"))
    a = ap.parse_args()
    allow = []
    with open(a.allowlist) as f:
        next(f)
        allow = [line.rstrip("\n").split("\t")[:2] for line in f if line.strip()]
    rows, bad, allowed = [], 0, 0
    for root, _, files in os.walk(a.tree):
        for f in sorted(files):
            if not re.match(r"\d{4,5}_", f):  # corpus ids, or export ids with the leading 1
                continue
            p = os.path.join(root, f)
            found, ok = [], []
            for x in scan(p):
                listed = any((f.startswith(i + "_") or f.startswith("1" + i + "_")) and x.startswith(pre)
                             for i, pre in allow)
                (ok if listed else found).append(x)
            bad += bool(found)
            allowed += len(ok)
            rows.append((os.path.relpath(p, a.tree), "; ".join(found), "; ".join(ok)))
    out = sys.stdout if a.out == "-" else open(a.out, "w")
    out.write("path\tfindings\tallowed\n")
    for p, f, ok in sorted(rows):
        if f or ok or a.out != "-":
            out.write(f"{p}\t{f}\t{ok}\n")
    print(f"{len(rows)} files scanned, {bad} with findings, {allowed} allowed findings", file=sys.stderr)
    if not rows:
        sys.exit("no image files found: nothing was scanned")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
