//! The zen-reader adapter: decode any supported input through zencodecs,
//! honour orientation and colour management, emit an sRGB8 PNG plus a JSON
//! stats line. This is one of the uniform-CLI readers; the harness wraps it
//! like every other adapter.

use zencodecs::{DecodeRequest, Limits, OrientationHint};
use zenpixels::ColorProfileSource;
use zenpixels_convert::PixelBufferConvertExt;
use zenpixels_convert::cms::{PluggableCms, RowTransformMut};

/// Result of a probe run (also serialized to JSON).
pub struct ProbeOut {
    pub status: String,
    pub w: u32,
    pub h: u32,
    pub ms: f64,
    pub version: String,
    pub error_head: String,
    pub format: String,
    pub source_color: String,
    pub orientation_reported: u8,
    /// true when the probe baked the reported tag itself (decoder didn't)
    pub orient_applied: bool,
    /// how the colour conversion happened (icc-moxcms, cicp, none, skipped)
    pub colour_path: String,
    /// "none" | source format name | "error:<msg>" when extraction failed
    pub gainmap: String,
    pub gainmap_w: u32,
    pub gainmap_h: u32,
    /// per-channel mean/std of the emitted RGB (census collapse detection)
    pub mean: [f64; 3],
    pub std: [f64; 3],
    pub png: Vec<u8>,
}

fn fmt_debug(v: &impl std::fmt::Debug) -> String {
    let s = format!("{v:?}");
    s.chars().take(160).collect()
}

/// ICC->sRGB row transform via the moxcms-backed CMS (handles arbitrary
/// profiles, not just the builtin table).
fn icc_transform(src_icc: &[u8]) -> Result<Box<dyn RowTransformMut>, String> {
    let srgb = crate::icc::srgb_icc_v4();
    let cms = zenpixels_convert::cms_moxcms::MoxCms;
    cms.build_source_transform(
        ColorProfileSource::Icc(src_icc),
        ColorProfileSource::Icc(&srgb),
        zenpixels::PixelFormat::Rgba8,
        zenpixels::PixelFormat::Rgba8,
        &zenpixels_convert::ConvertOptions::permissive(),
    )
    .ok_or_else(|| "cms declined".to_string())
    .and_then(|r| r.map_err(|e| format!("cms: {e}")))
}

fn cicp_transform(c: zenpixels::Cicp) -> Result<Box<dyn RowTransformMut>, String> {
    let cms = zenpixels_convert::cms_moxcms::MoxCms;
    cms.build_source_transform(
        ColorProfileSource::Cicp(c),
        ColorProfileSource::Cicp(zenpixels::Cicp::SRGB),
        zenpixels::PixelFormat::Rgba8,
        zenpixels::PixelFormat::Rgba8,
        &zenpixels_convert::ConvertOptions::permissive(),
    )
    .ok_or_else(|| "cms declined".to_string())
    .and_then(|r| r.map_err(|e| format!("cms: {e}")))
}

/// Apply an EXIF orientation to RGBA8 pixels; returns (new_px, w, h).
/// Some decode paths (AVIF) report the stored tag without baking it — the
/// viewer still has to apply it to get display pixels.
pub fn apply_orientation_rgba8(px: &[u8], w: u32, h: u32, o: u8) -> (Vec<u8>, u32, u32) {
    let (dw, dh) = if (5..=8).contains(&o) { (h, w) } else { (w, h) };
    let mut out = vec![0u8; (dw * dh * 4) as usize];
    for y in 0..dh {
        for x in 0..dw {
            let (sx, sy) = crate::orient_map(x, y, w, h, o);
            let s = ((sy * w + sx) * 4) as usize;
            let d = ((y * dw + x) * 4) as usize;
            out[d..d + 4].copy_from_slice(&px[s..s + 4]);
        }
    }
    (out, dw, dh)
}

fn apply_rows(t: &mut dyn RowTransformMut, px: &mut [u8], w: u32, h: u32) {
    let row = (w * 4) as usize;
    let mut tmp = vec![0u8; row];
    for y in 0..h as usize {
        let r = &mut px[y * row..(y + 1) * row];
        t.transform_row(r, &mut tmp, w);
        r.copy_from_slice(&tmp);
    }
}

