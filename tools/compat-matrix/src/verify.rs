//! Post-generation verification: re-parse each emitted fixture and assert it
//! carries the signalling its manifest row claims (`row.expect` tokens), that
//! no two fixtures are byte-identical, and that every row declares tokens.
//! A fixture that doesn't say what its label says silently corrupts the
//! matrix — generation fails here before it can be swept.

use crate::exif;
use crate::heif::Demux;
use crate::jpeg;
use crate::manifest::FixtureRow;
use std::collections::HashMap;
use std::path::Path;

/// Verify every emitted fixture against its expected signalling tokens.
/// Returns Err on the first violation (with the fixture id + missing token).
pub fn verify_dir(dir: &Path, rows: &[FixtureRow]) -> Result<(), String> {
    let mut shas: HashMap<&str, &str> = HashMap::new();
    for r in rows {
        if let Some(other) = shas.insert(&r.sha256, &r.id) {
            return Err(format!(
                "duplicate fixture bytes: {} == {} ({})",
                r.id, other, r.file
            ));
        }
        if r.expect.is_empty() {
            return Err(format!("{} declares no signalling expectations", r.id));
        }
        let bytes = std::fs::read(dir.join(&r.file)).map_err(|e| format!("{}: read: {e}", r.id))?;
        let got = measure(r, &bytes)?;
        for t in &r.expect {
            let (k, v) = t.split_once('=').unwrap_or((t.as_str(), ""));
            check(r, k, v, &got, dir)?;
        }
        // manifest dims must equal the file's stored dims for every format
        // we can measure (rotated fixtures store canonical; irot/EXIF carry
        // the transform).
        if let Some((w, h)) = got.stored_dims
            && (w, h) != (r.w, r.h)
        {
            return Err(format!(
                "{}: manifest dims {}x{} != stored {}x{}",
                r.id, r.w, r.h, w, h
            ));
        }
    }
    Ok(())
}

/// The container-level signalling observed by re-parsing fixture bytes.
/// Fields are Option<>s because each format only populates what applies.
#[derive(Default)]
struct Got {
    // shared
    exif_orient: Option<u8>,
    icc_sha: Option<String>,
    // jpeg
    jfif: bool,
    app14: Option<u8>,
    mpf: bool,
    mpf_offsets_past_eof: bool,
    xmp: bool,
    xmp_orient: Option<u8>,
    /// hdrgm/GContainer params inside an XMP APP1 (UltraHDR 1.0 style).
    xmp_hdrgm: bool,
    /// `urn:iso:std:iso:ts:21496` APP2 (ISO 21496-1 gain-map metadata).
    iso21496_app2: bool,
    baseline: bool,
    progressive: bool,
    exif_cs: Option<u16>,
    interop: Option<String>,
    // png / riff-family chunk+value reports
    chunks: Vec<String>,
    png_ct: u8,
    png_bd: u8,
    cicp: Option<[u8; 4]>,
    srgb_intent: Option<u8>,
    // heif-family (avif + heic)
    props: Vec<String>,
    items: Vec<String>,
    nclx: Option<[u16; 4]>,
    irot: Option<u8>,
    imir: Option<u8>,
    colr_kinds: Vec<String>,
    /// colr kinds across ALL items (grids often leave colour on tiles)
    colr_any: Vec<String>,
    /// ICC payload length of the primary item's `prof`/`rICC` colr — the
    /// malformed-donor-`prof` check (declares a profile, carries nothing).
    prof_len: Option<usize>,
    /// av1C-configured bit depth / chroma subsampling (r13 §2).
    av1c_highbitdepth: Option<bool>,
    av1c_sub: Option<(bool, bool)>,
    dinf: bool,
    /// `mime` item content_type (XMP etc.) — the remux must preserve it or
    /// exiftool-class readers can't identify the item at all.
    mime_ct: Option<String>,
    // jxl
    aux_items: Vec<u32>,
    stored_dims: Option<(u32, u32)>,
    jorient: Option<u8>,
    jboxes: Vec<String>,
    jcolour_enum: bool,
    // presence flags shared across formats
    has_exif: bool,
    has_alpha: bool,
    gainmap: bool,
}

