//! Hypothesis scoring: compare a reader's PNG output against hypothesis
//! renders. Two metrics, both on the <=512-long-side area-average downscale:
//!
//! - pattern fixtures (patch rects): max per-channel centre-mean difference
//!   in 8-bit levels over the named patches, `patch_level_dist`;
//! - corpus fixtures (no rects): per-pixel max-channel difference —
//!   threshold on p99, the per-pixel max is archived alongside.
//!
//! Verdict rules live in `classify_patched`: a hypothesis matches iff its
//! distance is within `t`; collapse pairs (renders the fixture itself
//! cannot separate) decide between a named reading and `not-measurable`.

use zenpixels_convert::PixelBufferConvertTypedExt;

/// RGBA8 image for scoring.
#[derive(Clone)]
pub struct Img {
    pub w: u32,
    pub h: u32,
    pub px: Vec<u8>,
}

pub fn load_png(path: &std::path::Path) -> Result<Img, String> {
    let data = std::fs::read(path).map_err(|e| format!("read: {e}"))?;
    decode_png(&data)
}

pub fn decode_png(data: &[u8]) -> Result<Img, String> {
    // r14 L-2: corpus renders exceed zenpng's default pixel cap (the
    // 16320×7612 glacier rep is 124 MP) — the tool decodes its own
    // trusted renders, so admit up to 1 GP (the 4 GiB memory cap still
    // bounds the allocation).
    let cfg = zenpng::PngDecodeConfig::default().with_max_pixels(1_000_000_000);
    let d =
        zenpng::decode(data, &cfg, &enough::Unstoppable).map_err(|e| format!("png decode: {e}"))?;
    let buf = d.pixels.to_rgba8();
    Ok(Img {
        w: buf.width(),
        h: buf.height(),
        px: buf.copy_to_contiguous_bytes(),
    })
}

// ---- output-profile-aware scoring (r12 coordinator-1, reworked r13 H-1) ---
// A reader whose output PNG carries its own colour tag — Quick Look writes
// Display P3 thumbnails, browsers honour cICP, sips copies the source cHRM —
// emits pixels in the declared space, not necessarily sRGB values. The
// matrix scores both readings: `verdict`/`d1`/`d2` on the raw bytes (the
// historical column — what an application that ignores the tag gets) and
// `verdict_tagged`/… on the pixels interpreted through the declared profile
// (what a colour-managed viewer gets). Tag selection follows PNG-3e §11.3.2
// precedence — cICP > iCCP > sRGB > gAMA+cHRM — not file order.

/// Colour tag found in an output PNG's ancillary chunks.
pub enum OutProfile {
    /// Inflated ICC profile bytes from `iCCP`.
    Icc(Vec<u8>),
    /// cICP code points (CP, TC, MC, range flag).
    Cicp(zenpixels::Cicp),
    /// `sRGB` chunk — sRGB declared.
    Srgb,
    /// `gAMA` + `cHRM` pair — a colour declaration in PNG-3e (gamma ×1e5;
    /// cHRM xy pairs ×1e5). `cHRM` may be absent (gamma-only declaration).
    GamaChrm { gama: u32, chrm: Option<[u32; 8]> },
}

/// Parse a PNG byte stream's colour chunks (`iCCP`, `cICP`, `sRGB`, `gAMA`,
/// `cHRM`) without decoding pixels. Returns the tag that PNG-3e precedence
/// selects — cICP > iCCP > sRGB > gAMA+cHRM (gAMA alone last) — regardless
/// of file order. Stops at `IDAT`: colour chunks precede image data.
pub fn png_out_profile(png: &[u8]) -> Option<OutProfile> {
    if png.len() < 8 || png[..8] != *b"\x89PNG\r\n\x1a\n" {
        return None;
    }
    let mut icc = None;
    let mut cicp = None;
    let mut srgb = false;
    let mut gama = None;
    let mut chrm = None;
    let mut pos = 8;
    while pos + 8 <= png.len() {
        let len = u32::from_be_bytes(png[pos..pos + 4].try_into().ok()?) as usize;
        let ty = &png[pos + 4..pos + 8];
        let end = pos + 8 + len;
        if end + 4 > png.len() {
            break;
        }
        let data = &png[pos + 8..end];
        match ty {
            b"iCCP" => {
                // profile name (latin-1, NUL) + compression byte + zlib ICC
                if icc.is_none()
                    && let Some(nul) = data.iter().position(|b| *b == 0)
                    && data.get(nul + 1) == Some(&0)
                    && let Ok(p) = miniz_oxide::inflate::decompress_to_vec_zlib(&data[nul + 2..])
                {
                    icc = Some(p);
                }
            }
            b"cICP" if data.len() >= 4 => {
                if cicp.is_none() {
                    cicp = Some(zenpixels::Cicp::new(
                        data[0],
                        data[1],
                        data[2],
                        data[3] & 1 == 1,
                    ));
                }
            }
            b"sRGB" => srgb = true,
            b"gAMA" if data.len() == 4 => {
                gama.get_or_insert(u32::from_be_bytes(data.try_into().ok()?));
            }
            b"cHRM" if data.len() == 32 => {
                if chrm.is_none() {
                    let mut v = [0u32; 8];
                    for (i, c) in data.as_chunks::<4>().0.iter().enumerate() {
                        v[i] = u32::from_be_bytes(*c);
                    }
                    chrm = Some(v);
                }
            }
            b"IDAT" => break,
            _ => {}
        }
        pos = end + 4;
    }
    cicp.map(OutProfile::Cicp)
        .or_else(|| icc.map(OutProfile::Icc))
        .or(if srgb { Some(OutProfile::Srgb) } else { None })
        .or_else(|| {
            gama.map(|g| OutProfile::GamaChrm { gama: g, chrm })
                .or_else(|| {
                    chrm.map(|c| OutProfile::GamaChrm {
                        gama: 0,
                        chrm: Some(c),
                    })
                })
        })
}

/// `desc`-tag text of an ICC profile for row naming — v2 `desc` bodies and
/// v4 `mluc` bodies both surface (empty on parse fail).
fn icc_desc(icc: &[u8]) -> String {
    if icc.len() < 132 {
        return String::new();
    }
    let be = |o: usize| -> usize { u32::from_be_bytes(icc[o..o + 4].try_into().unwrap()) as usize };
    let n = be(128);
    for i in 0..n {
        let e = 132 + i * 12;
        if e + 12 > icc.len() || icc[e..e + 4] != *b"desc" {
            continue;
        }
        let (off, sz) = (be(e + 4), be(e + 8));
        if off + sz > icc.len() || sz < 12 {
            return String::new();
        }
        return match &icc[off..off + 4] {
            b"desc" => {
                let len = be(off + 8);
                String::from_utf8_lossy(
                    &icc[off + 12..(off + 12 + len.saturating_sub(1)).min(off + sz)],
                )
                .trim()
                .to_string()
            }
            b"mluc" => {
                // first localized record: lang(2) country(2) len(4) off(4),
                // UTF-16BE text relative to the tag body start
                let (cnt, recs) = (be(off + 8), be(off + 12));
                if cnt == 0 || recs < 12 || off + 16 + recs > icc.len() {
                    return String::new();
                }
                let (tl, to) = (be(off + 16 + 4), be(off + 16 + 8));
                if off + to + tl > icc.len() {
                    return String::new();
                }
                icc[off + to..off + to + tl]
                    .as_chunks::<2>()
                    .0
                    .iter()
                    .map(|c| u16::from_be_bytes(*c))
                    .map(|u| char::from_u32(u as u32).unwrap_or(' '))
                    .collect::<String>()
                    .trim()
                    .to_string()
            }
            _ => String::new(),
        };
    }
    String::new()
}

