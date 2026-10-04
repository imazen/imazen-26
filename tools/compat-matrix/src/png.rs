//! PNG chunk-level tools: list, insert (spec-position), and remove chunks.

pub struct Chunk {
    pub ty: [u8; 4],
    pub data: Vec<u8>,
    /// offsets in the original file
    pub start: usize,
    pub end: usize,
}

pub fn chunks(d: &[u8]) -> Result<Vec<Chunk>, String> {
    if d.len() < 8 || &d[..8] != b"\x89PNG\r\n\x1a\n" {
        return Err("not a PNG".into());
    }
    let mut pos = 8usize;
    let mut out = Vec::new();
    while pos + 12 <= d.len() {
        let ln = u32::from_be_bytes([d[pos], d[pos + 1], d[pos + 2], d[pos + 3]]) as usize;
        let ty = [d[pos + 4], d[pos + 5], d[pos + 6], d[pos + 7]];
        let end = pos + 12 + ln;
        if end > d.len() {
            return Err("truncated chunk".into());
        }
        out.push(Chunk {
            ty,
            data: d[pos + 8..pos + 8 + ln].to_vec(),
            start: pos,
            end,
        });
        pos = end;
        if &ty == b"IEND" {
            break;
        }
    }
    Ok(out)
}

fn emit(ty: &[u8; 4], data: &[u8]) -> Vec<u8> {
    let mut v = (data.len() as u32).to_be_bytes().to_vec();
    v.extend_from_slice(ty);
    v.extend_from_slice(data);
    let crc = crc32(ty, data);
    v.extend_from_slice(&crc.to_be_bytes());
    v
}

fn crc32(ty: &[u8; 4], data: &[u8]) -> u32 {
    // IEEE CRC-32 over type+data (same polynomial zenflate uses; table-free).
    let mut crc: u32 = 0xFFFF_FFFF;
    for &b in ty.iter().chain(data.iter()) {
        crc ^= b as u32;
        for _ in 0..8 {
            crc = (crc >> 1) ^ (0xEDB8_8320 & (0u32.wrapping_sub(crc & 1)));
        }
    }
    !crc
}

/// Insert a chunk right after `after` (e.g. b"IHDR"), or before the first
/// chunk whose type is in `before` — whichever the caller passes. Used to add
/// iCCP/cICP/eXIf in spec position (before PLTE/IDAT).
pub fn insert_chunk(
    d: &[u8],
    ty: &[u8; 4],
    data: &[u8],
    after: &[u8; 4],
) -> Result<Vec<u8>, String> {
    let cs = chunks(d)?;
    let pos = cs
        .iter()
        .position(|c| &c.ty == after)
        .ok_or_else(|| format!("{after:?} not found"))?;
    let at = cs[pos].end;
    let mut out = d[..at].to_vec();
    out.extend_from_slice(&emit(ty, data));
    out.extend_from_slice(&d[at..]);
    Ok(out)
}

/// Build a cICP chunk payload.
pub fn cicp_body(cp: u8, tc: u8, mc: u8, full_range: bool) -> Vec<u8> {
    vec![cp, tc, mc, u8::from(full_range)]
}

/// Build an iCCP chunk payload (profile name + nul + deflate-compressed ICC).
pub fn iccp_body(name: &str, icc: &[u8]) -> Vec<u8> {
    let mut v = name.as_bytes().to_vec();
    v.push(0);
    v.push(0); // compression method: deflate
    v.extend_from_slice(&deflate_zlib(icc));
    v
}

/// zlib wrapper around stored (uncompressed) deflate blocks — spec-legal and
/// dependency-free; readers only inflate.
fn deflate_zlib(data: &[u8]) -> Vec<u8> {
    let mut out = vec![0x78, 0x01]; // zlib header, no compression
    let mut pos = 0usize;
    loop {
        let take = (data.len() - pos).min(65535);
        let last = pos + take == data.len();
        out.push(u8::from(last));
        out.extend_from_slice(&(take as u16).to_le_bytes());
        out.extend_from_slice(&(!(take as u16)).to_le_bytes());
        out.extend_from_slice(&data[pos..pos + take]);
        pos += take;
        if last {
            break;
        }
    }
    out.extend_from_slice(&adler32(data).to_be_bytes());
    out
}

fn adler32(d: &[u8]) -> u32 {
    let (mut a, mut b) = (1u32, 0u32);
    for &x in d {
        a = (a + x as u32) % 65521;
        b = (b + a) % 65521;
    }
    (b << 16) | a
}

/// Byte-level indexed (colour type 3) PNG: IHDR + PLTE + optional tRNS +
/// IDAT. `indices` is w*h bytes; `palette` is RGB triples; `alphas` is the
/// tRNS table (omit for opaque).
pub fn indexed_png(
    w: u32,
    h: u32,
    indices: &[u8],
    palette: &[[u8; 3]],
    alphas: Option<&[u8]>,
) -> Vec<u8> {
    let mut out = b"\x89PNG\r\n\x1a\n".to_vec();
    let mut ihdr = w.to_be_bytes().to_vec();
    ihdr.extend_from_slice(&h.to_be_bytes());
    ihdr.extend_from_slice(&[8, 3, 0, 0, 0]); // 8-bit, palette, no interlace
    out.extend_from_slice(&emit(b"IHDR", &ihdr));
    out.extend_from_slice(&emit(b"PLTE", &palette.concat()));
    if let Some(a) = alphas {
        out.extend_from_slice(&emit(b"tRNS", a));
    }
    // filter byte 0 per row
    let mut raw = Vec::with_capacity((w * h + h) as usize);
    for y in 0..h as usize {
        raw.push(0);
        raw.extend_from_slice(&indices[y * w as usize..(y + 1) * w as usize]);
    }
    out.extend_from_slice(&emit(b"IDAT", &deflate_zlib(&raw)));
    out.extend_from_slice(&emit(b"IEND", &[]));
    out
}
