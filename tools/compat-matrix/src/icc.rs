//! Minimal ICC RGB matrix-profile writer for the fixture generator. All
//! profiles are generated in-repo from the *published* primaries, white point
//! and transfer (Bradford-adapted D65->D50), so `icc_identity_check.py`'s
//! independent numpy recomputation can verify them exactly (round-9 H-3).

fn s15f16(v: f64) -> [u8; 4] {
    ((v * 65536.0).round() as i32).to_be_bytes()
}

fn u8f8(v: f64) -> [u8; 2] {
    ((v * 256.0).round() as u16).to_be_bytes()
}

fn xyz(x: f64, y: f64, z: f64) -> Vec<u8> {
    let mut v = b"XYZ \0\0\0\0".to_vec();
    v.extend_from_slice(&s15f16(x));
    v.extend_from_slice(&s15f16(y));
    v.extend_from_slice(&s15f16(z));
    v
}

fn para4() -> Vec<u8> {
    // sRGB parametric curve, ICC functionType 0x0004:
    //   X >= d: (a*X + b)^g + e ; X < d: c*X + f
    let mut v = b"para\0\0\0\0".to_vec();
    v.extend_from_slice(&0x0004u16.to_be_bytes());
    v.extend_from_slice(&0u16.to_be_bytes());
    for p in [
        2.4,
        0.947_867_298_578_199_1,
        0.052_132_701_421_800_95,
        0.077_399_380_804_953_57,
        0.04045,
        0.0,
        0.0,
    ] {
        v.extend_from_slice(&s15f16(p));
    }
    v
}

fn mluc(text: &str) -> Vec<u8> {
    let mut v = b"mluc\0\0\0\0".to_vec();
    let utf16: Vec<u16> = text.encode_utf16().collect();
    let nbytes = (utf16.len() * 2) as u32;
    v.extend_from_slice(&1u32.to_be_bytes()); // one record
    v.extend_from_slice(&12u32.to_be_bytes()); // record size
    v.extend_from_slice(b"enUS");
    v.extend_from_slice(&nbytes.to_be_bytes());
    v.extend_from_slice(&28u32.to_be_bytes()); // offset
    for u in utf16 {
        v.extend_from_slice(&u.to_be_bytes());
    }
    v
}

/// v2 textDescriptionType ('desc'): ascii + (empty) unicode + (empty) mac tail.
fn desc_v2(text: &str) -> Vec<u8> {
    let mut v = b"desc\0\0\0\0".to_vec();
    v.extend_from_slice(&(text.len() as u32 + 1).to_be_bytes());
    v.extend_from_slice(text.as_bytes());
    v.push(0);
    v.extend_from_slice(&0u32.to_be_bytes()); // unicode lang
    v.extend_from_slice(&0u32.to_be_bytes()); // unicode count
    v.extend_from_slice(&0u16.to_be_bytes()); // scriptcode code
    v.push(0); // scriptcode count
    v.extend_from_slice(&[0u8; 67]); // mac data
    v
}

/// curvType with a single count=1 entry = pure gamma (u8Fixed8).
fn curv_gamma(g: f64) -> Vec<u8> {
    let mut v = b"curv\0\0\0\0".to_vec();
    v.extend_from_slice(&1u32.to_be_bytes());
    v.extend_from_slice(&u8f8(g));
    v
}

/// curvType table of `n` entries sampling `f` on [0,1].
fn curv_table(n: usize, f: impl Fn(f64) -> f64) -> Vec<u8> {
    let mut v = b"curv\0\0\0\0".to_vec();
    v.extend_from_slice(&(n as u32).to_be_bytes());
    for i in 0..n {
        let x = i as f64 / (n - 1) as f64;
        let y = (f(x) * 65535.0).round().clamp(0.0, 65535.0) as u16;
        v.extend_from_slice(&y.to_be_bytes());
    }
    v
}

fn srgb_eotf(c: f64) -> f64 {
    if c <= 0.04045 {
        c / 12.92
    } else {
        ((c + 0.055) / 1.055).powf(2.4)
    }
}