fn cicp_is_srgb(c: &zenpixels::Cicp) -> bool {
    // CP=1 (BT.709) + TC=13 (sRGB) + MC=0 (identity/RGB) — the cICP sRGB
    // declaration; the range flag does not change pixel semantics here.
    c.color_primaries == 1 && c.transfer_characteristics == 13 && c.matrix_coefficients == 0
}

/// cICP HDR transfer code points (PQ / HLG): a reader emitting these
/// declares a rendition no sRGB comparison can grade.
fn cicp_is_hdr(c: &zenpixels::Cicp) -> bool {
    matches!(c.transfer_characteristics, 16..=18)
}

/// ICC `desc`/`mluc` text that names an HDR transfer — moxcms may still
/// "convert" such a profile, but the sRGB-headed result isn't the reader's
/// declared rendition, so these score `hdr-output`, not a distance.
fn icc_declares_hdr(icc: &[u8]) -> bool {
    let d = icc_desc(icc).to_lowercase();
    d.contains("pq")
        || d.contains("hlg")
        || d.contains("2084")
        || d.contains("gain map")
        || d.contains("hdr")
}

/// cHRM xy pairs (×1e5) → a known primaries set, ±0.005 per coordinate.
fn chrm_primaries(chrm: &[u32; 8]) -> Option<zenpixels::ColorPrimaries> {
    use zenpixels::ColorPrimaries as P;
    let tol = 500i64; // 0.005 in ×1e5 units
    let close = |got: [u32; 8], want: [u32; 8]| {
        got.iter()
            .zip(want.iter())
            .all(|(g, w)| (*g as i64 - *w as i64).abs() <= tol)
    };
    // order: wx wy rx ry gx gy bx by — sRGB/BT.709 D65, Display-P3 D65,
    // BT.2020 D65, Adobe RGB D65.
    const SRGB: [u32; 8] = [31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000];
    const P3: [u32; 8] = [31270, 32900, 68000, 32000, 26500, 69000, 15000, 6000];
    const BT2020: [u32; 8] = [31270, 32900, 70800, 29200, 17000, 79700, 13100, 4600];
    const ADOBE: [u32; 8] = [31270, 32900, 64000, 33000, 21000, 71000, 15000, 6000];
    if close(*chrm, SRGB) {
        Some(P::Bt709)
    } else if close(*chrm, P3) {
        Some(P::DisplayP3)
    } else if close(*chrm, BT2020) {
        Some(P::Bt2020)
    } else if close(*chrm, ADOBE) {
        Some(P::AdobeRgb)
    } else {
        None
    }
}

fn primaries_name(p: zenpixels::ColorPrimaries) -> &'static str {
    use zenpixels::ColorPrimaries as P;
    match p {
        P::Bt709 => "bt709",
        P::DisplayP3 => "p3",
        P::Bt2020 => "bt2020",
        P::AdobeRgb => "adobe",
        _ => "unknown",
    }
}

/// ICC matrix colourants (rXYZ/gXYZ/bXYZ, D50-adapted) → a known primaries
/// set. Compared against the canonical D50 colourant values the fixtures
/// and common reader ICCs carry, ±0.01 per XYZ component.
fn icc_primaries(icc: &[u8]) -> Option<zenpixels::ColorPrimaries> {
    use zenpixels::ColorPrimaries as P;
    if icc.len() < 132 {
        return None;
    }
    let be = |o: usize| -> usize { u32::from_be_bytes(icc[o..o + 4].try_into().unwrap()) as usize };
    let tag_xyz = |sig: &[u8; 4]| -> Option<[f64; 3]> {
        let n = be(128);
        for i in 0..n {
            let e = 132 + i * 12;
            if e + 12 > icc.len() {
                return None;
            }
            if &icc[e..e + 4] == sig {
                let (off, sz) = (be(e + 4), be(e + 8));
                // 'XYZ ' type: 8-byte header + three s15Fixed16 numbers
                if off + 20 > icc.len() || sz < 20 || icc[off..off + 4] != *b"XYZ " {
                    return None;
                }
                let f = |o: usize| {
                    i32::from_be_bytes(icc[o..o + 4].try_into().unwrap()) as f64 / 65536.0
                };
                return Some([f(off + 8), f(off + 12), f(off + 16)]);
            }
        }
        None
    };
    let (r, g, b) = (tag_xyz(b"rXYZ")?, tag_xyz(b"gXYZ")?, tag_xyz(b"bXYZ")?);
    let close = |got: [f64; 3], want: [f64; 3]| {
        got.iter()
            .zip(want.iter())
            .all(|(a, b)| (*a - *b).abs() <= 0.01)
    };
    let at = |m: [[f64; 3]; 3]| close(r, m[0]) && close(g, m[1]) && close(b, m[2]);
    // D50-adapted RGB→XYZ colourant columns of the spaces fixtures declare.
    const SRGB_D50: [[f64; 3]; 3] = [
        [0.4360, 0.2225, 0.0139],
        [0.3851, 0.7169, 0.0971],
        [0.1431, 0.0606, 0.7141],
    ];
    const P3_D50: [[f64; 3]; 3] = [
        [0.5151, 0.2412, -0.0011],
        [0.2920, 0.6922, 0.0419],
        [0.1571, 0.0666, 0.7841],
    ];
    const ADOBE_D50: [[f64; 3]; 3] = [
        [0.6097, 0.3111, 0.0195],
        [0.2053, 0.6255, 0.0609],
        [0.1492, 0.0632, 0.7446],
    ];
    const BT2020_D50: [[f64; 3]; 3] = [
        [0.6734, 0.2790, -0.0019],
        [0.1656, 0.6753, 0.0299],
        [0.1254, 0.0458, 0.7966],
    ];
    if at(SRGB_D50) {
        Some(P::Bt709)
    } else if at(P3_D50) {
        Some(P::DisplayP3)
    } else if at(ADOBE_D50) {
        Some(P::AdobeRgb)
    } else if at(BT2020_D50) {
        Some(P::Bt2020)
    } else {
        None
    }
}

