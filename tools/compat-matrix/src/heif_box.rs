//! Minimal HEIF box model: `HBox`, the `parse_*` readers, and the `make_*`
//! serializers used by `heif.rs`'s demux/remux. Split out to keep both files
//! under the 30 KB per-file cap.

use std::collections::BTreeMap;

#[derive(Clone)]
pub struct HBox {
    pub ty: [u8; 4],
    pub data: Vec<u8>, // payload only (after the 8/16-byte header)
}

impl HBox {
    pub fn new(ty: &[u8; 4], data: Vec<u8>) -> Self {
        Self { ty: *ty, data }
    }

    pub fn full(ty: &[u8; 4], version: u8, flags: u32, body: Vec<u8>) -> Self {
        let mut d = vec![version];
        d.extend_from_slice(&flags.to_be_bytes()[1..]);
        d.extend_from_slice(&body);
        Self::new(ty, d)
    }

    pub fn serialize(&self) -> Vec<u8> {
        let sz = (8 + self.data.len()) as u32;
        let mut v = sz.to_be_bytes().to_vec();
        v.extend_from_slice(&self.ty);
        v.extend_from_slice(&self.data);
        v
    }
}

/// Parse boxes spanning `d`.
pub fn parse_boxes(d: &[u8]) -> Result<Vec<HBox>, String> {
    let mut out = Vec::new();
    let mut pos = 0usize;
    while pos + 8 <= d.len() {
        let sz32 = u32::from_be_bytes([d[pos], d[pos + 1], d[pos + 2], d[pos + 3]]) as usize;
        let ty = [d[pos + 4], d[pos + 5], d[pos + 6], d[pos + 7]];
        let (size, hdr) = if sz32 == 1 {
            if pos + 16 > d.len() {
                return Err("truncated largesize box".into());
            }
            let s = u64::from_be_bytes([
                d[pos + 8],
                d[pos + 9],
                d[pos + 10],
                d[pos + 11],
                d[pos + 12],
                d[pos + 13],
                d[pos + 14],
                d[pos + 15],
            ]) as usize;
            (s, 16)
        } else if sz32 == 0 {
            (d.len() - pos, 8)
        } else {
            (sz32, 8)
        };
        if size < hdr || pos + size > d.len() {
            return Err(format!("bad box size at {pos:#x} ({:02x?})", ty));
        }
        out.push(HBox {
            ty,
            data: d[pos + hdr..pos + size].to_vec(),
        });
        pos += size;
    }
    Ok(out)
}

/// A parsed iinf entry.
#[derive(Clone)]
pub struct IinfEntry {
    pub item_id: u32,
    pub item_type: [u8; 4],
    pub name: String,
    /// v2/v3 `mime`/`uri ` items carry a trailing content_type string
    /// (e.g. "application/rdf+xml"); everything else leaves it None.
    pub content_type: Option<String>,
    pub hidden: bool,
}

/// A parsed iloc extent.
#[derive(Clone)]
pub struct Extent {
    pub construction_method: u16, // 0=file offset, 1=idat offset
    pub offset: u64,
    pub length: u64,
}

#[derive(Clone)]
pub struct IlocEntry {
    pub item_id: u32,
    pub construction_method: u16,
    pub extents: Vec<Extent>,
}

/// A parsed ipma association.
#[derive(Clone)]
pub struct IpmaAssoc {
    pub item_id: u32,
    /// (property_index, essential)
    pub props: Vec<(u16, bool)>,
}