fn measure(r: &FixtureRow, d: &[u8]) -> Result<Got, String> {
    let mut g = Got::default();
    let ext = r.file.rsplit('.').next().unwrap_or("");
    match ext {
        "jpg" | "jpeg" => measure_jpeg(&mut g, d)?,
        "png" => measure_png(&mut g, d)?,
        "webp" => measure_webp(&mut g, d)?,
        "avif" | "heic" => measure_heif(&mut g, d)?,
        "jxl" => measure_jxl(&mut g, d)?,
        e => return Err(format!("{}: no verifier for .{e}", r.id)),
    }
    Ok(g)
}

// ------------------------------------------------------------- jpeg

fn measure_jpeg(g: &mut Got, d: &[u8]) -> Result<(), String> {
    let marks = jpeg::markers(d)?;
    for (m, s, e) in &marks {
        let (m, s, e) = (*m, *s, *e);
        let p = jpeg::payload(d, (m, s, e));
        match m {
            0xE0 if p.starts_with(b"JFIF\0") => g.jfif = true,
            0xE1 => {
                if p.starts_with(b"Exif\0\0") {
                    g.has_exif = true;
                    let t = exif::parse_tiff(&p[6..]);
                    g.exif_orient = t.orientation;
                    g.exif_cs = t.color_space;
                    g.interop = t.interop_index.clone();
                } else if p.starts_with(b"http://ns.adobe.com/xap/1.0/") {
                    g.xmp = true;
                    let xs = String::from_utf8_lossy(p);
                    if let Some(v) = xs.split("tiff:Orientation=\"").nth(1) {
                        g.xmp_orient = v[..1].parse().ok();
                    }
                    if xs.contains("hdrgm:") || xs.contains("GContainer:Item") {
                        g.xmp_hdrgm = true;
                        g.gainmap = true;
                    }
                }
            }
            0xE2 => {
                if p.starts_with(b"urn:iso:std:iso:ts:21496") {
                    g.iso21496_app2 = true;
                    g.gainmap = true;
                }
                if p.starts_with(b"MPF\0") {
                    g.mpf = true;
                    g.gainmap = true;
                    // every MP entry offset must be out of range for the
                    // corrupt variant
                    if let Ok(past) = mpf_offsets_out_of_range(p, d.len()) {
                        g.mpf_offsets_past_eof = past;
                    }
                } else if p.starts_with(b"ICC_PROFILE\0") {
                    let prof = collect_icc(&marks, d);
                    g.icc_sha = Some(crate::generate::sha256_hex_pub(&prof));
                }
            }
            0xEE if p.starts_with(b"Adobe") => {
                // "Adobe" + ver(2) + flags0(2) + flags1(2) + transform(1)
                if p.len() >= 12 {
                    g.app14 = Some(p[11]);
                }
            }
            0xC0 | 0xC1 | 0xC2 | 0xC9 | 0xCA => {
                if m == 0xC0 {
                    g.baseline = true;
                }
                if m == 0xC2 {
                    g.progressive = true;
                }
                if p.len() >= 5 && g.stored_dims.is_none() {
                    g.stored_dims = Some((
                        u16::from_be_bytes([p[3], p[4]]) as u32,
                        u16::from_be_bytes([p[1], p[2]]) as u32,
                    ));
                }
            }
            _ => {}
        }
    }
    Ok(())
}

fn collect_icc(marks: &[(u8, usize, usize)], d: &[u8]) -> Vec<u8> {
    let mut parts: Vec<(u8, Vec<u8>)> = Vec::new();
    for &(m, s, e) in marks {
        if m != 0xE2 {
            continue;
        }
        let p = jpeg::payload(d, (m, s, e));
        if p.starts_with(b"ICC_PROFILE\0") && p.len() > 14 {
            parts.push((p[12], p[14..].to_vec()));
        }
    }
    parts.sort();
    parts.into_iter().flat_map(|(_, v)| v).collect()
}

/// MP Entry (0xB002) type-7 count is a byte count; entries are 16 bytes.
/// Returns Ok(true) when every non-primary entry's offset lands past `flen`.
fn mpf_offsets_out_of_range(p: &[u8], flen: usize) -> Result<bool, String> {
    let t = &p[4..];
    let le = t.starts_with(b"II");
    if !le && !t.starts_with(b"MM") {
        return Err("MPF bad byte order".into());
    }
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
    let ifd = r32(4) as usize;
    let n = r16(ifd) as usize;
    let mut past = true;
    let mut found = false;
    for k in 0..n {
        let e = ifd + 2 + 12 * k;
        if r16(e) != 0xB002 {
            continue;
        }
        let cnt = r32(e + 4) as usize / 16;
        let vo = r32(e + 8) as usize;
        for j in 1..cnt {
            let off = r32(vo + 16 * j + 8) as usize;
            found = true;
            if off <= flen {
                past = false;
            }
        }
    }
    Ok(found && past)
}