/// The primaries a colour source declares — for the mis-tag check's "tag
/// names the source space" test.
fn src_primaries(src: &OwnedSrc) -> Option<zenpixels::ColorPrimaries> {
    use zenpixels::ColorPrimaries as P;
    match src {
        OwnedSrc::Cicp(c) => match c.color_primaries {
            1 => Some(P::Bt709),
            9 => Some(P::Bt2020),
            12 => Some(P::DisplayP3),
            _ => None,
        },
        OwnedSrc::PrimTransfer { primaries, .. } => Some(*primaries),
        OwnedSrc::Icc(b) => icc_primaries(b),
    }
}

/// An owned colour source the scorer can convert through (ICC bytes can't
/// borrow the parse buffer — `png_out_profile` hands them over).
enum OwnedSrc {
    Cicp(zenpixels::Cicp),
    Icc(Vec<u8>),
    PrimTransfer {
        primaries: zenpixels::ColorPrimaries,
        transfer: zenpixels::TransferFunction,
    },
}

impl OwnedSrc {
    fn as_source(&self) -> zenpixels::ColorProfileSource<'_> {
        match self {
            Self::Cicp(c) => zenpixels::ColorProfileSource::Cicp(*c),
            Self::Icc(b) => zenpixels::ColorProfileSource::Icc(b),
            Self::PrimTransfer {
                primaries,
                transfer,
            } => zenpixels::ColorProfileSource::PrimariesTransferPair {
                primaries: *primaries,
                transfer: *transfer,
            },
        }
    }
}

/// What the output's colour tag means for scoring.
enum TagKind {
    /// sRGB-equivalent declaration — scored pixels are the raw pixels.
    Identity,
    /// Interpret through this profile (relcol convert to sRGB).
    Convert(OwnedSrc),
    /// HDR declaration — named `hdr-output`, no distance grading.
    Hdr,
    /// Declaration present but not interpretable by this scorer
    /// (gAMA without cHRM, unknown primaries, CMM failure).
    Unhandled,
}

/// Resolve the tag to (recorded `out_profile` name, scoring action).
/// For ICC sources the transform is built once here so the sRGB
/// equivalence probe and the real conversion share it — an ICC that
/// converts probe pixels to themselves IS sRGB whatever its desc says.
fn tag_plan(prof: Option<OutProfile>) -> (String, TagKind) {
    use zenpixels_convert::cms::PluggableCms;
    let p = match prof {
        None => return (String::new(), TagKind::Identity),
        Some(p) => p,
    };
    match p {
        OutProfile::Srgb => ("srgb".into(), TagKind::Identity),
        OutProfile::Cicp(c) => {
            let name = format!(
                "cicp:{},{},{}",
                c.color_primaries, c.transfer_characteristics, c.matrix_coefficients
            );
            if cicp_is_srgb(&c) {
                ("cicp-srgb".into(), TagKind::Identity)
            } else if cicp_is_hdr(&c) {
                (name, TagKind::Hdr)
            } else {
                (name, TagKind::Convert(OwnedSrc::Cicp(c)))
            }
        }
        OutProfile::Icc(icc) => {
            let name = format!("icc:{}", icc_desc(&icc));
            if icc_declares_hdr(&icc) {
                return (name, TagKind::Hdr);
            }
            // sRGB-equivalence by measurement: build the transform and run
            // a probe ramp through it — libjxl "sRGB built-in", the
            // generated "sRGB compat-matrix" and IEC61966-2.1 profiles all
            // collapse to identity here, whatever the desc text says.
            match zenpixels_convert::MoxCms.build_source_transform(
                zenpixels::ColorProfileSource::Icc(&icc),
                zenpixels::ColorProfileSource::Named(zenpixels::NamedProfile::Srgb),
                zenpixels::PixelFormat::Rgba8,
                zenpixels::PixelFormat::Rgba8,
                &zenpixels::ConvertOptions::permissive(),
            ) {
                Some(Ok(mut t)) => {
                    if transform_is_identity(&mut *t) {
                        (format!("icc-srgb:{}", icc_desc(&icc)), TagKind::Identity)
                    } else {
                        (name, TagKind::Convert(OwnedSrc::Icc(icc)))
                    }
                }
                _ => (format!("{name}(unconverted)"), TagKind::Unhandled),
            }
        }
        OutProfile::GamaChrm { gama, chrm } => {
            let g = gama as f64 / 100_000.0;
            let (prim, pname) = match chrm.as_ref().and_then(chrm_primaries) {
                Some(p) => (p, primaries_name(p)),
                None => {
                    if chrm.is_none() {
                        return (format!("gama:{g:.4}"), TagKind::Unhandled);
                    }
                    return ("gama-chrm:custom-primaries".into(), TagKind::Unhandled);
                }
            };
            // r14 L-8: a cHRM with no gAMA declares primaries but no decode
            // gamma — label it `chrm-only`, not a nonsense `g0.000`.
            if gama == 0 {
                return (format!("chrm-only:{pname}"), TagKind::Unhandled);
            }
            let name = format!("gama-chrm:{pname}");
            // sRGB declaration: sRGB primaries + ~2.2 gamma.
            if prim == zenpixels::ColorPrimaries::Bt709 && (g - 0.4545).abs() < 0.05 {
                return ("gama-chrm:srgb".into(), TagKind::Identity);
            }
            let tf = if (g - 0.4545).abs() < 0.05 {
                zenpixels::TransferFunction::Gamma22
            } else if (g - 1.0).abs() < 0.02 {
                zenpixels::TransferFunction::Linear
            } else {
                return (format!("{name}@g{g:.3}"), TagKind::Unhandled);
            };
            (
                name,
                TagKind::Convert(OwnedSrc::PrimTransfer {
                    primaries: prim,
                    transfer: tf,
                }),
            )
        }
    }
}

/// Probe whether a row transform is the identity on a representative
/// ramp — 256 grays + a saturated R/G/B sweep; ±1 8-bit level tolerance.
fn transform_is_identity(t: &mut dyn zenpixels_convert::cms::RowTransformMut) -> bool {
    let mut inp = Vec::with_capacity((256 + 18 * 4 * 3) * 4);
    for v in 0..=255u8 {
        inp.extend_from_slice(&[v, v, v, 255]);
    }
    for i in 0..18u16 {
        let v = (i * 255 / 17) as u8;
        inp.extend_from_slice(&[v, 0, 0, 255]);
        inp.extend_from_slice(&[0, v, 0, 255]);
        inp.extend_from_slice(&[0, 0, v, 255]);
        inp.extend_from_slice(&[v, v, 0, 255]);
    }
    let n = (inp.len() / 4) as u32;
    let mut out = vec![0u8; inp.len()];
    t.transform_row(&inp, &mut out, n);
    inp.as_chunks::<4>()
        .0
        .iter()
        .zip(out.as_chunks::<4>().0.iter())
        .all(|(a, b)| {
            a.iter()
                .zip(b.iter())
                .all(|(x, y)| (*x as i32 - *y as i32).abs() <= 1)
        })
}

