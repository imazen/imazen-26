#!/usr/bin/env python3
"""Re-run the camera-class metadata whitelist from the oldest copies, keeping colour and HDR.

The 2026-08 whitelist rewrite of the four camera classes (1000/1200/1400/1600) met its
privacy goal but damaged colour and HDR signalling: it emptied or swapped HEIC `colr`
properties, removed the UltraHDR gain maps, and removed the Apple MakerNote that legacy
Apple gain maps need (benchmarks/metadata_audit_earlier_copies_2026-09-25.md). This
script applies the same policy (STORAGE-MAP.md) to the oldest copy of each file with
container-aware code, so everything that carries colour or HDR survives and nothing
else from the original does.

Kept, per the published policy:
  Exif IFD0   Make, Model, Orientation, X/YResolution, ResolutionUnit, DateTime,
              YCbCrPositioning
  Exif IFD    ExposureTime, FNumber, ExposureProgram, ISO, ExifVersion,
              DateTimeOriginal/Digitized, SubSecTime/Original/Digitized,
              ComponentsConfiguration, ShutterSpeedValue, ApertureValue,
              ExposureBiasValue, MeteringMode, Flash, FocalLength, FlashpixVersion,
              ColorSpace, WhiteBalance, FocalLengthIn35mmFilm, LensSpecification,
              LensMake, LensModel
  ICC profiles (every one, in every item)
Kept because they carry colour or HDR:
  Interop IFD (InteropIndex `R98` = DCF sRGB, InteropVersion)
  Apple MakerNote reduced to HDRImageType, HDRHeadroom, HDRGain (0x000A/0x0021/0x0030):
    the gain-map parameters of Apple HEICs without an ISO 21496-1 `tmap`
  JPEG: APP0 JFIF; for UltraHDR, the container XMP, the ISO 21496-1 APP2, an MPF APP2
    rebuilt from scratch (no ImageUIDList), and the gain-map JPEG verbatim
  HEIC: every item and property as the camera wrote it (`colr`, `auxC`, `tmap`, grids,
    auxiliary images and their XMP, Apple style metadata), `mpvd` motion-photo video
Removed:
  GPS IFD, IFD1 thumbnail, OffsetTime*, ImageUniqueID, serial numbers, HostComputer,
  Software, every other MakerNote tag, vendor APPn segments (APP4/5/6/13), COM,
  Samsung SEF trailers (MCC country code, UTC time), MPF thumbnails (GoPro), the primary
  HEIC XMP (replaced by an empty packet; it held face/pet regions and tool versions),
  PNG data after IEND. DNGs are not handled here.

Every output is checked before it is written:
  - the coded image data equals the source's (JPEG scan data, PNG IDAT, HEIC items);
  - HEIC item properties equal the source's, and every item's data except Exif and the
    replaced XMP equals the source's;
  - Exif carries only whitelisted tags;
  - no byte window taken from anything removed (dropped tag values, GPS IFD, MakerNote,
    SEF trailer, vendor segments, replaced XMP) occurs in the output.

Usage: whitelist_v2.py <sources.tsv> <out-dir>
  sources.tsv: id, ext, source_generation, source, canonical (one row per camera file)
Writes <out-dir>/<class>/<corpus name>, <out-dir>/manifest.tsv, <out-dir>/SHA256SUMS.
"""
import csv
import hashlib
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "metadata-loss-audit"))
from heif_props import props_from_bytes  # noqa: E402

# ── policy ────────────────────────────────────────────────────────────────────────────

KEEP_IFD0 = {0x010F, 0x0110, 0x0112, 0x011A, 0x011B, 0x0128, 0x0132, 0x0213}
KEEP_EXIF = {0x829A, 0x829D, 0x8822, 0x8827, 0x9000, 0x9003, 0x9004, 0x9101, 0x9201,
             0x9202, 0x9204, 0x9207, 0x9209, 0x920A, 0x9290, 0x9291, 0x9292, 0xA000,
             0xA001, 0xA403, 0xA405, 0xA432, 0xA433, 0xA434}
KEEP_INTEROP = {0x0001, 0x0002}
APPLE_HDR_TAGS = {0x000A, 0x0021, 0x0030}
TAG_EXIF, TAG_GPS, TAG_INTEROP, TAG_MAKERNOTE = 0x8769, 0x8825, 0xA005, 0x927C
TIFF_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
XMP_NS = b"http://ns.adobe.com/xap/1.0/\x00"
ISO_NS = b"urn:iso:std:iso:ts:21496:-1\x00"
UHDR_XMP_PREFIXES = {b"x", b"rdf", b"Container", b"Item", b"hdrgm"}
MOTION_XMP_PREFIXES = {b"x", b"rdf", b"Container", b"Item", b"GCamera"}
EMPTY_XMP = (b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
             b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
             b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></x:xmpmeta>'
             b'<?xpacket end="w"?>')