/// Parsed iinf box (handles v0/v1 2-byte ids and v2/v3 4-byte ids).
pub fn parse_iinf(data: &[u8]) -> Result<Vec<IinfEntry>, String> {
    // iinf fullbox: version, flags; then 2-byte (v0) or 4-byte (v>=1) count
    let (version, _flags) = fullbox(data)?;
    let mut pos = 4;
    let _count = if version == 0 {
        let c = u16::from_be_bytes([data[pos], data[pos + 1]]);
        pos += 2;
        c as u32
    } else {
        let c = u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]);
        pos += 4;
        c
    };
    let mut out = Vec::new();
    while pos + 8 <= data.len() {
        let sz =
            u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]) as usize;
        let ty = &data[pos + 4..pos + 8];
        let body = &data[pos + 8..pos + sz];
        if ty != b"infe" {
            pos += sz;
            continue;
        }
        let (v, f) = fullbox(body)?;
        // v2: id(2) | protection_index(2) | type(4) | name
        // v3: id(4) | protection_index(2) | type(4) | name
        // v0/v1: id(2) | protection_index(2) | name | content_type | ...
        let (item_id, item_type, name_off) = if v >= 3 {
            if body.len() < 14 {
                pos += sz;
                continue;
            }
            (
                u32::from_be_bytes([body[4], body[5], body[6], body[7]]),
                [body[10], body[11], body[12], body[13]],
                14,
            )
        } else if v == 2 {
            if body.len() < 12 {
                pos += sz;
                continue;
            }
            (
                u16::from_be_bytes([body[4], body[5]]) as u32,
                [body[8], body[9], body[10], body[11]],
                12,
            )
        } else {
            if body.len() < 8 {
                pos += sz;
                continue;
            }
            (u16::from_be_bytes([body[4], body[5]]) as u32, *b"    ", 8)
        };
        let mut rest = &body[name_off..];
        let name = rest
            .split(|&b| b == 0)
            .next()
            .map(|b| String::from_utf8_lossy(b).into_owned())
            .unwrap_or_default();
        rest = &rest[(name.len() + 1).min(rest.len())..];
        let content_type = if v >= 2 && (item_type == *b"mime" || item_type == *b"uri ") {
            rest.split(|&b| b == 0)
                .next()
                .map(|b| String::from_utf8_lossy(b).into_owned())
        } else {
            None
        };
        out.push(IinfEntry {
            item_id,
            item_type,
            name,
            content_type,
            hidden: f & 1 == 1,
        });
        pos += sz;
    }
    Ok(out)
}

pub(crate) fn fullbox(d: &[u8]) -> Result<(u8, u32), String> {
    if d.len() < 4 {
        return Err("short fullbox".into());
    }
    Ok((d[0], u32::from_be_bytes([0, d[1], d[2], d[3]])))
}

/// Parse an iloc box. Handles versions 0/1/2.
pub fn parse_iloc(data: &[u8]) -> Result<Vec<IlocEntry>, String> {
    let (version, _flags) = fullbox(data)?;
    let mut pos = 4;
    let b = data[pos];
    pos += 1;
    let offset_size = (b >> 4) as usize;
    let length_size = (b & 0xF) as usize;
    let b2 = data[pos];
    pos += 1;
    let base_offset_size = (b2 >> 4) as usize;
    let index_size = if version == 1 || version == 2 {
        (b2 & 0xF) as usize
    } else {
        0
    };
    let item_count = if version < 2 {
        let c = u16::from_be_bytes([data[pos], data[pos + 1]]);
        pos += 2;
        c as usize
    } else {
        let c = u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]);
        pos += 4;
        c as usize
    };
    let mut out = Vec::new();
    for _ in 0..item_count {
        let item_id = if version < 2 {
            let v = u16::from_be_bytes([data[pos], data[pos + 1]]) as u32;
            pos += 2;
            v
        } else {
            let v = u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]);
            pos += 4;
            v
        };
        let construction_method = if version == 1 || version == 2 {
            let v = u16::from_be_bytes([data[pos], data[pos + 1]]) & 0xF;
            pos += 2;
            v
        } else {
            0
        };
        pos += 2; // data_reference_index
        let mut read = |n: usize| -> u64 {
            let mut v = 0u64;
            for i in 0..n {
                v = (v << 8) | data[pos + i] as u64;
            }
            pos += n;
            v
        };
        let base_offset = read(base_offset_size);
        let extent_count = read(2) as usize;
        let mut extents = Vec::with_capacity(extent_count);
        for _ in 0..extent_count {
            if index_size > 0 {
                read(index_size); // extent_index
            }
            let offset = read(offset_size);
            let length = read(length_size);
            extents.push(Extent {
                construction_method,
                offset: base_offset + offset,
                length,
            });
        }
        out.push(IlocEntry {
            item_id,
            construction_method,
            extents,
        });
    }
    Ok(out)
}