fn assemble(v4: bool, tags: Vec<(&[u8; 4], Vec<u8>)>) -> Vec<u8> {
    let n = tags.len() as u32;
    let mut out = Vec::with_capacity(1024);
    out.resize(128 + 4 + 12 * n as usize, 0u8);
    out[4..8].copy_from_slice(b"znmx");
    out[8..12].copy_from_slice(&if v4 { 0x0440_0000u32 } else { 0x0200_0000u32 }.to_be_bytes());
    out[12..16].copy_from_slice(b"mntr");
    out[16..20].copy_from_slice(b"RGB ");
    out[20..24].copy_from_slice(b"XYZ ");
    for (i, v) in [2026u16, 10, 4, 0, 0, 0].iter().enumerate() {
        out[24 + 2 * i..26 + 2 * i].copy_from_slice(&v.to_be_bytes());
    }
    out[36..40].copy_from_slice(b"acsp");
    out[40..44].copy_from_slice(b"APPL");
    out[64..68].copy_from_slice(&0u32.to_be_bytes()); // intent: perceptual
    out[68..72].copy_from_slice(&s15f16(0.9642));
    out[72..76].copy_from_slice(&s15f16(1.0));
    out[76..80].copy_from_slice(&s15f16(0.8249));
    out[80..84].copy_from_slice(b"znmx");
    out[128..132].copy_from_slice(&n.to_be_bytes());
    let mut data = Vec::new();
    for (i, (sig, body)) in tags.iter().enumerate() {
        let off = (128 + 4 + 12 * n as usize + data.len()) as u32;
        let p = 132 + 12 * i;
        out[p..p + 4].copy_from_slice(&sig[..]);
        out[p + 4..p + 8].copy_from_slice(&off.to_be_bytes());
        out[p + 8..p + 12].copy_from_slice(&(body.len() as u32).to_be_bytes());
        data.extend_from_slice(body);
        while data.len() % 4 != 0 {
            data.push(0);
        }
    }
    out.extend_from_slice(&data);
    let sz = out.len() as u32;
    out[0..4].copy_from_slice(&sz.to_be_bytes());
    out
}

const D50: (f64, f64, f64) = (0.9642, 1.0, 0.8249);
// sRGB primaries, Bradford D65->D50 adapted (canonical sRGB ICC values).
const SRGB_D50: [(f64, f64, f64); 3] = [
    (0.43604, 0.22249, 0.01392),
    (0.38515, 0.71687, 0.09708),
    (0.14307, 0.06061, 0.71410),
];
// Display P3 primaries (0.680/0.320, 0.265/0.690, 0.150/0.060), D65 wp,
// Bradford-adapted to D50 — numpy-recomputable via icc_identity_check.py.
const P3_D50: [(f64, f64, f64); 3] = [
    (0.51514, 0.24120, -0.00105),
    (0.29202, 0.69223, 0.04188),
    (0.15713, 0.06657, 0.78427),
];
// Adobe RGB (1998) primaries (0.64/0.33, 0.21/0.71, 0.15/0.06), D65 wp,
// Bradford-adapted to D50.
const ADOBE_D50: [(f64, f64, f64); 3] = [
    (0.60977, 0.31112, 0.01947),
    (0.20531, 0.62566, 0.06088),
    (0.14922, 0.06322, 0.74475),
];

fn matrix_tags(
    name: &str,
    prims: &[(f64, f64, f64); 3],
    trc: Vec<u8>,
    v4: bool,
) -> Vec<(&'static [u8; 4], Vec<u8>)> {
    let desc_tag: &'static [u8; 4] = b"desc";
    let mut tags: Vec<(&'static [u8; 4], Vec<u8>)> = vec![
        (desc_tag, if v4 { mluc(name) } else { desc_v2(name) }),
        (b"cprt", if v4 { mluc("CC0") } else { desc_v2("CC0") }),
        (b"wtpt", xyz(D50.0, D50.1, D50.2)),
        (b"rXYZ", xyz(prims[0].0, prims[0].1, prims[0].2)),
        (b"gXYZ", xyz(prims[1].0, prims[1].1, prims[1].2)),
        (b"bXYZ", xyz(prims[2].0, prims[2].1, prims[2].2)),
        (b"rTRC", trc.clone()),
        (b"gTRC", trc.clone()),
        (b"bTRC", trc),
    ];
    if v4 {
        // optional v4.4 CICP tag: sRGB 1/13/0/1 on the sRGB profile only
        if name.starts_with("sRGB") {
            let mut v = b"cicp\0\0\0\0".to_vec();
            v.extend_from_slice(&[1, 13, 0, 1]);
            tags.push((b"cicp", v));
        }
    }
    tags
}