/// gAMA+cHRM conversion without a CMM: linearize by the declared decode
/// exponent, apply the primaries→BT.709 gamut matrix in linear light,
/// re-encode through the sRGB OETF. moxcms can't carry gamma-2.2 or Adobe
/// primaries through the CICP path, so this pair is handled directly.
fn convert_prim_transfer(
    primaries: zenpixels::ColorPrimaries,
    transfer: zenpixels::TransferFunction,
    img: &Img,
) -> Option<Img> {
    let gamma_dec = match transfer {
        zenpixels::TransferFunction::Gamma22 => 2.2f64,
        zenpixels::TransferFunction::Linear => 1.0,
        _ => return None,
    };
    let m = primaries.gamut_matrix_to(zenpixels::ColorPrimaries::Bt709)?;
    let oetf = |l: f64| -> u8 {
        let c = l.clamp(0.0, 1.0);
        let e = if c <= 0.0031308 {
            12.92 * c
        } else {
            1.055 * c.powf(1.0 / 2.4) - 0.055
        };
        (e * 255.0).round().clamp(0.0, 255.0) as u8
    };
    let mut out = vec![0u8; img.px.len()];
    for (d, s) in out
        .as_chunks_mut::<4>()
        .0
        .iter_mut()
        .zip(img.px.as_chunks::<4>().0.iter())
    {
        let l = [
            (s[0] as f64 / 255.0).powf(gamma_dec) as f32,
            (s[1] as f64 / 255.0).powf(gamma_dec) as f32,
            (s[2] as f64 / 255.0).powf(gamma_dec) as f32,
        ];
        for k in 0..3 {
            d[k] = oetf((m[k][0] * l[0] + m[k][1] * l[1] + m[k][2] * l[2]) as f64);
        }
        d[3] = s[3];
    }
    Some(Img {
        w: img.w,
        h: img.h,
        px: out,
    })
}

/// Apply a source-profile transform to a copy of `img` (RGBA8 row
/// transform). Returns None when the CMM declines.
fn convert_with(src: &OwnedSrc, img: &Img) -> Option<Img> {
    if let OwnedSrc::PrimTransfer {
        primaries,
        transfer,
    } = src
    {
        return convert_prim_transfer(*primaries, *transfer, img);
    }
    use zenpixels_convert::cms::PluggableCms;
    let t = zenpixels_convert::MoxCms.build_source_transform(
        src.as_source(),
        zenpixels::ColorProfileSource::Named(zenpixels::NamedProfile::Srgb),
        zenpixels::PixelFormat::Rgba8,
        zenpixels::PixelFormat::Rgba8,
        &zenpixels::ConvertOptions::permissive(),
    );
    let mut t = match t {
        Some(Ok(t)) => t,
        _ => return None,
    };
    let stride = img.w as usize * 4;
    let mut out = vec![0u8; img.px.len()];
    for y in 0..img.h as usize {
        t.transform_row(
            &img.px[y * stride..(y + 1) * stride],
            &mut out[y * stride..(y + 1) * stride],
            img.w,
        );
    }
    Some(Img {
        w: img.w,
        h: img.h,
        px: out,
    })
}

/// Which interpretation an output tag produced — calibration callers use
/// `Hdr` to exclude the cell (it isn't an sRGB-comparable reading).
#[derive(Clone, Copy, PartialEq)]
pub enum OutInterp {
    /// Raw pixels stand (untagged, or sRGB-equivalent declaration).
    Identity,
    /// Converted through the declared profile to sRGB.
    Converted,
    /// Declaration present but not interpretable — raw pixels stand.
    Unhandled,
    /// HDR declaration — no sRGB comparison applies.
    Hdr,
}

/// Interpret an output PNG's pixels under its own colour tag: the image a
/// colour-managed viewer gets. Returns (pixels, recorded tag name, kind).
/// Used by calibration so the fold measures the same pixels the tagged
/// matrix column scores.
pub fn out_tagged_pixels(img: &Img, png: &[u8]) -> (Img, String, OutInterp) {
    let (name, kind) = tag_plan(png_out_profile(png));
    match kind {
        TagKind::Identity => (img.clone(), name, OutInterp::Identity),
        TagKind::Hdr => (img.clone(), name, OutInterp::Hdr),
        TagKind::Unhandled => (img.clone(), name, OutInterp::Unhandled),
        TagKind::Convert(src) => match convert_with(&src, img) {
            Some(i) => (i, name, OutInterp::Converted),
            None => (
                img.clone(),
                format!("{name}(unconverted)"),
                OutInterp::Unhandled,
            ),
        },
    }
}

/// Tagged-interpretation result for one cell.
pub struct TaggedScore {
    pub verdict: String,
    /// "true" / "false" / "n/a" (hdr-output).
    pub correct: &'static str,
    pub d1: f64,
    pub d2: f64,
    pub profile: String,
}

/// Splice the colour chunks of `src` (a full render) into `dst` (its
/// thumbnail re-encode), inserting before the first IDAT. Copies cICP,
/// iCCP, sRGB, gAMA, cHRM records verbatim — a stored cell render stays
/// gradeable under its own output tag (r13: thumbs carry the source's
/// colour declaration).
pub fn png_copy_colour_chunks(dst: &mut Vec<u8>, src: &[u8]) {
    let mut kept: Vec<&[u8]> = Vec::new();
    let mut off = 8usize;
    while off + 8 <= src.len() {
        let len = u32::from_be_bytes(src[off..off + 4].try_into().unwrap()) as usize;
        let end = off + 12 + len;
        if end > src.len() {
            break;
        }
        let ty = &src[off + 4..off + 8];
        if ty == b"IDAT" {
            break;
        }
        if matches!(ty, b"cICP" | b"iCCP" | b"sRGB" | b"gAMA" | b"cHRM") {
            kept.push(&src[off..end]);
        }
        off = end;
    }
    if kept.is_empty() {
        return;
    }
    // dst = signature + IHDR + [insert here] + rest (a fresh encode has no
    // colour chunks of its own).
    let mut at = 8usize;
    while at + 8 <= dst.len() {
        let len = u32::from_be_bytes(dst[at..at + 4].try_into().unwrap()) as usize;
        if &dst[at + 4..at + 8] == b"IDAT" || at + 12 + len > dst.len() {
            break;
        }
        at += 12 + len;
    }
    let tail = dst.split_off(at);
    for c in kept {
        dst.extend_from_slice(c);
    }
    dst.extend_from_slice(&tail);
}

