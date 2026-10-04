//! Minimal TIFF/EXIF writer for fixture metadata: IFD0 + Exif IFD + Interop
//! IFD, little-endian. Used for JPEG APP1 (with an `Exif\0\0` prefix), PNG
//! eXIf, WebP EXIF and HEIF/AVIF Exif items.

/// One IFD entry: (tag, type, count, value-bytes inline or spill).
#[derive(Clone)]
pub struct IfdEntry {
    pub tag: u16,
    pub typ: u16,
    pub count: u32,
    pub raw: Vec<u8>,
}

impl IfdEntry {
    pub fn short(tag: u16, v: u16) -> Self {
        Self {
            tag,
            typ: 3,
            count: 1,
            raw: v.to_le_bytes().to_vec(),
        }
    }
    pub fn shorts(tag: u16, vs: &[u16]) -> Self {
        Self {
            tag,
            typ: 3,
            count: vs.len() as u32,
            raw: vs.iter().flat_map(|v| v.to_le_bytes()).collect(),
        }
    }
    pub fn long(tag: u16, v: u32) -> Self {
        Self {
            tag,
            typ: 4,
            count: 1,
            raw: v.to_le_bytes().to_vec(),
        }
    }
    pub fn ascii(tag: u16, s: &str) -> Self {
        let mut raw = s.as_bytes().to_vec();
        raw.push(0);
        Self {
            tag,
            typ: 2,
            count: raw.len() as u32,
            raw,
        }
    }
}

fn ifd_bytes(entries: &[IfdEntry], at: u32) -> Vec<u8> {
    let mut entries: Vec<&IfdEntry> = entries.iter().collect();
    entries.sort_by_key(|e| e.tag);
    let data_at = at + 2 + 12 * entries.len() as u32 + 4;
    let mut head = (entries.len() as u16).to_le_bytes().to_vec();
    let mut data = Vec::new();
    for e in entries {
        if e.raw.len() <= 4 {
            head.extend_from_slice(&e.tag.to_le_bytes());
            head.extend_from_slice(&e.typ.to_le_bytes());
            head.extend_from_slice(&e.count.to_le_bytes());
            let mut v = e.raw.clone();
            v.resize(4, 0);
            head.extend_from_slice(&v);
        } else {
            head.extend_from_slice(&e.tag.to_le_bytes());
            head.extend_from_slice(&e.typ.to_le_bytes());
            head.extend_from_slice(&e.count.to_le_bytes());
            head.extend_from_slice(&(data_at + data.len() as u32).to_le_bytes());
            data.extend_from_slice(&e.raw);
            if e.raw.len() & 1 == 1 {
                data.push(0);
            }
        }
    }
    head.extend_from_slice(&0u32.to_le_bytes());
    head.extend_from_slice(&data);
    head
}

/// What to put in the EXIF blob.
#[derive(Clone, Default)]
pub struct ExifSpec {
    /// IFD0 orientation tag (0x0112); None = omit.
    pub orientation: Option<u16>,
    /// Exif IFD ColorSpace (0xA001): 1 = sRGB, 0xFFFF = uncalibrated.
    pub color_space: Option<u16>,
    /// Interop IFD index: "R98" (DCF sRGB) or "R03" (DCF Adobe RGB).
    pub interop_index: Option<&'static str>,
}

/// Build the TIFF blob (starts `II*\0`), including IFD0/Exif/Interop layout.
pub fn build_tiff(spec: &ExifSpec) -> Vec<u8> {
    let mut ifd0: Vec<IfdEntry> = Vec::new();
    if let Some(o) = spec.orientation {
        ifd0.push(IfdEntry::short(0x0112, o));
    }
    ifd0.push(IfdEntry::shorts(0x0213, &[1])); // YCbCrPositioning = centered, keeps picky readers happy
    let has_io = spec.interop_index.is_some();
    let has_exif = spec.color_space.is_some() || has_io;

    // layout: header(8), IFD0, Exif IFD, Interop IFD. All entries inline-size,
    // so the IFD size is exactly 2+12n+4.
    let n_ifd0 = ifd0.len() + usize::from(has_exif);
    let exif_at = 8 + ifd_size_placeholder(n_ifd0);
    let n_exif = usize::from(spec.color_space.is_some()) + usize::from(has_io);
    let io_at = exif_at + ifd_size_placeholder(n_exif);

    if has_exif {
        ifd0.push(IfdEntry::long(0x8769, exif_at as u32));
    }
    let mut out = b"II*\0".to_vec();
    out.extend_from_slice(&8u32.to_le_bytes());
    out.extend_from_slice(&ifd_bytes(&ifd0, 8));
    if has_exif {
        let mut ents = Vec::new();
        if let Some(cs) = spec.color_space {
            ents.push(IfdEntry::short(0xA001, cs));
        }
        if has_io {
            ents.push(IfdEntry::long(0xA005, io_at as u32));
        }
        out.extend_from_slice(&ifd_bytes(&ents, exif_at as u32));
    }
    if has_io {
        let ents = vec![IfdEntry::ascii(0x0001, spec.interop_index.unwrap())];
        out.extend_from_slice(&ifd_bytes(&ents, io_at as u32));
    }
    out
}