# outputs are candidates: they may only be written under these roots, never beside an input
OUTPUT_ROOTS = ["~/tmp", "/mnt/v/output/imazen-26-variants"]


class Reject(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ── TIFF / Exif ───────────────────────────────────────────────────────────────────────

def read_ifd(t, e, off):
    """[(tag, type, count, value bytes)] of the IFD at `off`, and the next-IFD offset."""
    if off + 2 > len(t):
        raise Reject(f"IFD offset {off} outside the TIFF")
    n = struct.unpack(e + "H", t[off:off + 2])[0]
    out = []
    for k in range(n):
        p = off + 2 + 12 * k
        tag, typ, cnt = struct.unpack(e + "HHI", t[p:p + 8])
        size = TIFF_SIZES.get(typ, 1) * cnt
        if size <= 4:
            raw = t[p + 8:p + 8 + size]
        else:
            vo = struct.unpack(e + "I", t[p + 8:p + 12])[0]
            raw = t[vo:vo + size]
        out.append((tag, typ, cnt, raw))
    nxt = struct.unpack(e + "I", t[off + 2 + 12 * n:off + 6 + 12 * n])[0]
    return out, nxt


def ptr(e, entries, tag):
    return next((struct.unpack(e + "I", raw[:4])[0] for tg, _, _, raw in entries if tg == tag), None)


def ifd_bytes(e, entries, at):
    """Serialize an IFD placed at offset `at`, its out-of-line values right after it."""
    entries = sorted(entries)
    data_at = at + 2 + 12 * len(entries) + 4
    head, data = struct.pack(e + "H", len(entries)), b""
    for tag, typ, cnt, raw in entries:
        if len(raw) <= 4:
            head += struct.pack(e + "HHI", tag, typ, cnt) + raw.ljust(4, b"\0")
        else:
            head += struct.pack(e + "HHII", tag, typ, cnt, data_at + len(data))
            data += raw + (b"\0" if len(raw) & 1 else b"")
    return head + b"\0\0\0\0" + data


def ifd_size(entries):
    return 2 + 12 * len(entries) + 4 + sum(len(r) + (len(r) & 1) for _, _, _, r in entries if len(r) > 4)


def apple_hdr_makernote(raw):
    """Reduce an Apple MakerNote to its HDR tags; None if it isn't Apple or has none."""
    if raw[:10] != b"Apple iOS\0" or raw[12:14] not in (b"MM", b"II"):
        return None
    me = ">" if raw[12:14] == b"MM" else "<"
    body = raw[12:]
    ifd = struct.unpack(me + "I", body[4:8])[0] if struct.unpack(me + "H", body[2:4])[0] == 42 else 2
    n = struct.unpack(me + "H", body[ifd:ifd + 2])[0]
    found = []
    for k in range(n):
        p = ifd + 2 + 12 * k
        tag, typ, cnt = struct.unpack(me + "HHI", body[p:p + 8])
        if tag not in APPLE_HDR_TAGS:
            continue
        size = TIFF_SIZES.get(typ, 1) * cnt
        if size <= 4:
            value = body[p + 8:p + 8 + size]
        else:
            vo = struct.unpack(me + "I", body[p + 8:p + 12])[0]  # relative to the MakerNote start
            value = raw[vo:vo + size]
        found.append((tag, typ, cnt, value))
    if not found:
        return None
    # header, then an IFD in Apple's layout (count right after the byte-order mark),
    # out-of-line values addressed from the MakerNote start
    head = b"Apple iOS\0" + raw[10:12] + raw[12:14]
    data_pos = len(head) + 2 + 12 * len(found) + 4
    ifdb, data = struct.pack(me + "H", len(found)), b""
    for tag, typ, cnt, value in sorted(found):
        if len(value) <= 4:
            ifdb += struct.pack(me + "HHI", tag, typ, cnt) + value.ljust(4, b"\0")
        else:
            ifdb += struct.pack(me + "HHII", tag, typ, cnt, data_pos + len(data))
            data += value + (b"\0" if len(value) & 1 else b"")
    return head + ifdb + b"\0\0\0\0" + data


def whitelist_tiff(t):
    """(new TIFF, [removed value bytes]) with only whitelisted tags; same byte order."""
    if t[:4] not in (b"II*\0", b"MM\0*"):
        raise Reject("Exif is not a TIFF")
    e = "<" if t[:2] == b"II" else ">"
    ifd0, _ = read_ifd(t, e, struct.unpack(e + "I", t[4:8])[0])
    removed = []
    keep0 = [x for x in ifd0 if x[0] in KEEP_IFD0]
    removed += [x[3] for x in ifd0 if x[0] not in KEEP_IFD0 | {TAG_EXIF}]
    gps = ptr(e, ifd0, TAG_GPS)
    if gps is not None:
        removed += [x[3] for x in read_ifd(t, e, gps)[0]]
    keepx, keepi = [], []
    exif = ptr(e, ifd0, TAG_EXIF)
    if exif is not None:
        ents, _ = read_ifd(t, e, exif)
        keepx = [x for x in ents if x[0] in KEEP_EXIF]
        removed += [x[3] for x in ents if x[0] not in KEEP_EXIF | {TAG_INTEROP}]
        mn = next((x for x in ents if x[0] == TAG_MAKERNOTE), None)
        if mn is not None:
            reduced = apple_hdr_makernote(mn[3])
            if reduced:
                keepx.append((TAG_MAKERNOTE, 7, len(reduced), reduced))
        io = ptr(e, ents, TAG_INTEROP)
        if io is not None:
            iv, _ = read_ifd(t, e, io)
            keepi = [x for x in iv if x[0] in KEEP_INTEROP]
            removed += [x[3] for x in iv if x[0] not in KEEP_INTEROP]
    # layout: header, IFD0, Exif IFD, Interop IFD
    ifd0_at = 8
    n0 = keep0 + ([(TAG_EXIF, 4, 1, b"\0" * 4)] if exif is not None else [])
    exif_at = ifd0_at + ifd_size(n0)
    nx = keepx + ([(TAG_INTEROP, 4, 1, b"\0" * 4)] if keepi else [])
    io_at = exif_at + ifd_size(nx)
    n0 = keep0 + ([(TAG_EXIF, 4, 1, struct.pack(e + "I", exif_at))] if exif is not None else [])
    nx = keepx + ([(TAG_INTEROP, 4, 1, struct.pack(e + "I", io_at))] if keepi else [])
    out = t[:4] + struct.pack(e + "I", ifd0_at) + ifd_bytes(e, n0, ifd0_at)
    if exif is not None:
        out += ifd_bytes(e, nx, exif_at)
    if keepi:
        out += ifd_bytes(e, keepi, io_at)
    return out, removed


def tiff_tag_paths(t):
    e = "<" if t[:2] == b"II" else ">"
    ifd0, nxt = read_ifd(t, e, struct.unpack(e + "I", t[4:8])[0])
    paths = [("ifd0", x[0]) for x in ifd0]
    if nxt:
        paths.append(("ifd1", 0))
    exif = ptr(e, ifd0, TAG_EXIF)
    if exif is not None:
        ents, _ = read_ifd(t, e, exif)
        paths += [("exif", x[0]) for x in ents]
        io = ptr(e, ents, TAG_INTEROP)
        if io is not None:
            paths += [("interop", x[0]) for x in read_ifd(t, e, io)[0]]
    return paths


def check_whitelisted(t):
    allowed = {("ifd0", x) for x in KEEP_IFD0 | {TAG_EXIF}} | {("exif", x) for x in KEEP_EXIF | {TAG_INTEROP, TAG_MAKERNOTE}} \
        | {("interop", x) for x in KEEP_INTEROP}
    bad = [p for p in tiff_tag_paths(t) if p not in allowed]
    if bad:
        raise Reject(f"non-whitelisted tags remain: {bad[:5]}")


# ── JPEG ──────────────────────────────────────────────────────────────────────────────

def jpeg_markers(d, pos=2):
    """[(marker, start, end)] from `pos` through EOI; entropy data is skipped."""
    out = []
    while pos + 2 <= len(d):
        if d[pos] != 0xFF:
            raise Reject(f"expected a marker at {pos}")
        m = d[pos + 1]
        if m == 0xFF:
            pos += 1
            continue
        if m == 0xD9:
            out.append((m, pos, pos + 2))
            return out
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            pos += 2
            continue
        end = pos + 2 + struct.unpack(">H", d[pos + 2:pos + 4])[0]
        out.append((m, pos, end))
        pos = end
        if m == 0xDA:
            while True:
                pos = d.find(b"\xff", pos)
                if pos < 0 or pos + 1 >= len(d):
                    raise Reject("entropy data runs off the end")
                nb = d[pos + 1]
                if nb == 0x00 or 0xD0 <= nb <= 0xD7 or nb == 0xFF:
                    pos += 2 if nb != 0xFF else 1
                    continue
                break
    raise Reject("EOI not found")


def xmp_prefixes(x):
    import re
    return set(re.findall(rb"xmlns:([A-Za-z0-9_]+)=", x))


def mpf_parse(p):
    t = p[4:]
    e = "<" if t[:2] == b"II" else ">"
    ents, _ = read_ifd(t, e, struct.unpack(e + "I", t[4:8])[0])
    raw = next((x[3] for x in ents if x[0] == 0xB002), None)
    if raw is None:
        raise Reject("MPF without MP entries")
    return e, [struct.unpack(e + "IIIHH", raw[16 * j:16 * j + 16]) for j in range(len(raw) // 16)]


def mpf_build(e, entries):
    """APP2 MPF segment with MPFVersion, NumberOfImages and MPEntry only."""
    n = len(entries)
    ifd_at = 8
    tags = [(0xB000, 7, 4, b"0100"), (0xB001, 4, 1, struct.pack(e + "I", n)), (0xB002, 7, 16 * n, b"")]
    data_at = ifd_at + 2 + 12 * len(tags) + 4
    table = b"".join(struct.pack(e + "IIIHH", *x) for x in entries)
    head = struct.pack(e + "H", len(tags))
    for tag, typ, cnt, raw in tags:
        if tag == 0xB002:
            head += struct.pack(e + "HHII", tag, typ, cnt, data_at)
        else:
            head += struct.pack(e + "HHI", tag, typ, cnt) + raw.ljust(4, b"\0")
    tiff = (b"II*\0" if e == "<" else b"MM\0*") + struct.pack(e + "I", ifd_at) + head + b"\0\0\0\0" + table
    body = b"MPF\0" + tiff
    return b"\xff\xe2" + struct.pack(">H", len(body) + 2) + body


def rewrite_jpeg(d):
    if d[:2] != b"\xff\xd8":
        raise Reject("not a JPEG")
    marks = jpeg_markers(d)
    eoi = marks[-1][2]
    head_segs = []
    for m, s, e_ in marks:
        if 0xE0 <= m <= 0xEF or m == 0xFE:
            head_segs.append((m, s, e_))
        else:
            break
    body_start = head_segs[-1][2] if head_segs else 2
    if any(0xE0 <= m <= 0xEF or m == 0xFE for m, st, _ in marks if st >= body_start):
        raise Reject("APPn/COM inside the image body")
    body = d[body_start:eoi]
    pay = lambda seg: d[seg[1] + 4:seg[2]]
    xmp = [s for s in head_segs if s[0] == 0xE1 and pay(s).startswith(XMP_NS)]
    iso = [s for s in head_segs if s[0] == 0xE2 and pay(s).startswith(ISO_NS)]
    mpf = [s for s in head_segs if s[0] == 0xE2 and pay(s).startswith(b"MPF\0")]
    uhdr = bool(xmp) and b"hdrgm" in pay(xmp[0]) and len(iso) == 1 and len(mpf) == 1
    removed, gm = [], None
    if uhdr:
        e, ents = mpf_parse(pay(mpf[0]))
        if len(ents) != 2:
            raise Reject(f"UltraHDR MPF lists {len(ents)} images")
        at = mpf[0][1] + 8 + ents[1][2]
        gm = d[at:at + ents[1][1]]
        gmarks = jpeg_markers(gm)
        for m, s, e2 in gmarks:
            if 0xE0 <= m <= 0xEF or m == 0xFE:
                p = gm[s + 4:e2]
                ok = (m == 0xE0 and p.startswith(b"JFIF\0")) or (m == 0xE1 and p.startswith(XMP_NS)) \
                    or (m == 0xE2 and (p.startswith(ISO_NS) or p.startswith(b"MPF\0")))
                if not ok:
                    raise Reject(f"gain-map JPEG carries APP{m - 0xE0:X}/COM")
                if m == 0xE1 and not xmp_prefixes(p) <= UHDR_XMP_PREFIXES:
                    raise Reject("gain-map XMP has unexpected namespaces")
        if not xmp_prefixes(pay(xmp[0])) <= UHDR_XMP_PREFIXES:
            raise Reject(f"UltraHDR XMP has unexpected namespaces {xmp_prefixes(pay(xmp[0]))}")
    out_segs, mpf_slot, kept = [], None, [body]
    for seg in head_segs:
        m, p = seg[0], pay(seg)
        if m == 0xE0 and p.startswith(b"JFIF\0"):
            out_segs.append(d[seg[1]:seg[2]])
        elif m == 0xE1 and p.startswith(b"Exif\0\0"):
            t, rem = whitelist_tiff(p[6:])
            removed += rem
            body_ = b"Exif\0\0" + t
            kept.append(t)
            out_segs.append(b"\xff\xe1" + struct.pack(">H", len(body_) + 2) + body_)
        elif m == 0xE2 and p.startswith(b"ICC_PROFILE\0"):
            out_segs.append(d[seg[1]:seg[2]])
        elif uhdr and seg in xmp:
            out_segs.append(d[seg[1]:seg[2]])
        elif uhdr and seg in iso:
            out_segs.append(d[seg[1]:seg[2]])
        elif uhdr and seg in mpf:
            mpf_slot = len(out_segs)
            out_segs.append(None)
        else:
            removed.append(p)
    trailer = d[eoi:]
    if uhdr:
        e, ents = mpf_parse(pay(mpf[0]))
        mpf_len = len(mpf_build(e, [(0, 0, 0, 0, 0)] * 2))
        pre = 2 + sum(len(s) for s in out_segs[:mpf_slot])
        primary_len = 2 + sum(len(s) for s in out_segs if s) + mpf_len + len(body)
        tiff_pos = pre + 8
        new = [(ents[0][0], primary_len, 0, ents[0][3], ents[0][4]),
               (ents[1][0], len(gm), primary_len - tiff_pos, ents[1][3], ents[1][4])]
        out_segs[mpf_slot] = mpf_build(e, new)
        start = mpf[0][1] + 8 + ents[1][2]
        trailer = d[eoi:start] + d[start + len(gm):]
    removed.append(trailer)
    out = b"\xff\xd8" + b"".join(out_segs) + body + (gm or b"")
    kept += [s_ for s_ in out_segs] + ([gm] if gm else [])
    return out, removed, kept, {"uhdr": int(uhdr)}


# ── HEIF ──────────────────────────────────────────────────────────────────────────────

def boxes(d, s, e):
    while s + 8 <= e:
        sz, ty = struct.unpack(">I4s", d[s:s + 8])
        hdr = 8
        if sz == 1:
            sz = struct.unpack(">Q", d[s + 8:s + 16])[0]
            hdr = 16
        elif sz == 0:
            sz = e - s
        if sz < hdr:
            raise Reject("bad box size")
        yield ty.decode("latin1"), s, s + hdr, s + sz
        s += sz


def box(ty, payload):
    return struct.pack(">I4s", len(payload) + 8, ty.encode()) + payload


def parse_iloc(d, b):
    q = b[2]
    v = d[q]
    flags = d[q + 1:q + 4]
    q += 4
    osz, lsz = d[q] >> 4, d[q] & 15
    bsz = d[q + 1] >> 4
    isz = (d[q + 1] & 15) if v in (1, 2) else 0
    q += 2
    w = 2 if v < 2 else 4
    n = int.from_bytes(d[q:q + w], "big")
    q += w
    rd = lambda pos, k: int.from_bytes(d[pos:pos + k], "big") if k else 0
    items = []
    for _ in range(n):
        iid = int.from_bytes(d[q:q + w], "big")
        q += w
        method = 0
        if v in (1, 2):
            method = struct.unpack(">H", d[q:q + 2])[0] & 15
            q += 2
        dref = struct.unpack(">H", d[q:q + 2])[0]
        q += 2
        base = rd(q, bsz)
        q += bsz
        ec = struct.unpack(">H", d[q:q + 2])[0]
        q += 2
        ext, lpos = [], []
        for _ in range(ec):
            idx = rd(q, isz)
            q += isz
            off = rd(q, osz)
            q += osz
            ln = rd(q, lsz)
            lpos.append((q, lsz))
            q += lsz
            ext.append((idx, off, ln))
        items.append(dict(id=iid, method=method, dref=dref, base=base, ext=ext, lpos=lpos))
    return v, flags, items


def heif_info(d):
    top = list(boxes(d, 0, len(d)))
    meta = next(b for b in top if b[0] == "meta")
    kids = list(boxes(d, meta[2] + 4, meta[3]))
    kd = {k[0]: k for k in kids}
    iinf = kd["iinf"]
    v = d[iinf[2]]
    q0 = iinf[2] + 4 + (2 if v == 0 else 4)
    types = {}
    for _, _, bs, _ in boxes(d, q0, iinf[3]):
        v2 = d[bs]
        q = bs + 4
        w = 2 if v2 < 3 else 4
        iid = int.from_bytes(d[q:q + w], "big")
        q += w + 2
        types[iid] = d[q:q + 4].decode("latin1")
    v_, flags, items = parse_iloc(d, kd["iloc"])
    idat = kd.get("idat")
    data = {}
    for it in items:
        if it["dref"] != 0:
            raise Reject("item data in another file")
        parts = []
        for _, off, ln in it["ext"]:
            if it["method"] == 0:
                a = it["base"] + off
                parts.append(d[a:a + ln] if ln else d[a:])
            elif it["method"] == 1:
                a = idat[2] + it["base"] + off
                parts.append(d[a:a + ln])
            else:
                raise Reject("item construction method 2")
        data[it["id"]] = b"".join(parts)
    pitm = kd["pitm"]
    pv = d[pitm[2]]
    primary = int.from_bytes(d[pitm[2] + 4:pitm[2] + (6 if pv == 0 else 8)], "big")
    cdsc = {}
    if "iref" in kd:
        ir = kd["iref"]
        w = 2 if d[ir[2]] == 0 else 4
        for ty, _, bs, _ in boxes(d, ir[2] + 4, ir[3]):
            f = int.from_bytes(d[bs:bs + w], "big")
            n = struct.unpack(">H", d[bs + w:bs + w + 2])[0]
            to = [int.from_bytes(d[bs + w + 2 + w * i:bs + w + 4 + w * i], "big") for i in range(n)]
            if ty == "cdsc":
                cdsc[f] = to
    return dict(top=top, meta=meta, kids=kids, types=types, iloc=(v_, flags, items),
                data=data, primary=primary, cdsc=cdsc)


def padded_xmp(length):
    """An empty XMP packet padded with whitespace to exactly `length` bytes."""
    head, tail = EMPTY_XMP.split(b'<?xpacket end="w"?>')[0], b'<?xpacket end="w"?>'
    pad = length - len(head) - len(tail)
    if pad < 1:
        raise Reject("primary XMP slot too small for an empty packet")
    body = b"\n" + b" " * (pad - 1)
    return head + body + tail


def rewrite_heic(d):
    """Whitelist a HEIF in place: nothing moves; metadata slots are rewritten or zeroed."""
    h = heif_info(d)
    out = bytearray(d)
    removed, slots, changed = [], [], []
    v, flags, items = h["iloc"]
    by_id = {it["id"]: it for it in items}

    def file_extent(iid):
        it = by_id[iid]
        if it["method"] != 0 or len(it["ext"]) != 1 or it["ext"][0][2] == 0:
            raise Reject(f"item {iid} is not a single file extent")
        a = it["base"] + it["ext"][0][1]
        return a, a + it["ext"][0][2], it

    for iid, ty in h["types"].items():
        if ty == "Exif":
            a, b, it = file_extent(iid)
            x = d[a:b]
            skip = 4 + struct.unpack(">I", x[:4])[0]
            t, rem = whitelist_tiff(x[skip:])
            removed += rem + [x]
            new = x[:skip] + t
            if len(new) > len(x):
                raise Reject("whitelisted Exif is larger than the original")
            out[a:b] = new + b"\0" * (len(x) - len(new))
            lp, lsz = it["lpos"][0]
            out[lp:lp + lsz] = len(new).to_bytes(lsz, "big")
            slots += [(a, b), (lp, lp + lsz)]
            changed.append(iid)
        elif ty == "mime" and h["primary"] in h["cdsc"].get(iid, []):
            a, b, _ = file_extent(iid)
            x = d[a:b]
            if b"GCamera:MotionPhoto" in x:
                if not xmp_prefixes(x) <= MOTION_XMP_PREFIXES:
                    raise Reject(f"motion-photo XMP has unexpected namespaces {xmp_prefixes(x)}")
                continue  # structural: primary/video lengths, unchanged because nothing moves
            removed.append(x)
            out[a:b] = padded_xmp(len(x))
            slots.append((a, b))
            changed.append(iid)
    for ty, s0, bs, e in h["top"]:
        if ty in ("ftyp", "meta", "mdat", "mpvd"):
            continue
        if ty in ("sefd", "free", "skip"):
            removed.append(d[bs:e])
            out[s0 + 4:s0 + 8] = b"free"
            out[bs:e] = b"\0" * (e - bs)
            slots.append((s0 + 4, e))
        else:
            raise Reject(f"unexpected top-level box {ty}")
    # every other extent must stay clear of the rewritten slots
    for it in items:
        if it["id"] in changed or it["method"] != 0:
            continue
        for _, off, ln in it["ext"]:
            a = it["base"] + off
            if any(a < sb and (a + ln if ln else len(d)) > sa for sa, sb in slots):
                raise Reject(f"item {it['id']} overlaps a rewritten slot")
    out = bytes(out)
    kept = [out[a:b] for a, b in slots] + [d[bs:e] for ty, _, bs, e in h["top"] if ty in ("ftyp", "meta")]
    # kept: everything outside the slots is the source's own bytes
    edges = sorted(slots)
    outside, pos = [], 0
    for a, b in edges:
        outside.append(d[pos:a])
        pos = max(pos, b)
    outside.append(d[pos:])
    return out, removed, kept + outside, {"rewritten_items": "+".join(map(str, sorted(changed))), "slots": edges}


# ── PNG ───────────────────────────────────────────────────────────────────────────────

def png_chunks(d):
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise Reject("not a PNG")
    pos, out = 8, []
    while pos + 12 <= len(d):
        ln, ty = struct.unpack(">I4s", d[pos:pos + 8])
        out.append((ty, d[pos + 8:pos + 8 + ln], pos, pos + 12 + ln))
        pos += 12 + ln
        if ty == b"IEND":
            break
    return out, pos


def rewrite_png(d):
    chunks, end = png_chunks(d)
    out, removed = d[:8], [d[end:]]
    kept = []
    for ty, data, s, e in chunks:
        if ty == b"eXIf":
            t, rem = whitelist_tiff(data)
            removed += rem
            out += struct.pack(">I", len(t)) + ty + t + struct.pack(">I", zlib.crc32(ty + t) & 0xFFFFFFFF)
            kept.append(t)
        elif ty in (b"tEXt", b"iTXt", b"zTXt", b"tIME"):
            removed.append(data)
        else:
            out += d[s:e]
            kept.append(d[s:e])
    return out, removed, kept, {}


# ── checks ────────────────────────────────────────────────────────────────────────────

def image_key(ext, d):
    if ext == ".jpg":
        marks = jpeg_markers(d)
        start = next(s for m, s, _ in marks if not (0xE0 <= m <= 0xEF or m == 0xFE))
        return sha(d[start:marks[-1][2]])
    if ext == ".png":
        chunks, _ = png_chunks(d)
        return sha(b"".join(c[1] for c in chunks if c[0] in (b"IHDR", b"IDAT", b"PLTE")))
    h = heif_info(d)
    return sha(b"".join(h["data"][i] for i in sorted(h["data"]) if h["types"][i] in ("hvc1", "av01", "grid", "tmap")))


def needles(blob, size=24, cap=64):
    """Distinctive byte strings to look for: the whole value if short, else up to `cap` windows."""
    if len(blob) < 8:
        return []
    if len(blob) <= size:
        return [blob] if len(set(blob)) >= 6 else []
    step = max(size, (len(blob) - size) // cap)
    out = []
    for i in range(0, len(blob) - size + 1, step):
        w = blob[i:i + size]
        if len(set(w)) >= 10:
            out.append(w)
    return out


def leak_check(out, removed, kept):
    for blob in removed:
        for w in needles(blob):
            if w in out and not any(w in k for k in kept):
                raise Reject(f"removed bytes survive in the output: {w[:16]!r}")


def exif_of(ext, d):
    if ext == ".jpg":
        for m, s, e in jpeg_markers(d):
            if m == 0xE1 and d[s + 4:s + 10] == b"Exif\0\0":
                return d[s + 10:e]
    elif ext == ".png":
        return next((c[1] for c in png_chunks(d)[0] if c[0] == b"eXIf"), None)
    else:
        h = heif_info(d)
        for iid, ty in h["types"].items():
            if ty == "Exif":
                x = h["data"][iid]
                return x[4 + struct.unpack(">I", x[:4])[0]:]
    return None


def verify(ext, src, out, removed, kept, notes):
    if image_key(ext, src) != image_key(ext, out):
        raise Reject("coded image data differs from the source")
    t = exif_of(ext, out)
    if t:
        check_whitelisted(t)
    if ext == ".heic":
        if len(src) != len(out):
            raise Reject("in-place HEIC changed length")
        slots = notes["slots"]
        step = 1 << 16
        for a in range(0, len(src), step):
            if src[a:a + step] != out[a:a + step]:
                for k in range(a, min(a + step, len(src))):
                    if src[k] != out[k] and not any(sa <= k < sb for sa, sb in slots):
                        raise Reject(f"byte {k} changed outside the metadata slots")
        if props_from_bytes(src) != props_from_bytes(out):
            raise Reject("item properties differ from the source")
        hs, ho = heif_info(src), heif_info(out)
        diff = [i for i in hs["data"] if hs["data"][i] != ho["data"].get(i)
                and hs["types"][i] not in ("Exif",) and not (hs["types"][i] == "mime" and hs["primary"] in hs["cdsc"].get(i, []))]
        if diff or set(hs["data"]) != set(ho["data"]):
            raise Reject(f"item data differs from the source on items {diff[:5]}")
    leak_check(out, removed, kept)


def input_guard(rows, out_dir):
    """Refuse an output directory that could touch an input; return input hashes."""
    out_real = os.path.realpath(out_dir)
    roots = [os.path.realpath(os.path.expanduser(x)) for x in OUTPUT_ROOTS]
    if not any(os.path.commonpath([out_real, r]) == r and out_real != r for r in roots):
        raise SystemExit(f"refusing: output dir must be inside one of {OUTPUT_ROOTS}")
    hashes = {}
    for r in rows:
        for k in ("source", "canonical"):
            p = os.path.realpath(r[k])
            top = os.path.dirname(os.path.dirname(p))  # the class directory's parent
            for a, b in ((out_real, top), (top, out_real)):
                if os.path.commonpath([a, b]) == b:
                    raise SystemExit(f"refusing: output dir {out_dir} overlaps input tree {top}")
            hashes[p] = sha(open(p, "rb").read())
    return hashes


def main():
    src_tsv, out_dir = sys.argv[1], sys.argv[2]
    rows = list(csv.DictReader(open(src_tsv), delimiter="\t"))
    before = input_guard(rows, out_dir)
    if os.path.exists(out_dir) and os.listdir(out_dir):
        raise SystemExit(f"refusing: {out_dir} is not empty (outputs are never overwritten)")
    os.makedirs(out_dir, exist_ok=True)
    man = open(os.path.join(out_dir, "manifest.tsv"), "w")
    man.write("id\tstatus\tsource_generation\tsource_sha256\tcanonical_sha256\toutput_sha256\tbytes\tnotes\toutput\n")
    sums, n_ok, n_fail = [], 0, 0
    for r in rows:
        ext = r["ext"]
        if ext == ".dng":
            continue
        src = open(r["source"], "rb").read()
        canon_sha = sha(open(r["canonical"], "rb").read())
        try:
            fn = {".jpg": rewrite_jpeg, ".heic": rewrite_heic, ".png": rewrite_png}[ext]
            out, removed, kept, notes = fn(src)
            verify(ext, src, out, removed, kept, notes)
        except Reject as ex:
            n_fail += 1
            man.write(f"{r['id']}\tFAILED: {ex}\t{r['source_generation']}\t{sha(src)}\t{canon_sha}\t\t\t\t\n")
            print(f"{r['id']} FAILED {ex}", file=sys.stderr)
            continue
        cls = os.path.basename(os.path.dirname(r["canonical"]))
        rel = os.path.join(cls, os.path.basename(r["canonical"]))
        os.makedirs(os.path.join(out_dir, cls), exist_ok=True)
        with open(os.path.join(out_dir, rel), "xb") as f:  # never overwrite
            f.write(out)
        n_ok += 1
        sums.append(f"{sha(out)}  {rel}\n")
        note = ",".join(f"{k}={v}" for k, v in notes.items() if k != "slots")
        man.write(f"{r['id']}\tok\t{r['source_generation']}\t{sha(src)}\t{canon_sha}\t{sha(out)}\t{len(out)}\t{note}\t{rel}\n")
    with open(os.path.join(out_dir, "SHA256SUMS"), "w") as f:
        f.writelines(sums)
    after = {p: sha(open(p, "rb").read()) for p in before}
    moved = [p for p in before if before[p] != after[p]]
    print(f"{n_ok} written, {n_fail} failed; inputs re-hashed: {len(before) - len(moved)} unchanged, {len(moved)} changed")
    if moved:
        raise SystemExit(f"INPUT FILES CHANGED: {moved[:5]}")


if __name__ == "__main__":
    main()