/// The `correct` rule shared by both scorings: a named verdict certifies
/// only when it names a correct-labelled hyp; `not-measurable` certifies
/// unless the note is the corpus margin rule (which names nothing) or a
/// tie whose tied pair carries no correct-labelled hyp (r14 H-1 — a tie
/// is emitted only from a within-T branch, but proximity alone certifies
/// nothing when neither reading is the correct one); a collapse clique
/// including a correct hyp certifies by construction.
pub fn verdict_correct(verdict: &str, note: &str, scored: &[Scored]) -> bool {
    if verdict == "not-measurable" {
        if note.starts_with("margin") {
            false
        } else if note.starts_with("tie:") {
            scored.len() >= 2
                && scored[1].dist - scored[0].dist < FINE_T
                && (scored[0].correct || scored[1].correct)
        } else {
            true
        }
    } else if verdict == "other" {
        false
    } else {
        scored.iter().any(|s| s.name == verdict && s.correct)
    }
}

/// The raw scoring of a cell — the evidence `classify_tagged` needs for
/// the mis-tag check and the as-is fallback columns.
pub struct RawScoring<'a> {
    pub scored: &'a [Scored],
    pub verdict: &'a str,
    pub correct: bool,
    /// The fixture's declared colour — the mis-tag check compares the
    /// output tag's primaries against it (r14 M-1 condition b).
    pub src_colour: crate::manifest::Colour,
}

/// The colour space a fixture declares — the mis-tag check compares the
/// output tag's primaries against it (r14 M-1 condition b). `Untagged`
/// and `Uncalibrated` have no declared space: the tag can never name it.
fn declared_primaries(c: crate::manifest::Colour) -> Option<zenpixels::ColorPrimaries> {
    use crate::manifest::Colour as C;
    use zenpixels::ColorPrimaries as P;
    match c {
        C::Srgb => Some(P::Bt709),
        C::P3 => Some(P::DisplayP3),
        C::AdobeRgb => Some(P::AdobeRgb),
        C::Untagged | C::Uncalibrated => None,
    }
}

/// Score a cell under its own output colour tag (the tagged column).
/// `raw` carries the raw scoring so the mis-tag check can see whether the
/// raw pixels already match a documented hypothesis within FINE_T while
/// the declared interpretation lands strictly worse (djxl-best 0.12 case:
/// pixels converted, tag still declares the source space). The fixture's
/// declared colour rides in `raw.src_colour` — the mis-tag label fires
/// only when the tag's primaries equal it (r14 M-1).
pub fn classify_tagged(
    raw_img: &Img,
    png: &[u8],
    raw: &RawScoring<'_>,
    hyps: &[HypIn],
    t: f64,
    max_side: u32,
    collapsed: &[(String, String, f64, f64)],
) -> TaggedScore {
    let (name, kind) = tag_plan(png_out_profile(png));
    let raw_correct_str = if raw.correct { "true" } else { "false" };
    let as_raw = |profile: String| TaggedScore {
        verdict: raw.verdict.to_string(),
        correct: raw_correct_str,
        d1: raw.scored.first().map(|s| s.dist).unwrap_or(f64::INFINITY),
        d2: raw.scored.get(1).map(|s| s.dist).unwrap_or(f64::INFINITY),
        profile,
    };
    match kind {
        TagKind::Identity => as_raw(name),
        TagKind::Hdr => TaggedScore {
            verdict: "hdr-output".into(),
            correct: "n/a",
            d1: raw.scored.first().map(|s| s.dist).unwrap_or(f64::INFINITY),
            d2: raw.scored.get(1).map(|s| s.dist).unwrap_or(f64::INFINITY),
            profile: name,
        },
        TagKind::Unhandled => as_raw(name),
        TagKind::Convert(src) => {
            let img = match convert_with(&src, raw_img) {
                Some(i) => i,
                None => return as_raw(format!("{name}(unconverted)")),
            };
            let (v, scored, note) = classify_patched(&img, hyps, t, max_side, collapsed);
            let d1 = scored.first().map(|s| s.dist).unwrap_or(f64::INFINITY);
            let d2 = scored.get(1).map(|s| s.dist).unwrap_or(f64::INFINITY);
            // Mis-tag (r14 M-1): fires only when BOTH hold —
            //   (a) the raw reading is a managed hypothesis: it names a
            //       correct-labelled hyp or a `*-as-<dest>` converted
            //       reading (an unmanaged `stored`/`orient-only` passthrough
            //       whose tag honestly describes its pixels is not a
            //       mis-tag — the tagged reading is the honest conversion);
            //   (b) the tag's primaries equal the fixture's declared source
            //       colour — the tag names the source space (djxl-best 0.12
            //       keeps a P3 tag on pixels converted to sRGB; converting
            //       again lands strictly worse).
            // plus the distance test that r13 carried: the raw pixels sit
            // within FINE_T of a hypothesis while the managed
            // interpretation lands strictly worse.
            let raw_d = raw.scored.first().map(|s| s.dist).unwrap_or(f64::INFINITY);
            let raw_managed = raw.verdict != "not-measurable"
                && raw.verdict != "other"
                && (raw
                    .scored
                    .iter()
                    .find(|s| s.name == raw.verdict)
                    .map(|s| s.correct)
                    .unwrap_or(false)
                    || raw.verdict.contains("-as-"));
            let tag_names_source = match (declared_primaries(raw.src_colour), src_primaries(&src)) {
                (Some(w), Some(g)) => w == g,
                _ => false,
            };
            if raw_managed && tag_names_source && raw_d <= FINE_T && d1 - raw_d > FINE_T {
                return TaggedScore {
                    verdict: format!("mis-tagged:{}", raw.verdict),
                    correct: raw_correct_str,
                    d1: raw.scored.first().map(|s| s.dist).unwrap_or(f64::INFINITY),
                    d2: raw.scored.get(1).map(|s| s.dist).unwrap_or(f64::INFINITY),
                    profile: name,
                };
            }
            TaggedScore {
                correct: if verdict_correct(&v, &note, &scored) {
                    "true"
                } else {
                    "false"
                },
                verdict: v,
                d1,
                d2,
                profile: name,
            }
        }
    }
}

/// Area-average downscale so the long side is <= `max_side`.
/// Integer box filter: output pixel = mean of its source footprint.
pub fn downscale(img: &Img, max_side: u32) -> Img {
    let long = img.w.max(img.h);
    if long <= max_side {
        return img.clone();
    }
    let scale = long as f64 / max_side as f64;
    let dw = ((img.w as f64 / scale).round() as u32).max(1);
    let dh = ((img.h as f64 / scale).round() as u32).max(1);
    let mut px = vec![0u8; (dw * dh * 4) as usize];
    for y in 0..dh {
        let y0 = (y as f64 * scale) as u32;
        let y1 = (((y + 1) as f64 * scale) as u32).min(img.h).max(y0 + 1);
        for x in 0..dw {
            let x0 = (x as f64 * scale) as u32;
            let x1 = (((x + 1) as f64 * scale) as u32).min(img.w).max(x0 + 1);
            let mut acc = [0u64; 4];
            let n = ((x1 - x0) * (y1 - y0)) as u64;
            for sy in y0..y1 {
                for sx in x0..x1 {
                    let i = ((sy * img.w + sx) * 4) as usize;
                    for (c, a) in acc.iter_mut().enumerate() {
                        *a += img.px[i + c] as u64;
                    }
                }
            }
            let o = ((y * dw + x) * 4) as usize;
            for c in 0..4 {
                px[o + c] = (acc[c] / n) as u8;
            }
        }
    }
    Img { w: dw, h: dh, px }
}