// ------------------------------------------------------------- png

fn measure_png(g: &mut Got, d: &[u8]) -> Result<(), String> {
    if !d.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Err("bad PNG sig".into());
    }
    let mut pos = 8usize;
    while pos + 12 <= d.len() {
        let ln = u32::from_be_bytes([d[pos], d[pos + 1], d[pos + 2], d[pos + 3]]) as usize;
        let ty = std::str::from_utf8(&d[pos + 4..pos + 8]).unwrap_or("????");
        let body = &d[pos + 8..pos + 8 + ln.min(d.len().saturating_sub(pos + 8))];
        g.chunks.push(ty.to_string());
        match ty.as_bytes() {
            b"IHDR" => {
                g.png_bd = body[8];
                g.png_ct = body[9];
                g.stored_dims = Some((
                    u32::from_be_bytes([body[0], body[1], body[2], body[3]]),
                    u32::from_be_bytes([body[4], body[5], body[6], body[7]]),
                ));
            }
            b"cICP" if body.len() >= 4 => {
                g.cicp = Some([body[0], body[1], body[2], body[3]]);
            }
            b"sRGB" if !body.is_empty() => g.srgb_intent = Some(body[0]),
            b"iCCP" => {
                // "name\0 method data" — inflate the deflate stream to get
                // the real profile bytes for the sha check.
                if let Some(z) = body.iter().position(|&b| b == 0).map(|i| i + 2) {
                    if let Ok(prof) = miniz_oxide::inflate::decompress_to_vec_zlib(&body[z..]) {
                        g.icc_sha = Some(crate::generate::sha256_hex_pub(&prof));
                    } else {
                        g.icc_sha = Some("present".into());
                    }
                }
            }
            b"eXIf" => {
                g.has_exif = true;
                let t = exif::parse_tiff(body);
                g.exif_orient = t.orientation;
                g.exif_cs = t.color_space;
                g.interop = t.interop_index.clone();
            }
            _ => {}
        }
        pos += 12 + ln;
        if ty == "IEND" {
            break;
        }
    }
    g.has_alpha = matches!(g.png_ct, 4 | 6);
    Ok(())
}

// ------------------------------------------------------------- webp

fn measure_webp(g: &mut Got, d: &[u8]) -> Result<(), String> {
    if &d[0..4] != b"RIFF" || &d[8..12] != b"WEBP" {
        return Err("bad RIFF".into());
    }
    let mut pos = 12usize;
    while pos + 8 <= d.len() {
        let ty = std::str::from_utf8(&d[pos..pos + 4]).unwrap_or("????");
        let ln = u32::from_le_bytes([d[pos + 4], d[pos + 5], d[pos + 6], d[pos + 7]]) as usize;
        let body = &d[pos + 8..pos + 8 + ln.min(d.len().saturating_sub(pos + 8))];
        g.chunks.push(ty.to_string());
        match ty.as_bytes() {
            b"VP8X" if body.len() >= 10 => {
                g.stored_dims = Some((
                    1 + u32::from_le_bytes([body[4], body[5], body[6], 0]),
                    1 + u32::from_le_bytes([body[7], body[8], body[9], 0]),
                ));
                if body[0] & 0x10 != 0 {
                    g.has_alpha = true;
                }
            }
            b"VP8 " if body.len() >= 10 && g.stored_dims.is_none() => {
                // lossy bitstream header: frame tag(3) sig(3) w(2) h(2)
                let w = u16::from_le_bytes([body[6], body[7]]) & 0x3fff;
                let h = u16::from_le_bytes([body[8], body[9]]) & 0x3fff;
                g.stored_dims = Some((w as u32, h as u32));
            }
            b"VP8L" if body.len() >= 5 && g.stored_dims.is_none() => {
                let b0 = body[1] as u32;
                let b1 = body[2] as u32;
                let b2 = body[3] as u32;
                let b3 = body[4] as u32;
                g.stored_dims = Some((
                    1 + (b0 | ((b1 & 0x3f) << 8)),
                    1 + ((b1 >> 6) | (b2 << 2) | ((b3 & 0x0f) << 10)),
                ));
                g.has_alpha = true;
            }
            b"ICCP" => {
                g.icc_sha = Some(crate::generate::sha256_hex_pub(body));
            }
            b"EXIF" => {
                g.has_exif = true;
                let t = exif::parse_tiff(body);
                g.exif_orient = t.orientation;
                g.exif_cs = t.color_space;
                g.interop = t.interop_index.clone();
            }
            b"ALPH" => g.has_alpha = true,
            _ => {}
        }
        pos += 8 + ln + (ln & 1);
    }
    Ok(())
}

