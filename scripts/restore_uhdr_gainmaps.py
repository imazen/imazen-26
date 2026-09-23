#!/usr/bin/env python3
"""Build restore candidates for the UltraHDR JPEGs whose gain maps the metadata rewrite removed.

The canonical camera JPEGs went through a whitelist metadata rewrite that kept the image
data byte-identical but dropped everything that makes a file UltraHDR: the MPF and
ISO 21496-1 APP2 segments, the `hdrgm` container XMP, and the gain-map JPEG after the
primary EOI (benchmarks/jpeg_in_jxl_validation_2026-09-22.md, §HDR). This script
re-attaches those pieces from the pre-rewrite originals WITHOUT reintroducing anything
else from them:

    SOI
    canonical APPn segments, minus its XMP (whitelisted Exif, ICC)
    original primary XMP  (UltraHDR container directory only; checked)
    original ISO 21496-1 APP2 (version marker)
    original MPF APP2, sizes and offset recomputed for the new layout
    canonical image data, first table through EOI (byte-identical to the original's)
    original gain-map JPEG, verbatim (XMP hdrgm, ISO 21496-1, MPF, JFIF; no Exif)

The original's APP4 segment, its full Exif and the vendor trailer after the gain map are
not copied. Every candidate is re-parsed and checked before it is written;
a failed check skips the file and says why. Candidates go to --out-dir; the canonical
tree is only read. Replacing canonical files is an owner decision (it changes their
sha256) and is not done here.

Usage:
  scripts/restore_uhdr_gainmaps.py --out-dir /mnt/v/output/imazen-26-variants/uhdr-restore-candidates-2026-09-22
"""

import argparse
import csv
import hashlib
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
XMP_NS = b"http://ns.adobe.com/xap/1.0/\x00"
ISO_NS = b"urn:iso:std:iso:ts:21496:-1\x00"
LOCATION_WORDS = (b"GPS", b"Latitude", b"Longitude", b"Location", b"City", b"Country")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def segments(d: bytes):
    """Marker segments from SOI to the first non-APPn/COM marker: [(marker, start, end)], data_start."""
    out, pos = [], 2
    while pos + 4 <= len(d) and d[pos] == 0xFF:
        m = d[pos + 1]
        if not (0xE0 <= m <= 0xEF or m == 0xFE):
            return out, pos
        ln = struct.unpack(">H", d[pos + 2:pos + 4])[0]
        out.append((m, pos, pos + 2 + ln))
        pos += 2 + ln
    raise ValueError("no image data after the APPn segments")


def payload(d: bytes, seg) -> bytes:
    return d[seg[1] + 4:seg[2]]


def primary_end(d: bytes, pos: int) -> int:
    """Offset just past the primary image's EOI, walking markers from `pos`."""
    while pos + 2 <= len(d):
        if d[pos] != 0xFF:
            raise ValueError(f"expected a marker at offset {pos}")
        m = d[pos + 1]
        if m == 0xFF:  # fill byte
            pos += 1
            continue
        if m == 0xD9:
            return pos + 2
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            pos += 2
            continue
        pos += 2 + struct.unpack(">H", d[pos + 2:pos + 4])[0]
        if m == 0xDA:
            # entropy-coded data runs to the next marker that isn't stuffing, RSTn or fill
            while pos + 1 < len(d) and not (
                d[pos] == 0xFF and d[pos + 1] not in (0x00, 0xFF) and not 0xD0 <= d[pos + 1] <= 0xD7
            ):
                pos += 1
    raise ValueError("primary EOI not found")