fn ifd_size_placeholder(n: usize) -> usize {
    // Only inline-sized entries appear in our IFD0/Exif sets except none —
    // compute the real size so offsets stay honest.
    2 + 12 * n + 4
}

// ------------------------------------------------------------- parsing

/// What `verify` recovers from a TIFF/EXIF payload.
#[derive(Default)]
pub struct TiffInfo {
    pub orientation: Option<u8>,
    pub color_space: Option<u16>,
    pub interop_index: Option<String>,
}

/// One decoded IFD entry: tag, type, count, and the u16/u32 value for
/// SHORT/LONG count==1 entries (inline), otherwise the value offset.
struct Ifd {
    tag: u16,
    #[allow(dead_code)]
    ty: u16,
    #[allow(dead_code)]
    count: u32,
    value: u64,
    value_off: usize,
}

/// Parse a TIFF payload (the bytes after "Exif\0\0" or a bare TIFF blob)
/// for IFD0 orientation, ColorSpace, and the EXIF-IFD InteropIndex.
pub fn parse_tiff(t: &[u8]) -> TiffInfo {
    let mut out = TiffInfo::default();
    if t.len() < 8 {
        return out;
    }
    let le = t.starts_with(b"II");
    if !le && !t.starts_with(b"MM") {
        return out;
    }
    let r16 = |o: usize| -> u16 {
        if o + 2 > t.len() {
            return 0;
        }
        if le {
            u16::from_le_bytes([t[o], t[o + 1]])
        } else {
            u16::from_be_bytes([t[o], t[o + 1]])
        }
    };
    let r32 = |o: usize| -> u32 {
        if o + 4 > t.len() {
            return 0;
        }
        if le {
            u32::from_le_bytes([t[o], t[o + 1], t[o + 2], t[o + 3]])
        } else {
            u32::from_be_bytes([t[o], t[o + 1], t[o + 2], t[o + 3]])
        }
    };
    let entries = |off: usize| -> Vec<Ifd> {
        let mut v = Vec::new();
        let n = r16(off) as usize;
        for k in 0..n {
            let e = off + 2 + 12 * k;
            if e + 12 > t.len() {
                break;
            }
            let (tag, ty, cnt) = (r16(e), r16(e + 2), r32(e + 4));
            let value = match (ty, cnt) {
                (3, 1) => r16(e + 8) as u64,
                (4, 1) => r32(e + 8) as u64,
                _ => r32(e + 8) as u64,
            };
            v.push(Ifd {
                tag,
                ty,
                count: cnt,
                value,
                value_off: e + 8,
            });
        }
        v
    };

    let ifd0 = r32(4) as usize;
    let mut exif_ptr = None;
    for en in entries(ifd0) {
        match en.tag {
            0x0112 => out.orientation = Some(en.value as u8),
            0xA001 => out.color_space = Some(en.value as u16),
            0x8769 => exif_ptr = Some(en.value as usize),
            _ => {}
        }
    }
    if let Some(ep) = exif_ptr {
        let mut interop_ptr = None;
        for en in entries(ep) {
            match en.tag {
                // ExifIFD carries ColorSpace + InteropIFD pointer;
                // orientation occasionally lands here too (informative).
                0xA001 => out.color_space = Some(en.value as u16),
                0x0112 => out.orientation = Some(en.value as u8),
                0xA005 => interop_ptr = Some(en.value as usize),
                _ => {}
            }
        }
        if let Some(ip) = interop_ptr {
            for en in entries(ip) {
                if en.tag == 0x0001 && en.value_off + 4 <= t.len() {
                    // InteroperabilityIndex: "R98"/"R03" — 4-byte ASCII sits
                    // inline at value_off (count<=4 never spills).
                    let vo = en.value_off;
                    out.interop_index = Some(String::from_utf8_lossy(&t[vo..vo + 3]).into_owned());
                }
            }
        }
    }
    out
}