// ------------------------------------------------------------- heif/avif

fn measure_heif(g: &mut Got, d: &[u8]) -> Result<(), String> {
    let dm = Demux::load(d).map_err(|e| format!("demux: {e}"))?;
    for i in &dm.items {
        g.items
            .push(String::from_utf8_lossy(&i.item_type).trim().to_string());
        if i.item_type == *b"Exif" {
            g.has_exif = true;
            if let Some(pay) = dm.payload.get(&i.item_id) {
                // 4-byte TIFF-header offset, then TIFF
                if pay.len() > 4 {
                    let t = exif::parse_tiff(&pay[4..]);
                    g.exif_orient = t.orientation;
                    g.exif_cs = t.color_space;
                    g.interop = t.interop_index.clone();
                }
            }
        }
        if i.item_type == *b"mime" {
            g.mime_ct = i.content_type.clone();
        }
        if i.item_type == *b"auxl" {
            g.aux_items.push(i.item_id);
        }
        // auxC-marked auxiliary items (alpha/gainmap): the aux item's own
        // item_type can be av01/hvc1, not 'auxl' — scan every item's props.
        if let Some(a) = dm.ipma.iter().find(|a| a.item_id == i.item_id) {
            for (idx, _) in &a.props {
                if let Some(p) = dm.ipco.get((*idx - 1) as usize)
                    && &p.ty == b"auxC"
                {
                    let t = String::from_utf8_lossy(&p.data);
                    if t.contains("auxiliary:alpha") || t.contains("auxid:1") {
                        g.has_alpha = true;
                    }
                    if t.contains("hdrgainmap") || t.contains("gainmap") {
                        g.gainmap = true;
                    }
                }
            }
        }
        if i.item_type == *b"tmap" {
            g.gainmap = true;
        }
    }
    g.dinf = dm.dinf.is_some();
    // auxl semantics come from auxC aux_type: "urn:com:apple:photo:2020:aux:
    // hdrgainmap" (or semantic variants) = gain map; "...:auxid:1"/alpha = alpha.
    for aux_id in std::mem::take(&mut g.aux_items) {
        let props: Vec<u16> = dm
            .ipma
            .iter()
            .find(|a| a.item_id == aux_id)
            .map(|a| a.props.iter().map(|(i, _)| *i).collect())
            .unwrap_or_default();
        for idx in props {
            if let Some(p) = dm.ipco.get((idx - 1) as usize)
                && &p.ty == b"auxC"
            {
                let t = String::from_utf8_lossy(&p.data);
                if t.contains("hdrgainmap") || t.contains("gainmap") {
                    g.gainmap = true;
                }
                if t.contains("auxiliary:alpha") || t.contains("auxid:1") {
                    g.has_alpha = true;
                }
            }
        }
    }
    // primary stored dims vs manifest
    if let Some((w, h)) = dm.dims_of(dm.primary) {
        g.stored_dims = Some((w, h));
    }
    let primary_props: Vec<u16> = dm
        .ipma
        .iter()
        .find(|a| a.item_id == dm.primary)
        .map(|a| a.props.iter().map(|(i, _)| *i).collect())
        .unwrap_or_default();
    for a in &dm.ipma {
        for (idx, _) in &a.props {
            if let Some(p) = dm.ipco.get((idx - 1) as usize)
                && &p.ty == b"colr"
            {
                let kind = String::from_utf8_lossy(&p.data[0..4]).into_owned();
                if !g.colr_any.contains(&kind) {
                    g.colr_any.push(kind);
                }
            }
        }
    }
    for idx in primary_props {
        if let Some(p) = dm.ipco.get((idx - 1) as usize) {
            let ty = String::from_utf8_lossy(&p.ty).into_owned();
            g.props.push(ty.clone());
            match &p.ty {
                b"irot" => g.irot = Some(p.data[0] & 3),
                b"imir" => g.imir = Some(p.data[0] & 1),
                b"av1C" => {
                    // r13 §2: the av1C record (4 bytes, no inner type)
                    // carries the coded format the encoder configured —
                    // byte2: seq_tier_0|high_bitdepth|twelve_bit|mono|
                    // subsampling_x|subsampling_y|chroma_sample_position.
                    if p.data.len() >= 4 {
                        let b2 = p.data[2];
                        g.av1c_highbitdepth = Some(b2 & 0x40 != 0);
                        g.av1c_sub = Some((b2 & 0x08 != 0, b2 & 0x04 != 0));
                    }
                }
                b"colr" => {
                    let kind = String::from_utf8_lossy(&p.data[0..4]).into_owned();
                    g.colr_kinds.push(kind.clone());
                    if kind == "nclx" && p.data.len() >= 11 {
                        let n = |o: usize| u16::from_be_bytes([p.data[4 + o], p.data[5 + o]]);
                        // byte 7 is full_range_flag (0x80 = full): store
                        // the normalized flag, not the raw byte.
                        g.nclx =
                            Some([n(0), n(2), n(4), if p.data[10] & 0x80 != 0 { 1 } else { 0 }]);
                    } else if kind == "prof" || kind == "rICC" {
                        g.icc_sha = Some(crate::generate::sha256_hex_pub(&p.data[4..]));
                        g.prof_len = Some(p.data.len().saturating_sub(4));
                    }
                }
                _ => {}
            }
        }
    }
    Ok(())
}