fn png_pack(px: &[u8], w: u32, h: u32) -> Result<Vec<u8>, String> {
    let rgba: Vec<rgb::Rgba<u8>> = px
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| rgb::Rgba {
            r: c[0],
            g: c[1],
            b: c[2],
            a: c[3],
        })
        .collect();
    zenpng::encode_rgba8(
        imgref::ImgRef::new(&rgba, w as usize, h as usize),
        None,
        &zenpng::EncodeConfig::default(),
        &enough::Unstoppable,
        &enough::Unstoppable,
    )
    .map_err(|e| format!("png: {e}"))
}

fn blank_out() -> ProbeOut {
    ProbeOut {
        status: "error".into(),
        w: 0,
        h: 0,
        ms: 0.0,
        version: env!("CARGO_PKG_VERSION").to_string(),
        error_head: String::new(),
        format: String::new(),
        source_color: String::new(),
        orientation_reported: 1,
        orient_applied: false,
        colour_path: String::new(),
        gainmap: "none".into(),
        gainmap_w: 0,
        gainmap_h: 0,
        mean: [0.0; 3],
        std: [0.0; 3],
        png: Vec::new(),
    }
}

/// Per-channel mean/std of interleaved RGBA8 (alpha ignored).
fn chan_stats(px: &[u8]) -> ([f64; 3], [f64; 3]) {
    let n = (px.len() / 4) as f64;
    let mut mean = [0f64; 3];
    for c in px.as_chunks::<4>().0.iter() {
        mean[0] += c[0] as f64;
        mean[1] += c[1] as f64;
        mean[2] += c[2] as f64;
    }
    for m in &mut mean {
        *m /= n;
    }
    let mut var = [0f64; 3];
    for c in px.as_chunks::<4>().0.iter() {
        var[0] += (c[0] as f64 - mean[0]).powi(2);
        var[1] += (c[1] as f64 - mean[1]).powi(2);
        var[2] += (c[2] as f64 - mean[2]).powi(2);
    }
    (mean, [var[0] / n, var[1] / n, var[2] / n].map(f64::sqrt))
}