/// Per-pixel max-channel absolute difference (RGBA), returned as
/// (p99, max) in 8-bit levels; (+inf, +inf) on dimension mismatch.
/// Whole-image MAD dilutes localized strong differences — e.g. a primaries
/// swap on a mostly-dark photo moves only the saturated tail. p99 sees it.
pub fn p99_max(a: &Img, b: &Img) -> (f64, f64) {
    if a.w != b.w || a.h != b.h {
        return (f64::INFINITY, f64::INFINITY);
    }
    let n = a.px.len() / 4;
    let mut v: Vec<u8> = Vec::with_capacity(n);
    for i in 0..n {
        let o = i * 4;
        let m = (a.px[o] as i64 - b.px[o] as i64)
            .unsigned_abs()
            .max((a.px[o + 1] as i64 - b.px[o + 1] as i64).unsigned_abs())
            .max((a.px[o + 2] as i64 - b.px[o + 2] as i64).unsigned_abs())
            .max((a.px[o + 3] as i64 - b.px[o + 3] as i64).unsigned_abs());
        v.push(m as u8);
    }
    v.sort_unstable();
    let i99 = ((n as f64 * 0.99) as usize).min(n - 1);
    (v[i99] as f64, *v.last().unwrap() as f64)
}

/// Run-dir thumb long side (M-6): `compat-matrix thumb` box-downscales
/// to this, and corpus compares route every input through the same
/// stage-1, so a stored thumb, a full-res render, and a full-res
/// hypothesis of the same pixels converge on the same <=512
/// representation (a Lanczos thumb would diverge from the box chain
/// by ~17 p99 on photo detail).
pub const THUMB_SIDE: u32 = 1024;

/// Collapse bound for hypothesis pairs: two renders are indistinguishable
/// only when their distance stays within the fine decode-noise bound (the
/// libde265/heif-convert spread, ~1 level p99). The wide corpus match
/// threshold (cross-decoder tolerance, ~24) selects the *nearest*
/// hypothesis — it must not collapse readings the fixture separates, or a
/// reader 21 levels off the correct render would still certify it (H-2).
pub const FINE_T: f64 = 2.0;

/// Canonical corpus compare space: stage-1 box downscale to
/// [`THUMB_SIDE`] (== the run-dir thumb's own transform), then to
/// `max_side`. Two-stage by construction so thumb'd cells classify
/// identically to full-res renders.
pub fn corpus_space(img: &Img, max_side: u32) -> Img {
    downscale(&downscale(img, THUMB_SIDE), max_side)
}

/// Corpus-fixture distance = (p99, max) per-pixel max-channel diff. The
/// synth patch rects don't exist on photo content; the tail statistic is
/// what discriminates renditions. Classification thresholds on p99; the
/// max rides along for the record (a p99 36 / max 104 split is "patchy"
/// divergence, not uniform).
pub fn corpus_dist(a: &Img, b: &Img) -> (f64, f64) {
    p99_max(a, b)
}

/// A scored hypothesis row: `dist` is the match metric (patch-centre max
/// or corpus p99), `dmax` the corpus per-pixel max (== dist on pattern
/// fixtures, where the metric is already a max-of-means).
pub struct Scored {
    pub name: String,
    pub dist: f64,
    pub dmax: f64,
    pub correct: bool,
}

// ------------------------------------------------- mapped patch metric ----

/// Rect in image coordinates (a named pattern patch mapped through the
/// hypothesis' orientation steps).
#[derive(Clone, Copy, Debug)]
pub struct Rect {
    pub x: u32,
    pub y: u32,
    pub w: u32,
    pub h: u32,
}

/// Map `r` through EXIF orientation `o` applied to a `w`x`h` image.
/// Returns the rect in the output image's coordinates plus the new dims.
pub fn map_rect_orient(r: Rect, w: u32, h: u32, o: u8) -> (Rect, u32, u32) {
    let (x, y, rw, rh) = (r.x, r.y, r.w, r.h);
    match o {
        1 => (r, w, h),
        2 => (
            Rect {
                x: w - x - rw,
                y,
                w: rw,
                h: rh,
            },
            w,
            h,
        ),
        3 => (
            Rect {
                x: w - x - rw,
                y: h - y - rh,
                w: rw,
                h: rh,
            },
            w,
            h,
        ),
        4 => (
            Rect {
                x,
                y: h - y - rh,
                w: rw,
                h: rh,
            },
            w,
            h,
        ),
        // 5-8 transpose: output dims swap.
        5 => (
            Rect {
                x: y,
                y: x,
                w: rh,
                h: rw,
            },
            h,
            w,
        ),
        // 6 = rotate 90 CW: (x,y) -> (H-y, x)
        6 => (
            Rect {
                x: h - y - rh,
                y: x,
                w: rh,
                h: rw,
            },
            h,
            w,
        ),
        // 7 = transverse (transpose + 180): (x,y) -> (W-x, H-y) then transpose
        7 => (
            Rect {
                x: h - y - rh,
                y: w - x - rw,
                w: rh,
                h: rw,
            },
            h,
            w,
        ),
        // 8 = rotate 90 CCW: (x,y) -> (y, W-x)
        8 => (
            Rect {
                x: y,
                y: w - x - rw,
                w: rh,
                h: rw,
            },
            h,
            w,
        ),
        _ => (r, w, h),
    }
}

/// Mean of the inner half of `r` over all 4 channels (RGB + alpha) — the
/// patch-centre sample the round-2 review prescribes, extended in round 7 so
/// the alpha ramp band can actually distinguish alpha hypotheses.
fn patch_center_mean(img: &Img, r: Rect) -> [f64; 4] {
    let (x0, y0) = (r.x + r.w / 4, r.y + r.h / 4);
    let (x1, y1) = (r.x + r.w * 3 / 4, r.y + r.h * 3 / 4);
    let mut acc = [0u64; 4];
    let mut n = 0u64;
    // A rect entirely outside the image must NOT collapse to [0,0,0,0] —
    // two sides both missing coverage would "match" at distance 0.
    if x0 >= img.w || y0 >= img.h {
        return [f64::NAN; 4];
    }
    for yy in y0..y1.max(y0 + 1).min(img.h) {
        for xx in x0..x1.max(x0 + 1).min(img.w) {
            let i = ((yy * img.w + xx) * 4) as usize;
            for (acc_c, &v) in acc.iter_mut().zip(&img.px[i..i + 4]) {
                *acc_c += v as u64;
            }
            n += 1;
        }
    }
    if n == 0 {
        return [0.0; 4];
    }
    acc.map(|v| v as f64 / n as f64)
}