// ------------------------------------------------------------- jxl

fn measure_jxl(g: &mut Got, d: &[u8]) -> Result<(), String> {
    // JXL container: 12-byte signature box (size=12, "JXL ", magic 0D0A870A)
    // then boxed stream. Bare codestreams start FF 0A — no boxes.
    const SIG: &[u8; 12] = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a";
    if d.starts_with(SIG) {
        let mut pos = 12usize;
        let mut parts: Vec<u8> = Vec::new();
        while pos + 8 <= d.len() {
            let mut sz = u32::from_be_bytes([d[pos], d[pos + 1], d[pos + 2], d[pos + 3]]) as u64;
            let ty: &[u8] = &d[pos + 4..pos + 8];
            let mut hsz = 8usize;
            if sz == 1 && pos + 16 <= d.len() {
                sz = u64::from_be_bytes([
                    d[pos + 8],
                    d[pos + 9],
                    d[pos + 10],
                    d[pos + 11],
                    d[pos + 12],
                    d[pos + 13],
                    d[pos + 14],
                    d[pos + 15],
                ]);
                hsz = 16;
            }
            let body_end = (pos + sz as usize).min(d.len());
            let body = &d[pos + hsz..body_end.max(pos + hsz)];
            g.jboxes
                .push(String::from_utf8_lossy(ty).trim().to_string());
            match ty {
                b"jxlc" | b"jxlp" => parts.extend_from_slice(body),
                b"Exif" => {
                    g.has_exif = true;
                    // Exif box: 4-byte TIFF offset then TIFF
                    if body.len() > 4 {
                        let t = exif::parse_tiff(&body[4..]);
                        g.exif_orient = t.orientation;
                        g.exif_cs = t.color_space;
                        g.interop = t.interop_index.clone();
                    }
                }
                b"jhgm" => g.gainmap = true,
                _ => {}
            }
            pos = body_end;
        }
        err_if_empty(g, parts)
    } else {
        bare(g, d)
    }
}

fn err_if_empty(g: &mut Got, parts: Vec<u8>) -> Result<(), String> {
    if parts.is_empty() {
        return Err("container JXL: no jxlc/jxlp codestream".into());
    }
    bare(g, &parts)
}

fn bare(g: &mut Got, d: &[u8]) -> Result<(), String> {
    // bare codestream (FF 0A is the *signature codestream* marker too — the
    // jxl signature box contains it; a file starting with FF 0A raw is bare)
    match crate::jxl::get_orientation(d) {
        Ok(o) => g.jorient = Some(o),
        // headers without extra_fields carry no orientation field: spec
        // default is 1 (all_default implies extra_fields unset)
        Err(e) if e.contains("all_default") || e.contains("no orientation field") => {
            g.jorient = Some(1)
        }
        Err(e) => return Err(format!("jxl codestream orientation: {e}")),
    }
    Ok(())
}