/// Decode `data` to display-oriented, colour-managed sRGB8, and pack PNG.
pub fn probe(data: &[u8]) -> ProbeOut {
    let t0 = std::time::Instant::now();
    let mut out = blank_out();
    let r = (|| -> Result<(), String> {
        let limits = Limits::none()
            .with_max_pixels(600_000_000)
            .with_max_memory(16 << 30);
        let (img, gm) = match DecodeRequest::new(data)
            .with_limits(&limits)
            .with_orientation(OrientationHint::Correct)
            .decode_gain_map()
        {
            Ok(t) => t,
            // Gain-map extraction failures (e.g. corrupt MPF) should not
            // mask a still-decodable base image.
            Err(_) => {
                let img = DecodeRequest::new(data)
                    .with_limits(&limits)
                    .with_orientation(OrientationHint::Correct)
                    .decode_full_frame()
                    .map_err(|e| format!("decode: {e}"))?;
                out.gainmap = "extract-error".into();
                (img, None)
            }
        };
        if let Some(g) = &gm {
            out.gainmap = format!("{:?}", g.source_format).to_lowercase();
            out.gainmap_w = g.gain_map.width;
            out.gainmap_h = g.gain_map.height;
        }
        // The decode info reports post-bake orientation (1 after Correct);
        // the *signalled* tag is the header-level value. Report that, and
        // mark orient_applied whenever any layer transformed the pixels.
        let signalled = zencodecs::probe(data, &zencodecs::AllowedFormats::all())
            .map(|i| i.orientation.to_exif())
            .unwrap_or(1);
        let post_bake;
        let icc;
        let cicp;
        let prefer_cicp;
        {
            let info = img.info();
            out.orientation_reported = signalled;
            post_bake = info.orientation.to_exif();
            icc = info.source_color.icc_profile.clone();
            cicp = info.source_color.cicp;
            prefer_cicp = info.source_color.color_authority == zenpixels::ColorAuthority::Cicp;
        }
        out.source_color = fmt_debug(&img.info().source_color);
        out.format = fmt_debug(&img.descriptor().format);

        let buf = img.into_buffer();
        let d = buf.descriptor();
        let target = zenpixels::PixelDescriptor::RGBA8_SRGB
            .with_primaries(d.primaries)
            .with_transfer(d.transfer)
            .with_signal_range(d.signal_range);
        let buf = buf
            .convert_to(target)
            .map_err(|e| format!("layout convert: {e}"))?;
        let (mut w, mut h) = (buf.width(), buf.height());
        let mut px = buf.copy_to_contiguous_bytes();

        // Decoder paths that report a stored tag without baking (AVIF, PNG
        // eXIf) still need the viewer to apply it; paths that baked report 1
        // in info but had a signalled tag — mark either case as applied.
        if post_bake != 1 {
            let (npx, nw, nh) = apply_orientation_rgba8(&px, w, h, post_bake);
            px = npx;
            w = nw;
            h = nh;
        }
        out.orient_applied = signalled != 1;

        // Colour authority is format-defined (zencodecs reports it from the
        // container semantics): PNG-3e makes cICP authoritative over iCCP;
        // HEIF/JPEG put ICC first. Apply the authoritative carrier, with the
        // other as fallback when the authority field is absent.
        let mut path = "none";
        let try_cicp = |path: &mut &'static str, px: &mut [u8], w: u32, h: u32| {
            if let Some(c) = cicp {
                let srgbish =
                    c.color_primaries == 1 && matches!(c.transfer_characteristics, 1 | 13);
                if !srgbish {
                    match cicp_transform(c) {
                        Ok(mut t) => {
                            apply_rows(&mut *t, px, w, h);
                            *path = "cicp-moxcms";
                        }
                        Err(_) => *path = "cicp-unhandled",
                    }
                } else {
                    *path = "cicp-srgb";
                }
                true
            } else {
                false
            }
        };
        let try_icc = |path: &mut &'static str, px: &mut [u8], w: u32, h: u32| {
            if let Some(icc_bytes) = icc.as_deref().filter(|v| !v.is_empty()) {
                match icc_transform(icc_bytes) {
                    Ok(mut t) => {
                        apply_rows(&mut *t, px, w, h);
                        *path = "icc-moxcms";
                    }
                    Err(_) => *path = "icc-unhandled",
                }
                true
            } else {
                false
            }
        };
        // Order matters: the first successful transform wins; a failed
        // try_* leaves px untouched.
        if prefer_cicp {
            if !try_cicp(&mut path, &mut px, w, h) {
                try_icc(&mut path, &mut px, w, h);
            }
        } else if !try_icc(&mut path, &mut px, w, h) {
            try_cicp(&mut path, &mut px, w, h);
        }
        out.colour_path = path.into();
        (out.mean, out.std) = chan_stats(&px);
        out.png = png_pack(&px, w, h)?;
        out.w = w;
        out.h = h;
        out.status = "ok".into();
        Ok(())
    })();
    if let Err(e) = r {
        out.error_head = e;
    }
    out.ms = t0.elapsed().as_secs_f64() * 1000.0;
    out
}

/// Header-level probe: `zencodecs::probe` parses container metadata only —
/// no pixel decode. `ImageInfo.orientation` is the file's *signalled*
/// orientation (EXIF tag / irot), pre-bake — the number the census needs
/// (a full `probe --raw` decode reports the same field but costs pixels).
pub fn probe_meta(data: &[u8]) -> ProbeOut {
    let t0 = std::time::Instant::now();
    let mut out = blank_out();
    let r = (|| -> Result<(), String> {
        let info = zencodecs::probe(data, &zencodecs::AllowedFormats::all())
            .map_err(|e| format!("probe: {e}"))?;
        out.orientation_reported = info.orientation.to_exif();
        out.source_color = fmt_debug(&info.source_color);
        out.format = fmt_debug(&info.format);
        out.colour_path = "meta-only".into();
        out.w = info.width;
        out.h = info.height;
        out.status = "ok".into();
        Ok(())
    })();
    if let Err(e) = r {
        out.error_head = e;
    }
    out.ms = t0.elapsed().as_secs_f64() * 1000.0;
    out
}