/// Parse an ipma box (associations).
pub fn parse_ipma(data: &[u8]) -> Result<Vec<IpmaAssoc>, String> {
    let (version, flags) = fullbox(data)?;
    let idx_wide = flags & 1 == 1;
    let mut pos = 4;
    let count =
        u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]) as usize;
    pos += 4;
    let mut out = Vec::new();
    for _ in 0..count {
        let item_id = if version < 1 {
            let v = u16::from_be_bytes([data[pos], data[pos + 1]]) as u32;
            pos += 2;
            v
        } else {
            let v = u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]);
            pos += 4;
            v
        };
        let n = data[pos] as usize;
        pos += 1;
        let mut props = Vec::with_capacity(n);
        for _ in 0..n {
            if idx_wide {
                let v = u16::from_be_bytes([data[pos], data[pos + 1]]);
                pos += 2;
                props.push((v & 0x7FFF, v & 0x8000 != 0));
            } else {
                let v = data[pos];
                pos += 1;
                props.push(((v & 0x7F) as u16, v & 0x80 != 0));
            }
        }
        out.push(IpmaAssoc { item_id, props });
    }
    Ok(out)
}

/// ipco children are plain boxes.
pub fn parse_ipco(data: &[u8]) -> Vec<HBox> {
    parse_boxes(data).unwrap_or_default()
}

/// Parse an iref box: map reference-type -> [(from, to)].
pub fn parse_iref(data: &[u8]) -> BTreeMap<[u8; 4], Vec<(u32, u32)>> {
    let mut out: BTreeMap<[u8; 4], Vec<(u32, u32)>> = BTreeMap::new();
    let Ok((v, _f)) = fullbox(data) else {
        return out;
    };
    let mut pos = 4;
    while pos + 12 <= data.len() {
        let sz =
            u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]) as usize;
        if sz < 12 || pos + sz > data.len() {
            break;
        }
        let rt: [u8; 4] = data[pos + 4..pos + 8].try_into().unwrap();
        let from = if v == 0 {
            u16::from_be_bytes([data[pos + 8], data[pos + 9]]) as u32
        } else {
            u32::from_be_bytes([data[pos + 8], data[pos + 9], data[pos + 10], data[pos + 11]])
        };
        let mut p = pos + if v == 0 { 10 } else { 12 };
        let cnt = u16::from_be_bytes([data[p], data[p + 1]]) as usize;
        p += 2;
        for _ in 0..cnt {
            let to = if v == 0 {
                let x = u16::from_be_bytes([data[p], data[p + 1]]) as u32;
                p += 2;
                x
            } else {
                let x = u32::from_be_bytes([data[p], data[p + 1], data[p + 2], data[p + 3]]);
                p += 4;
                x
            };
            out.entry(rt).or_default().push((from, to));
        }
        pos += sz;
    }
    out
}

/// pitm box -> primary item id.
pub fn parse_pitm(data: &[u8]) -> u32 {
    let Ok((v, _)) = fullbox(data) else { return 0 };
    if v == 0 {
        u16::from_be_bytes([data[4], data[5]]) as u32
    } else {
        u32::from_be_bytes([data[4], data[5], data[6], data[7]])
    }
}

// ---------------------------------------------------------------- writers

pub(crate) fn infe_v2(
    item_id: u32,
    ty: &[u8; 4],
    name: &str,
    ct: Option<&str>,
    hidden: bool,
) -> HBox {
    let mut body = Vec::new();
    // v2: item_id is 2 bytes (4 only in v3) — protection_index stays 0.
    body.extend_from_slice(&(item_id as u16).to_be_bytes());
    body.push(0);
    body.push(0);
    body.extend_from_slice(ty);
    body.extend_from_slice(name.as_bytes());
    body.push(0);
    if let Some(ct) = ct {
        body.extend_from_slice(ct.as_bytes());
        body.push(0);
    }
    HBox::full(b"infe", 2, u32::from(hidden), body)
}

pub(crate) fn make_iinf(entries: &[IinfEntry]) -> HBox {
    let mut body = Vec::new();
    body.extend_from_slice(&(entries.len() as u16).to_be_bytes());
    for e in entries {
        body.extend_from_slice(
            &infe_v2(
                e.item_id,
                &e.item_type,
                &e.name,
                e.content_type.as_deref(),
                e.hidden,
            )
            .serialize(),
        );
    }
    HBox::full(b"iinf", 0, 0, body)
}