/// Build an sRGB v4 ICC profile (mntr/RGB/XYZ, D50 wtpt, Bradford-adapted
/// primaries). v4 display profiles must use the D50 PCS white point.
pub fn srgb_icc_v4() -> Vec<u8> {
    assemble(
        true,
        matrix_tags("sRGB compat-matrix", &SRGB_D50, para4(), true),
    )
}

/// Canonical Display P3 v4 (D50-adapted P3 primaries, sRGB parametric TRC).
pub fn display_p3_icc_v4() -> Vec<u8> {
    assemble(true, matrix_tags("Display P3 v4", &P3_D50, para4(), true))
}

/// Canonical Display P3 v2 (D50 wtpt, sRGB TRC as a 1024-entry curv table —
/// v2 has no parametric curve type).
pub fn display_p3_icc_v2() -> Vec<u8> {
    let trc = curv_table(1024, srgb_eotf);
    assemble(false, matrix_tags("Display P3 v2", &P3_D50, trc, false))
}

/// Canonical Adobe RGB (1998) v2 (D50 wtpt, curv count=1 gamma 2.19921875).
pub fn adobe_rgb_icc_v2() -> Vec<u8> {
    assemble(
        false,
        matrix_tags("Adobe RGB 1998", &ADOBE_D50, curv_gamma(2.19921875), false),
    )
}

/// Extract the embedded ICC profile from any container we can parse:
/// JPEG APP2 ICC_PROFILE, PNG iCCP (zlib), WebP ICCP chunk, AVIF/HEIC
/// colr 'prof' on the primary (else any image) item. Returns raw ICC bytes.
pub fn extract_icc(d: &[u8]) -> Option<Vec<u8>> {
    if d.starts_with(&[0xFF, 0xD8]) {
        // JPEG: APP2 "ICC_PROFILE\0" seq total payload...
        let segs = crate::jpeg::markers(d).ok()?;
        let mut parts: Vec<(u8, &[u8])> = Vec::new();
        for s in &segs {
            if s.0 != 0xE2 {
                continue;
            }
            let p = crate::jpeg::payload(d, *s);
            if p.len() > 14 && p.starts_with(b"ICC_PROFILE\0") {
                parts.push((p[12], &p[14..]));
            }
        }
        parts.sort_by_key(|(seq, _)| *seq);
        if parts.is_empty() {
            return None;
        }
        let mut icc = Vec::new();
        for (_, p) in parts {
            icc.extend_from_slice(p);
        }
        return Some(icc);
    }
    if d.starts_with(b"\x89PNG") {
        let cs = crate::png::chunks(d).ok()?;
        let c = cs.iter().find(|c| &c.ty == b"iCCP")?;
        // profile name \0 method \0 zlib(profile)
        let i = c.data.iter().position(|&b| b == 0)? + 2;
        return miniz_oxide::inflate::decompress_to_vec_zlib(&c.data[i..]).ok();
    }
    if d.len() > 12 && &d[0..4] == b"RIFF" && &d[8..12] == b"WEBP" {
        let mut pos = 12usize;
        while pos + 8 <= d.len() {
            let ty = &d[pos..pos + 4];
            let ln = u32::from_le_bytes([d[pos + 4], d[pos + 5], d[pos + 6], d[pos + 7]]) as usize;
            if ty == b"ICCP" {
                return Some(d[pos + 8..pos + 8 + ln].to_vec());
            }
            pos += 8 + ln + (ln & 1);
        }
        return None;
    }
    // ISO-BMFF (AVIF/HEIC): colr 'prof' property on the primary image item,
    // else on any item (HEIC colour may live on tiles).
    if d.len() > 12 && &d[4..8] == b"ftyp" {
        let dm = crate::heif::Demux::load(d).ok()?;
        let mut order: Vec<u32> = vec![dm.primary];
        order.extend(
            dm.items
                .iter()
                .map(|i| i.item_id)
                .filter(|id| *id != dm.primary),
        );
        for id in order {
            for (idx, _ess) in dm.props_for(id) {
                if let Some(p) = dm.ipco.get(idx as usize - 1)
                    && &p.ty == b"colr"
                    && p.data.len() > 4
                    && &p.data[0..4] == b"prof"
                {
                    return Some(p.data[4..].to_vec());
                }
            }
        }
        return None;
    }
    None
}