/// Decode to stored pixels (no orientation apply, no colour conversion).
pub fn probe_raw(data: &[u8]) -> ProbeOut {
    let t0 = std::time::Instant::now();
    let mut out = blank_out();
    let r = (|| -> Result<(), String> {
        let limits = Limits::none()
            .with_max_pixels(600_000_000)
            .with_max_memory(16 << 30);
        let img = DecodeRequest::new(data)
            .with_limits(&limits)
            .with_orientation(OrientationHint::Preserve)
            .decode_full_frame()
            .map_err(|e| format!("decode: {e}"))?;
        out.orientation_reported = img.info().orientation.to_exif();
        out.source_color = fmt_debug(&img.info().source_color);
        // Truly raw: convert layout to RGBA8 while preserving the source
        // primaries/transfer so no colour management is applied.
        let buf = img.into_buffer();
        let d = buf.descriptor();
        let target = zenpixels::PixelDescriptor::RGBA8_SRGB
            .with_primaries(d.primaries)
            .with_transfer(d.transfer)
            .with_signal_range(d.signal_range);
        let buf = buf
            .convert_to(target)
            .map_err(|e| format!("raw layout convert: {e}"))?;
        let (w, h) = (buf.width(), buf.height());
        let px = buf.copy_to_contiguous_bytes();
        out.colour_path = "raw".into();
        out.png = png_pack(&px, w, h)?;
        out.w = w;
        out.h = h;
        out.status = "ok".into();
        Ok(())
    })();
    if let Err(e) = r {
        out.error_head = e;
    }
    out.ms = t0.elapsed().as_secs_f64() * 1000.0;
    out
}

/// Reconstruct the full-boost HDR rendition (gain map applied) and write it
/// as a little-endian PFM of linear RGB f32. This is the zen reference the
/// HDR table's `|Δlog2|` comparisons run against.
///
/// Stored orientation and the base image's own primaries/transfer are
/// preserved — matching `ultrahdr_app -o 0 -O 4`, which emits stored
/// orientation in the base rendition's gamut. (An earlier version baked
/// orientation and clamped the base to sRGB primaries, which broke the
/// comparison on rotated and wide-gamut inputs.)
pub fn probe_hdr(data: &[u8], pfm_path: &std::path::Path) -> Result<String, String> {
    let limits = Limits::none()
        .with_max_pixels(600_000_000)
        .with_max_memory(16 << 30);
    let (img, gm) = DecodeRequest::new(data)
        .with_limits(&limits)
        .with_orientation(OrientationHint::Preserve)
        .decode_gain_map()
        .map_err(|e| format!("decode: {e}"))?;
    let gm = gm.ok_or_else(|| "no gain map".to_string())?;
    let buf = img.into_buffer();
    let d = buf.descriptor();
    let sdr = buf
        .convert_to(
            zenpixels::PixelDescriptor::RGBA8_SRGB
                .with_primaries(d.primaries)
                .with_transfer(d.transfer)
                .with_signal_range(d.signal_range),
        )
        .map_err(|e| format!("sdr convert: {e}"))?;
    let boost = ultrahdr_core::full_reconstruction_boost(&gm.metadata);
    let hdr = ultrahdr_core::gainmap::apply_gainmap(
        &sdr,
        &gm.gain_map,
        &gm.metadata,
        boost,
        ultrahdr_core::HdrOutputFormat::LinearFloat,
        enough::Unstoppable,
    )
    .map_err(|e| format!("apply: {e}"))?;
    let (w, h) = (hdr.width() as usize, hdr.height() as usize);
    let bytes = hdr.copy_to_contiguous_bytes(); // RgbaF32, little-endian
    let f32s: Vec<f32> = bytes
        .as_chunks::<16>()
        .0
        .iter()
        .flat_map(|px| {
            [
                f32::from_le_bytes(px[0..4].try_into().unwrap()),
                f32::from_le_bytes(px[4..8].try_into().unwrap()),
                f32::from_le_bytes(px[8..12].try_into().unwrap()),
            ]
        })
        .collect();
    write_pfm(pfm_path, w, h, &f32s).map_err(|e| format!("pfm: {e}"))?;
    Ok(format!("{w}x{h} boost={boost:.3}"))
}

/// Little-endian PFM ("PF", scale -1.0), rows stored bottom-up per spec.
fn write_pfm(path: &std::path::Path, w: usize, h: usize, rgb: &[f32]) -> std::io::Result<()> {
    use std::io::Write;
    let mut f = std::fs::File::create(path)?;
    write!(f, "PF\n{w} {h}\n-1.0\n")?;
    for row in (0..h).rev() {
        let start = row * w * 3;
        for &v in &rgb[start..start + w * 3] {
            f.write_all(&v.to_le_bytes())?;
        }
    }
    Ok(())
}