/// Max per-channel centre-mean difference across the given patch rects
/// (rects must already be in the compared image's coordinate space).
/// +inf on dimension mismatch.
pub fn patch_level_dist(a: &Img, b: &Img, rects: &[Rect]) -> f64 {
    if a.w != b.w || a.h != b.h {
        return f64::INFINITY;
    }
    let sx = a.w as f64;
    let sy = a.h as f64;
    let mut worst = 0.0f64;
    for r in rects {
        let ra = patch_center_mean(a, *r);
        let rb = patch_center_mean(b, *r);
        if ra[0].is_nan() || rb[0].is_nan() {
            return f64::INFINITY;
        }
        for c in 0..4 {
            worst = worst.max((ra[c] - rb[c]).abs());
        }
    }
    let _ = (sx, sy);
    worst
}

/// A scored hypothesis input: image + its patch rects (empty = use whole-
/// image distance for non-pattern content).
pub struct HypIn {
    pub name: String,
    pub img: Img,
    pub correct: bool,
    /// Patch rects in this hypothesis' own image space (already
    /// orientation-mapped). Empty for corpus/other non-pattern fixtures.
    pub rects: Vec<Rect>,
}

/// Classify `out` against hypotheses.
///
/// For hypotheses that carry patch rects the distance is the max per-channel
/// centre-mean difference (levels). For rect-less (corpus) hypotheses the
/// distance is the per-pixel p99 (`dmax` carries the archived max).
///
/// `collapsed` is the fixture's indistinguishable-hyp-pair list from
/// `self_test_patched` — pairs the content itself cannot separate.
///
/// Verdict rules:
/// - zero matches within `t`: `other`;
/// - nearest hyp is in a collapse pair: if the pair (transitively: every
///   collapsed partner of the nearest) includes a `correct` hyp, the fixture
///   cannot tell the readings apart — `not-measurable`; otherwise the output
///   still landed on a real reading, so report the nearest name with the
///   collapsed partner(s) in the note (`also=…`), correct=false;
/// - corpus margin rule: a named verdict requires the runner-up at least 2x
///   further than the best match — below that the call is `not-measurable`
///   (cross-decoder render noise is a sizeable fraction of the threshold);
/// - pattern fixtures with several non-collapsed matches: `indistinguishable`
///   (reader ambiguity — the output really is near each).
pub fn classify_patched(
    out: &Img,
    hyps: &[HypIn],
    t: f64,
    max_side: u32,
    collapsed: &[(String, String, f64, f64)],
) -> (String, Vec<Scored>, String) {
    let out_ds = downscale(out, max_side);
    let corpus = hyps.iter().all(|h| h.rects.is_empty());
    // Corpus compares run in corpus_space (M-6 thumb chain); the patch
    // metric stays on the plain one-stage downscale it was calibrated on.
    let out_cds = hyps
        .iter()
        .any(|h| h.rects.is_empty())
        .then(|| corpus_space(out, max_side));
    let mut scored: Vec<Scored> = Vec::with_capacity(hyps.len());
    for h in hyps {
        let (d, dmax) = if h.rects.is_empty() {
            let hds = corpus_space(&h.img, max_side);
            corpus_dist(out_cds.as_ref().unwrap(), &hds)
        } else {
            let hds = downscale(&h.img, max_side);
            // scale rects from full-res hyp space to downscaled space
            let s = if h.img.w.max(h.img.h) > max_side {
                max_side as f64 / h.img.w.max(h.img.h) as f64
            } else {
                1.0
            };
            let scaled: Vec<Rect> = h
                .rects
                .iter()
                .map(|r| Rect {
                    x: (r.x as f64 * s) as u32,
                    y: (r.y as f64 * s) as u32,
                    w: ((r.w as f64 * s).ceil() as u32).max(1),
                    h: ((r.h as f64 * s).ceil() as u32).max(1),
                })
                .collect();
            let d = patch_level_dist(&out_ds, &hds, &scaled);
            (d, d)
        };
        scored.push(Scored {
            name: h.name.clone(),
            dist: d,
            dmax,
            correct: h.correct,
        });
    }
    scored.sort_by(|a, b| {
        a.dist
            .partial_cmp(&b.dist)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let matches: Vec<usize> = scored
        .iter()
        .enumerate()
        .filter(|(_, s)| s.dist <= t)
        .map(|(i, _)| i)
        .collect();
    // Collapsed partners of `name` (the renders the fixture cannot separate).
    let partners = |name: &str| -> Vec<String> {
        collapsed
            .iter()
            .filter_map(|(a, b, _, _)| {
                if a == name {
                    Some(b.clone())
                } else if b == name {
                    Some(a.clone())
                } else {
                    None
                }
            })
            .collect()
    };
    let hyp_correct = |name: &str| -> bool {
        hyps.iter()
            .find(|h| h.name == name)
            .map(|h| h.correct)
            .unwrap_or(false)
    };
    // r13/r14: the two nearest hypotheses within FINE_T of each other are
    // an attribution tie. Inside T the cell reads `not-measurable` and
    // certifies only when a correct-labelled hyp is in the tied pair
    // (r14 H-1, via verdict_correct's tie branch). Beyond T two equally
    // bad misses certify nothing — the cell is `other` (the tie note is
    // still recorded so the cell shows why it wasn't named).
    let top_tie = scored.len() >= 2
        && scored[0].dist.is_finite()
        && scored[1].dist.is_finite()
        && scored[1].dist - scored[0].dist < FINE_T;
    let tie_note = || {
        format!(
            "tie: runner-up {:.2} within {:.1} of best {:.2}",
            scored[1].dist, FINE_T, scored[0].dist
        )
    };
    let (verdict, note): (String, String) = match matches.as_slice() {
        [] => (
            "other".to_string(),
            if top_tie { tie_note() } else { String::new() },
        ),
        [one] => {
            let one = &scored[*one];
            let parts = partners(&one.name);
            if !parts.is_empty() {
                if one.correct || parts.iter().any(|p| hyp_correct(p)) {
                    (
                        "not-measurable".to_string(),
                        format!("collapse {}~{} includes correct", one.name, parts.join("+")),
                    )
                } else {
                    // the output lands on a real reading; name it, and record
                    // the render-identical partner(s) it cannot rule out.
                    (one.name.clone(), format!("also={}", parts.join(",")))
                }
            } else if top_tie {
                ("not-measurable".to_string(), tie_note())
            } else if corpus
                && scored.len() > 1
                && scored[1].dist.is_finite()
                && scored[1].dist < 2.0 * scored[0].dist
            {
                (
                    "not-measurable".to_string(),
                    format!(
                        "margin: runner-up {:.2} < 2x best {:.2}",
                        scored[1].dist, scored[0].dist
                    ),
                )
            } else {
                (one.name.clone(), String::new())
            }
        }
        many => {
            // All matches mutually collapsed = one degenerate clique: the
            // fixture cannot separate them, so the corpus margin rule is moot.
            let clique_ok = |ms: &[usize]| -> bool {
                ms.iter().enumerate().all(|(i, a)| {
                    ms.iter().skip(i + 1).all(|b| {
                        collapsed.iter().any(|(x, y, _, _)| {
                            (x == &scored[*a].name && y == &scored[*b].name)
                                || (x == &scored[*b].name && y == &scored[*a].name)
                        })
                    })
                })
            };
            if clique_ok(many) {
                if many.iter().any(|&m| scored[m].correct) {
                    (
                        "not-measurable".to_string(),
                        format!(
                            "collapse {} includes correct",
                            many.iter()
                                .map(|&m| scored[m].name.as_str())
                                .collect::<Vec<_>>()
                                .join("~")
                        ),
                    )
                } else {
                    let rest: Vec<&str> = many
                        .iter()
                        .skip(1)
                        .map(|&m| scored[m].name.as_str())
                        .collect();
                    (
                        scored[many[0]].name.clone(),
                        format!("also={}", rest.join(",")),
                    )
                }
            } else if top_tie {
                // not a collapse clique, but the two nearest matches are
                // within the fine bound of each other — attribution is a
                // coin flip (r13: ties are not-measurable, never `other`
                // or an arbitrary name).
                ("not-measurable".to_string(), tie_note())
            } else if corpus && scored[many[1]].dist < 2.0 * scored[many[0]].dist {
                // not a collapse clique and the corpus margin rule fails —
                // the two nearest non-collapsed matches are too close to
                // call (cross-decoder noise is a sizeable fraction of T).
                (
                    "not-measurable".to_string(),
                    format!(
                        "margin: {} matches within T, runner-up {:.2} < 2x best {:.2}",
                        many.len(),
                        scored[many[1]].dist,
                        scored[many[0]].dist
                    ),
                )
            } else if corpus {
                // Margin clears — the nearest match stands. Run the same
                // collapse-partner naming as the single-match case so a
                // best match that is itself fine-bound-collapsed still
                // reports `also=`/`not-measurable` honestly.
                let best = &scored[many[0]];
                let parts = partners(&best.name);
                if !parts.is_empty() {
                    if best.correct || parts.iter().any(|p| hyp_correct(p)) {
                        (
                            "not-measurable".to_string(),
                            format!(
                                "collapse {}~{} includes correct",
                                best.name,
                                parts.join("+")
                            ),
                        )
                    } else {
                        (best.name.clone(), format!("also={}", parts.join(",")))
                    }
                } else {
                    (best.name.clone(), String::new())
                }
            } else {
                ("indistinguishable".to_string(), String::new())
            }
        }
    };
    (verdict, scored, note)
}

/// Self-test: two hyps are distinguishable iff some patch centre-mean
/// differs by >= `min_delta` levels (pattern fixtures) or their corpus
/// distance reaches `factor * corpus_threshold` (rect-less fixtures).
/// Returns (hyp_a, hyp_b, p99, max) quadruples for indistinguishable pairs.
pub fn self_test_patched(
    hyps: &[HypIn],
    min_delta: f64,
    factor: f64,
    corpus_threshold: f64,
    max_side: u32,
) -> Vec<(String, String, f64, f64)> {
    let ds: Vec<(&HypIn, Img)> = hyps
        .iter()
        .map(|h| (h, downscale(&h.img, max_side)))
        .collect();
    let mut indist = Vec::new();
    for i in 0..ds.len() {
        for j in i + 1..ds.len() {
            let (hi, a) = &ds[i];
            let (hj, b) = &ds[j];
            if !hi.rects.is_empty() && !hj.rects.is_empty() {
                let d = patch_level_dist(a, b, &hi.rects);
                if d < min_delta {
                    indist.push((hi.name.clone(), hj.name.clone(), d, d));
                }
            } else {
                // full-res originals through the same thumb chain cells
                // take (M-6) — `a`/`b` are already <=max_side.
                let (d, mx) = corpus_dist(
                    &corpus_space(&hi.img, max_side),
                    &corpus_space(&hj.img, max_side),
                );
                if d < factor * corpus_threshold {
                    indist.push((hi.name.clone(), hj.name.clone(), d, mx));
                }
            }
        }
    }
    indist
}

#[cfg(test)]
mod tests {
    use super::*;
    const MAX_SIDE: u32 = 512;

    fn uni(v: u8) -> Img {
        let mut px = Vec::with_capacity(16 * 16 * 4);
        for _ in 0..16 * 16 {
            px.extend_from_slice(&[v, v, v, 255]);
        }
        Img { w: 16, h: 16, px }
    }

    fn hyp(name: &str, v: u8, correct: bool) -> HypIn {
        HypIn {
            name: name.to_string(),
            img: uni(v),
            correct,
            rects: Vec::new(),
        }
    }

    // r14 H-1: every hypothesis equidistant at 100 — beyond T the tie
    // certifies nothing; the cell is `other`/false (the tie note is
    // still recorded for diagnosis).
    #[test]
    fn tie_beyond_t_is_other() {
        let out = uni(128);
        let hyps = vec![hyp("a", 228, false), hyp("b", 28, false)];
        let collapsed = self_test_patched(&hyps, FINE_T, 1.0, FINE_T, MAX_SIDE);
        let (v, scored, note) = classify_patched(&out, &hyps, 4.0, MAX_SIDE, &collapsed);
        assert_eq!(v, "other");
        assert!(note.starts_with("tie:"), "note {note}");
        assert!(!verdict_correct(&v, &note, &scored));
    }

    // A tie within T certifies when a correct-labelled hypothesis is in
    // the tied pair (the r13 collapse-agnostic within-T case review 8
    // re-classified as sound).
    #[test]
    fn tie_within_t_certifies_with_correct() {
        let out = uni(128);
        let hyps = vec![hyp("correct", 129, true), hyp("colour-only", 127, false)];
        let collapsed = self_test_patched(&hyps, FINE_T, 1.0, FINE_T, MAX_SIDE);
        let (v, scored, note) = classify_patched(&out, &hyps, 4.0, MAX_SIDE, &collapsed);
        assert_eq!(v, "not-measurable");
        assert!(note.starts_with("tie:"), "note {note}");
        assert!(verdict_correct(&v, &note, &scored));
    }

    // A tie within T between two non-correct readings certifies nothing:
    // `not-measurable` but correct=false.
    #[test]
    fn tie_within_t_no_correct_member() {
        let out = uni(128);
        let hyps = vec![hyp("stored", 129, false), hyp("orient-only", 127, false)];
        let collapsed = self_test_patched(&hyps, FINE_T, 1.0, FINE_T, MAX_SIDE);
        let (v, scored, note) = classify_patched(&out, &hyps, 4.0, MAX_SIDE, &collapsed);
        assert_eq!(v, "not-measurable");
        assert!(note.starts_with("tie:"), "note {note}");
        assert!(!verdict_correct(&v, &note, &scored));
    }
}