// ------------------------------------------------------------- check

fn check(r: &FixtureRow, k: &str, v: &str, g: &Got, dir: &Path) -> Result<(), String> {
    macro_rules! want {
        ($cond:expr, $desc:expr) => {
            if !($cond) {
                return Err(format!("{}: expected {}{} ({})", r.id, k, v, $desc));
            }
        };
    }
    match k {
        "exif" => {
            let want: u8 = v.parse().map_err(|_| format!("bad exif token {v}"))?;
            want!(
                g.exif_orient == Some(want),
                format!("exif_orient={:?}", g.exif_orient)
            );
        }
        "noexif" => want!(!g.has_exif, format!("has_exif={}", g.has_exif)),
        "jfif" => want!(g.jfif, "no JFIF APP0"),
        "app14" => {
            let want: u8 = v.parse().unwrap_or(0);
            want!(g.app14 == Some(want), format!("app14={:?}", g.app14));
        }
        "mpf" => want!(g.mpf, "no MPF APP2"),
        "mpf-corrupt" => want!(g.mpf_offsets_past_eof, "offsets not past EOF"),
        "xmp" => want!(g.xmp, "no XMP APP1"),
        "xmp-orient" => {
            let want: u8 = v.parse().unwrap_or(0);
            want!(
                g.xmp_orient == Some(want),
                format!("xmp_orient={:?}", g.xmp_orient)
            );
        }
        // iso21496 = the ISO 21496-1 APP2 segment specifically (hdrgm-in-XMP
        // is separately asserted via `xmp-hdrgm`).
        "iso21496" => want!(g.iso21496_app2, "no ISO 21496-1 APP2 segment"),
        "noiso21496" => want!(!g.iso21496_app2, "has ISO 21496-1 APP2 segment"),
        "xmp-hdrgm" => want!(g.xmp_hdrgm, "no hdrgm XMP gain-map params"),
        "noxmp" => want!(!g.xmp, "has XMP APP1"),
        "baseline" => want!(g.baseline && !g.progressive, "not baseline-only"),
        "progressive" => want!(g.progressive, "not progressive"),
        "icc" => {
            if v.is_empty() {
                want!(g.icc_sha.is_some(), "no ICC found");
            } else {
                let want_sha = icc_sha_for(v);
                want!(
                    g.icc_sha.as_deref() == Some(want_sha.as_str()),
                    format!("icc_sha={:?} want {v}={want_sha}", g.icc_sha)
                );
                // H6: functional identity — embedded profile must transform
                // like the reference under relcol+perceptual, not just match
                // its sha256.
                let script =
                    Path::new(env!("CARGO_MANIFEST_DIR")).join("scripts/icc_identity_check.py");
                let exe = std::env::current_exe().map_err(|e| e.to_string())?;
                let out = std::process::Command::new("python3")
                    .arg(&script)
                    .arg(dir.join(&r.file))
                    .arg(v)
                    .env("CM_BIN", &exe)
                    .output()
                    .map_err(|e| format!("{}: icc identity spawn: {e}", r.id))?;
                want!(
                    out.status.success(),
                    format!(
                        "icc identity: {}",
                        String::from_utf8_lossy(&out.stdout).trim()
                    )
                );
            }
        }
        "noicc" => want!(g.icc_sha.is_none(), format!("icc_sha={:?}", g.icc_sha)),
        "noorient" => want!(
            g.exif_orient.is_none(),
            format!("exif_orient={:?}", g.exif_orient)
        ),
        "jpeg-clean" => want!(g.baseline || g.progressive, "no SOF0/SOF2 found"),
        "irot" => {
            let want: u8 = v.parse().unwrap_or(0);
            want!(g.irot == Some(want), format!("irot={:?}", g.irot));
        }
        "imir" => {
            let want: u8 = v.parse().unwrap_or(0);
            want!(g.imir == Some(want), format!("imir={:?}", g.imir));
        }
        "nclx" => {
            let p: Vec<u16> = v.split('/').map(|x| x.parse().unwrap_or(0)).collect();
            let want = [p[0], p[1], p[2], p[3]];
            want!(g.nclx == Some(want), format!("nclx={:?}", g.nclx));
        }
        // r13 §2: coded AV1 format assertions from the av1C config record —
        // `av1sub=420` means subsampling_x=1,subsampling_y=1 (AV1 4:2:0),
        // `av1sub=444` means both 0; `av1depth=10` checks high_bitdepth.
        "av1sub" => {
            let want = match v {
                "420" => (true, true),
                "444" => (false, false),
                _ => return Err(format!("{}: bad av1sub token {v}", r.id)),
            };
            want!(
                g.av1c_sub == Some(want),
                format!("av1c_sub={:?} want {v}", g.av1c_sub)
            );
        }
        "av1depth" => {
            let want = v == "10";
            want!(
                g.av1c_highbitdepth == Some(want),
                format!("av1c_highbitdepth={:?} want {v}", g.av1c_highbitdepth)
            );
        }
        "cicp" => {
            let p: Vec<u8> = v.split('/').map(|x| x.parse().unwrap_or(0)).collect();
            want!(
                g.cicp == Some([p[0], p[1], p[2], p[3]]),
                format!("cicp={:?}", g.cicp)
            );
        }
        "prop" => want!(
            g.props.iter().any(|p| p == v),
            format!("props={:?}", g.props)
        ),
        "item" => want!(
            g.items.iter().any(|i| i == v),
            format!("items={:?}", g.items)
        ),
        "dinf" => want!(g.dinf, "no dinf box"),
        "ct" => {
            let want: u8 = v.parse().unwrap_or(0);
            want!(g.png_ct == want, format!("ct={}", g.png_ct));
        }
        "bd" => {
            let want: u8 = v.parse().unwrap_or(0);
            want!(g.png_bd == want, format!("bd={}", g.png_bd));
        }
        "chunk" => want!(
            g.chunks.iter().any(|c| c == v),
            format!("chunks={:?}", g.chunks)
        ),
        "nochunk" => want!(
            !g.chunks.iter().any(|c| c == v),
            format!("chunks={:?}", g.chunks)
        ),
        "colr" => want!(
            g.colr_kinds.iter().any(|c| c == v),
            format!("colr={:?}", g.colr_kinds)
        ),
        "nocolr" => want!(g.colr_kinds.is_empty(), format!("colr={:?}", g.colr_kinds)),
        "proflen" => {
            let want: usize = v.parse().unwrap_or(usize::MAX);
            want!(
                g.prof_len == Some(want),
                format!("prof_len={:?}", g.prof_len)
            );
        }
        "colrany" => want!(
            g.colr_any.iter().any(|c| c == v),
            format!("colr_any={:?}", g.colr_any)
        ),
        "jorient" => {
            let want: u8 = v.parse().unwrap_or(0);
            want!(g.jorient == Some(want), format!("jorient={:?}", g.jorient));
        }
        "jbox" => want!(
            g.jboxes.iter().any(|b| b == v),
            format!("jboxes={:?}", g.jboxes)
        ),
        "jcolour-enum" => want!(g.jcolour_enum, "enum colour expected"),
        "mime" => want!(
            g.mime_ct.as_deref() == Some(v),
            format!("mime_ct={:?}", g.mime_ct)
        ),
        "alpha" => want!(g.has_alpha, "no alpha signalled"),
        "gainmap" => want!(g.gainmap, "no gain-map structure"),
        "exif-cs" => {
            let want: u16 = v.parse().unwrap_or(0);
            want!(g.exif_cs == Some(want), format!("exif_cs={:?}", g.exif_cs));
        }
        "interop" => {
            want!(
                g.interop.as_deref() == Some(v),
                format!("interop={:?}", g.interop)
            );
        }
        _ => return Err(format!("{}: unknown expect token {k}={v}", r.id)),
    }
    Ok(())
}

/// sha256 of the named generated ICC blob (for `icc=` tokens).
fn icc_sha_for(name: &str) -> String {
    use crate::icc;
    let b = match name {
        "srgbv4" => icc::srgb_icc_v4(),
        "p3v4" => icc::display_p3_icc_v4(),
        "p3v2" => icc::display_p3_icc_v2(),
        "adobe" => icc::adobe_rgb_icc_v2(),
        _ => return String::new(),
    };
    crate::generate::sha256_hex_pub(&b)
}