/// iloc v0 writer: all extents file-offset based (construction_method 0),
/// offset_size=4, length_size=4, base_offset_size=0.
pub(crate) fn make_iloc(entries: &[(u32, &[(u64, u64)])]) -> HBox {
    // (item_id, extents[(offset,len)])
    let mut body = vec![0x44, 0x00]; // offset_size=4 length_size=4 base=0 index=0
    body.extend_from_slice(&(entries.len() as u16).to_be_bytes());
    for (id, exts) in entries {
        body.extend_from_slice(&(*id as u16).to_be_bytes());
        body.extend_from_slice(&0u16.to_be_bytes()); // data_reference_index
        body.extend_from_slice(&(exts.len() as u16).to_be_bytes());
        for (off, len) in *exts {
            body.extend_from_slice(&(*off as u32).to_be_bytes());
            body.extend_from_slice(&(*len as u32).to_be_bytes());
        }
    }
    HBox::full(b"iloc", 0, 0, body)
}

/// ipma v0, 1-byte indexes (essential bit in top bit). `props` is a list of
/// (item_id, [(index1based, essential)]).
pub(crate) fn make_ipma(assocs: &[(u32, Vec<(u16, bool)>)]) -> HBox {
    let mut body = Vec::new();
    body.extend_from_slice(&(assocs.len() as u32).to_be_bytes());
    for (id, props) in assocs {
        assert!(
            *id <= 0xFFFF,
            "ipma v0 item_id {id} exceeds u16 — need ipma v1"
        );
        body.extend_from_slice(&(*id as u16).to_be_bytes());
        body.push(props.len() as u8);
        for (idx, ess) in props {
            assert!(
                *idx <= 0x7F,
                "ipma v0 property index {idx} exceeds 7 bits — need ipma v1"
            );
            body.push((*idx as u8) | u8::from(*ess) << 7);
        }
    }
    HBox::full(b"ipma", 0, 0, body)
}

pub(crate) fn make_ipco(props: &[HBox]) -> HBox {
    let mut d = Vec::new();
    for p in props {
        d.extend_from_slice(&p.serialize());
    }
    HBox::new(b"ipco", d)
}

pub(crate) fn make_iprp(props: &[HBox], assocs: &[(u32, Vec<(u16, bool)>)]) -> HBox {
    let mut d = make_ipco(props).serialize();
    d.extend_from_slice(&make_ipma(assocs).serialize());
    HBox::new(b"iprp", d)
}

/// iref with 'cdsc' (content-describes) and 'dimg' references, version 0.
pub(crate) fn make_iref(refs: &[(u32, [u8; 4], Vec<u32>)]) -> HBox {
    let mut d = Vec::new();
    for (from, rt, tos) in refs {
        let mut body = Vec::new();
        body.extend_from_slice(&(*from as u16).to_be_bytes());
        body.extend_from_slice(&(tos.len() as u16).to_be_bytes());
        for to in tos {
            body.extend_from_slice(&(*to as u16).to_be_bytes());
        }
        d.extend_from_slice(&HBox::new(rt, body).serialize());
    }
    HBox::full(b"iref", 0, 0, d)
}

pub(crate) fn make_pitm(primary: u32) -> HBox {
    HBox::full(b"pitm", 0, 0, (primary as u16).to_be_bytes().to_vec())
}

pub(crate) fn make_hdlr() -> HBox {
    let mut body = Vec::new();
    body.extend_from_slice(&0u32.to_be_bytes()); // pre_defined
    body.extend_from_slice(b"pict");
    body.extend_from_slice(&[0; 12]); // reserved
    body.extend_from_slice(b"compat-matrix\0");
    HBox::full(b"hdlr", 0, 0, body)
}

pub(crate) fn make_meta(children: Vec<HBox>) -> HBox {
    let mut d = vec![0u8; 4]; // version+flags
    for c in children {
        d.extend_from_slice(&c.serialize());
    }
    HBox::new(b"meta", d)
}