def mpf_entries(seg_payload: bytes):
    """(endian, entry_table_offset_in_tiff, [(attr, size, offset, dep1, dep2)]) from an MPF payload."""
    t = seg_payload[4:]
    e = "<" if t[:2] == b"II" else ">"
    ifd = struct.unpack(e + "I", t[4:8])[0]
    n = struct.unpack(e + "H", t[ifd:ifd + 2])[0]
    for k in range(n):
        tag, typ, cnt, val = struct.unpack(e + "HHII", t[ifd + 2 + 12 * k:ifd + 14 + 12 * k])
        if tag == 0xB002:
            ents = [struct.unpack(e + "IIIHH", t[val + 16 * j:val + 16 * j + 16]) for j in range(cnt // 16)]
            return e, val, ents
    raise ValueError("MPF has no MP Entry tag")


def exif_has_gps(exif_payload: bytes) -> bool:
    t = exif_payload[6:]
    e = "<" if t[:2] == b"II" else ">"
    ifd = struct.unpack(e + "I", t[4:8])[0]
    n = struct.unpack(e + "H", t[ifd:ifd + 2])[0]
    return any(struct.unpack(e + "H", t[ifd + 2 + 12 * k:ifd + 4 + 12 * k])[0] == 0x8825 for k in range(n))


def build(canon: bytes, orig: bytes):
    csegs, cdata = segments(canon)
    osegs, odata = segments(orig)
    cend = primary_end(canon, cdata)
    oend = primary_end(orig, odata)
    if cend != len(canon):
        raise ValueError(f"canonical has {len(canon) - cend} bytes after EOI; expected none")
    image = canon[cdata:cend]
    if image != orig[odata:oend]:
        raise ValueError("image data differs between canonical and original")

    oxmp = [s for s in osegs if s[0] == 0xE1 and payload(orig, s).startswith(XMP_NS)]
    oiso = [s for s in osegs if s[0] == 0xE2 and payload(orig, s).startswith(ISO_NS)]
    ompf = [s for s in osegs if s[0] == 0xE2 and payload(orig, s).startswith(b"MPF\x00")]
    if len(oxmp) != 1 or len(oiso) != 1 or len(ompf) != 1:
        raise ValueError(f"original lacks a single XMP/ISO/MPF segment ({len(oxmp)}/{len(oiso)}/{len(ompf)})")
    xmp = orig[oxmp[0][1]:oxmp[0][2]]
    if b"hdrgm:Version" not in xmp or b'Item:Semantic="GainMap"' not in xmp:
        raise ValueError("original XMP is not an UltraHDR container directory")
    if any(w in xmp for w in LOCATION_WORDS):
        raise ValueError("original XMP mentions location; refusing to copy it")

    # gain map: MPF entry 1, which must start right after the primary EOI
    e, table, ents = mpf_entries(payload(orig, ompf[0]))
    if len(ents) != 2:
        raise ValueError(f"original MPF lists {len(ents)} images, expected 2")
    tiff_orig = ompf[0][1] + 8
    gm_start = tiff_orig + ents[1][2]
    if gm_start != oend:
        raise ValueError("gain map doesn't start at the primary EOI")
    gm = orig[gm_start:gm_start + ents[1][1]]
    if not (gm.startswith(b"\xff\xd8") and gm.endswith(b"\xff\xd9")):
        raise ValueError("gain-map range isn't a complete JPEG")
    gsegs, _ = segments(gm)
    if any(s[0] == 0xE1 and payload(gm, s).startswith(b"Exif\x00\x00") for s in gsegs):
        raise ValueError("gain-map JPEG carries Exif; refusing to copy it")
    if any(w in gm[:gsegs[-1][2]] for w in LOCATION_WORDS):
        raise ValueError("gain-map metadata mentions location; refusing to copy it")
    if f'Item:Length="{len(gm)}"'.encode() not in xmp:
        raise ValueError("XMP Item:Length doesn't match the gain map")

    keep = [canon[s[1]:s[2]] for s in csegs
            if not (s[0] == 0xE1 and payload(canon, s).startswith(XMP_NS))]
    head = bytearray(b"\xff\xd8" + b"".join(keep) + xmp + orig[oiso[0][1]:oiso[0][2]])
    mpf_pos = len(head)
    mpf = bytearray(orig[ompf[0][1]:ompf[0][2]])
    head += mpf
    primary_len = len(head) + len(image)
    tiff = mpf_pos + 8
    base = 8 + table  # entry table within the segment: FF E2, length, "MPF\0", then TIFF
    struct.pack_into(e + "I", head, mpf_pos + base + 4, primary_len)          # entry 0 size
    struct.pack_into(e + "I", head, mpf_pos + base + 16 + 4, len(gm))         # entry 1 size
    struct.pack_into(e + "I", head, mpf_pos + base + 16 + 8, primary_len - tiff)  # entry 1 offset
    out = bytes(head) + image + gm

    # re-parse and check what was built
    rsegs, rdata = segments(out)
    if out[rdata:primary_end(out, rdata)] != image or primary_end(out, rdata) != primary_len:
        raise ValueError("rebuilt primary doesn't end where expected")
    rexif = [payload(out, s) for s in rsegs if s[0] == 0xE1 and payload(out, s).startswith(b"Exif\x00\x00")]
    cexif = [payload(canon, s) for s in csegs if s[0] == 0xE1 and payload(canon, s).startswith(b"Exif\x00\x00")]
    if rexif != cexif:
        raise ValueError("Exif differs from the canonical file")
    if any(exif_has_gps(x) for x in rexif):
        raise ValueError("Exif carries a GPS IFD")
    rmpf = [s for s in rsegs if s[0] == 0xE2 and payload(out, s).startswith(b"MPF\x00")][0]
    _, _, rents = mpf_entries(payload(out, rmpf))
    at = rmpf[1] + 8 + rents[1][2]
    if rents[0][1] != primary_len or out[at:at + rents[1][1]] != gm or at + len(gm) != len(out):
        raise ValueError("rebuilt MPF doesn't locate the gain map")
    return out, gm, len(orig) - oend - len(gm)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus-root", type=Path, default=Path.home() / "work/codec-corpus/imazen-26")
    ap.add_argument("--originals-root", type=Path,
                    default=Path("/mnt/v/output/codec-corpus/lilith-photos-backup-2026-06-09"))
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    rows = []
    for bucket in ("train", "validate", "test"):
        with open(REPO / "manifests" / f"{bucket}.tsv", newline="") as f:
            rows += [r for r in csv.DictReader(f, delimiter="\t") if r["format"] == "jpg"]
    report, failed = [], 0
    for r in sorted(rows, key=lambda r: r["id"]):
        opath = args.originals_root / r["path"]
        if not opath.exists():
            continue
        canon = (args.corpus_root / r["path"]).read_bytes()
        if sha(canon) != r["sha256"]:
            print(f"{r['id']}: canonical file doesn't match the manifest sha256", file=sys.stderr)
            failed += 1
            continue
        orig = opath.read_bytes()
        if b"hdrgm:Version" not in orig[:200_000]:
            continue  # original isn't UltraHDR
        try:
            out, gm, dropped_tail = build(canon, orig)
        except ValueError as e:
            print(f"{r['id']}: skipped: {e}", file=sys.stderr)
            failed += 1
            continue
        dest = args.out_dir / r["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(out)
        report.append({
            "id": r["id"], "path": r["path"], "split": r["split"],
            "canonical_sha256": r["sha256"], "canonical_bytes": len(canon),
            "original_sha256": sha(orig), "original_bytes": len(orig),
            "restored_sha256": sha(out), "restored_bytes": len(out),
            "gainmap_sha256": sha(gm), "gainmap_bytes": len(gm),
            "original_trailer_bytes_dropped": dropped_tail,
        })
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with open(args.out_dir / "restore_manifest.tsv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0]) if report else ["id"], delimiter="\t")
        w.writeheader()
        w.writerows(report)
    print(f"{len(report)} candidates written, {failed} skipped", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
