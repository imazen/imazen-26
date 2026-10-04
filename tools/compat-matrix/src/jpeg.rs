//! Byte-level JPEG segment tools: marker scan, APPn insertion/removal, and
//! MPF surgery — all on container bytes, never touching entropy-coded data.

/// One marker segment: (marker byte, start offset, end offset).
/// `start` points at 0xFF; for APPn/COM/etc `end` is one past the length
/// field's declared end. The SOS entry's `end` is the start of entropy data.
pub fn markers(d: &[u8]) -> Result<Vec<(u8, usize, usize)>, String> {
    if d.len() < 4 || d[0] != 0xFF || d[1] != 0xD8 {
        return Err("not a JPEG".into());
    }
    let mut out = Vec::new();
    let mut pos = 2usize;
    while pos + 2 <= d.len() {
        if d[pos] != 0xFF {
            return Err(format!("expected a marker at {pos:#x}"));
        }
        let m = d[pos + 1];
        if m == 0xFF {
            pos += 1;
            continue;
        }
        if m == 0xD9 {
            out.push((m, pos, pos + 2));
            return Ok(out);
        }
        if (0xD0..=0xD7).contains(&m) || m == 0x01 {
            pos += 2;
            continue;
        }
        if pos + 4 > d.len() {
            return Err("truncated marker".into());
        }
        let end = pos + 2 + u16::from_be_bytes([d[pos + 2], d[pos + 3]]) as usize;
        out.push((m, pos, end));
        pos = end;
        if m == 0xDA {
            // skip entropy-coded data until a real marker
            loop {
                pos = memchr(0xFF, d, pos).ok_or("entropy data runs off the end")?;
                if pos + 1 >= d.len() {
                    return Err("entropy data runs off the end".into());
                }
                let nb = d[pos + 1];
                if nb == 0x00 || (0xD0..=0xD7).contains(&nb) {
                    pos += 2;
                    continue;
                }
                if nb == 0xFF {
                    pos += 1;
                    continue;
                }
                break;
            }
        }
    }
    Err("EOI not found".into())
}

fn memchr(b: u8, d: &[u8], from: usize) -> Option<usize> {
    d[from..].iter().position(|&x| x == b).map(|p| p + from)
}

/// Segment payload (without marker and length). No-length markers
/// (EOI/RSTn/TEM carry no length field) yield an empty payload.
pub fn payload(d: &[u8], seg: (u8, usize, usize)) -> &[u8] {
    if seg.1 + 4 >= seg.2 {
        return &[];
    }
    &d[seg.1 + 4..seg.2]
}

/// Insert a fully-formed segment (starting at its 0xFF marker) before the
/// first non-APPn/COM marker (after existing APPn), i.e. at the end of the
/// header block.
pub fn insert_head_segment(d: &[u8], seg: &[u8]) -> Result<Vec<u8>, String> {
    let marks = markers(d)?;
    let body_start = marks
        .iter()
        .find(|(m, _, _)| !(0xE0..=0xEF).contains(m) && *m != 0xFE)
        .map(|(_, s, _)| *s)
        .ok_or("no body")?;
    let mut out = d[..body_start].to_vec();
    out.extend_from_slice(seg);
    out.extend_from_slice(&d[body_start..]);
    Ok(out)
}

/// Build an APPn segment from its payload.
pub fn appn(marker: u8, body: &[u8]) -> Vec<u8> {
    let mut v = vec![0xFF, marker];
    v.extend_from_slice(&((body.len() + 2) as u16).to_be_bytes());
    v.extend_from_slice(body);
    v
}

/// Remove every header segment whose payload starts with `prefix`
/// (e.g. `b"http://ns.adobe.com/xap/1.0/"` strips all XMP APP1s).
/// Returns Ok(input) unchanged when nothing matches.
pub fn drop_segments(d: &[u8], marker: u8, prefix: &[u8]) -> Result<Vec<u8>, String> {
    let marks = markers(d)?;
    let drop: Vec<(usize, usize)> = marks
        .iter()
        .filter(|&&(m, s, e)| m == marker && payload(d, (m, s, e)).starts_with(prefix))
        .map(|&(_, s, e)| (s, e))
        .collect();
    if drop.is_empty() {
        return Ok(d.to_vec());
    }
    let mut out = Vec::with_capacity(d.len());
    let mut pos = 0;
    for (s, e) in drop {
        out.extend_from_slice(&d[pos..s]);
        pos = e;
    }
    out.extend_from_slice(&d[pos..]);
    Ok(out)
}

/// XMP APP1 signature.
pub const XMP_NS: &[u8] = b"http://ns.adobe.com/xap/1.0/\0";

// One MPF image entry: (attr, size, offset, dep1, dep2); `offset` is
// relative to the TIFF header start inside the MPF payload.

/// Corrupt every MPF entry's offset so the secondary image pointer lands
/// `extra` bytes past EOF (offset = huge, size unchanged). Returns the patched
/// JPEG; errors if no MPF APP2 is found.
pub fn mpf_offsets_past_eof(d: &[u8]) -> Result<Vec<u8>, String> {
    let marks = markers(d)?;
    let mut out = d.to_vec();
    let mut patched = false;
    for (m, s, e) in marks {
        if m != 0xE2 || !payload(d, (m, s, e)).starts_with(b"MPF\0") {
            continue;
        }
        let p = payload(d, (m, s, e));
        let t_off = s + 4 + 4; // TIFF start = payload start + "MPF\0"
        let t = &p[4..];
        let le = t.starts_with(b"II");
        let ifd = if le {
            u32::from_le_bytes([t[4], t[5], t[6], t[7]]) as usize
        } else {
            u32::from_be_bytes([t[4], t[5], t[6], t[7]]) as usize
        };
        let r16 = |o: usize| -> u16 {
            if le {
                u16::from_le_bytes([t[o], t[o + 1]])
            } else {
                u16::from_be_bytes([t[o], t[o + 1]])
            }
        };
        let r32 = |o: usize| -> u32 {
            if le {
                u32::from_le_bytes([t[o], t[o + 1], t[o + 2], t[o + 3]])
            } else {
                u32::from_be_bytes([t[o], t[o + 1], t[o + 2], t[o + 3]])
            }
        };
        let n = r16(ifd) as usize;
        for k in 0..n {
            let e2 = ifd + 2 + 12 * k;
            if r16(e2) != 0xB002 {
                continue;
            }
            // MP Entry (0xB002) is type UNDEFINED: `cnt` is the byte count
            // of the entry array; each entry is 16 bytes.
            let cnt = r32(e2 + 4) as usize / 16;
            let vo = r32(e2 + 8) as usize;
            for j in 1..cnt {
                // entry j: offset field at vo+16j+8 — must stay inside this
                // APP2 payload (p covers t[4..] of it).
                let pos = t_off + vo + 16 * j + 8;
                assert!(pos + 4 <= e, "MPF entry write out of segment bounds");
                let v = d.len() as u32 + 0x1000;
                let v = if le { v.to_le_bytes() } else { v.to_be_bytes() };
                out[pos..pos + 4].copy_from_slice(&v);
                patched = true;
            }
        }
    }
    if patched {
        Ok(out)
    } else {
        Err("no MPF entries patched".into())
    }
}
