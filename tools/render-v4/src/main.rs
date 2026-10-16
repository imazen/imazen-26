//! Render the imazen-26 v4 layers from the originals (EXPORT-PLAN.md, "Render v4").
//!
//! Four passes, each a subcommand writing beside the others in one output directory:
//! - `png-sdr` (this file): the two SDR PNG layers.
//!   - `png-p3`: each source's own colour space and code values.
//!   - `png-srgb`: sRGB. Display P3 and Adobe RGB sources are converted relative-colorimetric
//!     (a matrix in linear light), out-of-gamut colours clipped, and the clipped pixels
//!     counted. An sRGB source's `png-srgb` file is byte-identical to its `png-p3` file.
//! - `png-hdr` (see `hdr`): the 16-bit PQ render of each gain-map source, `<stem>.hdr.png` in
//!   `png-p3`.
//! - `jxl` and `jxl-hdr` (see `jxl`): the JPEG XL twins of the PNG layers, with JPEG-in-JXL for
//!   JPEG sources and the gain-map form (`jhgm`) for gain-map sources.
//!
//! For the PNG layers: orientation baked into the pixels; channels and bit depth follow the
//! source (8-bit, and the 1-bit patent pages stay 1-bit), a fully opaque alpha channel dropped
//! and reported; colour signalling as the plan says (an `sRGB` chunk for sRGB, the source's
//! `iCCP` plus an agreeing `cICP` where H.273 has a code, `iCCP` alone for Adobe RGB); one
//! provenance `tEXt` chunk (keyword `imazen-26`, the row's JSON, ASCII so it reads the same as
//! Latin-1 or UTF-8) before the image data; zenpng at effort 22. Every output is decoded again
//! and must hold exactly the pixels it was written from and that one text chunk. DNGs are not
//! rendered. A gain-map source's SDR files hold the camera's SDR base, and the report names
//! its gain map.
//!
//! Usage: render-v4 png-sdr [--jobs N] <list.tsv> <out-dir>
//!        render-v4 png-hdr [--jobs N] <list.tsv> <out-dir>    (the gain-map sources; see `hdr`)
//!        render-v4 hdr-info [--jobs N] <list.tsv> <out-dir>   (what png-hdr would use; writes nothing)
//!        render-v4 jxl --effort E [--jobs N] <list.tsv> <out-dir>   (the JPEG XL layers; see `jxl`)
//!        render-v4 jxl-hdr --effort E [--jobs N] <list.tsv> <out-dir>   (each .hdr.png's JXL twin)
//!   list: id<TAB>source path<TAB>out stem (class/newid_name, no _WxH)<TAB>provenance JSON
//!   → <out-dir>/png-p3/<stem>_<W>x<H>.png and <out-dir>/png-srgb/<stem>_<W>x<H>.png, and a
//!     report on stdout: id, layer, path, width, height, layout, source_alpha (none, kept or
//!     dropped-opaque), colour, gain_map, clipped, bytes, sha256, rgba_sha256, error, in the
//!     order files finish (`--jobs` renders that many at once; progress goes to stderr)

#![forbid(unsafe_code)]

mod hdr;
mod jxl;

use std::fs;
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

use enough::Unstoppable;
use sha2::{Digest, Sha256};
use zencodec::{Cicp, Metadata, OrientationHint};
use zencodecs::{DecodeRequest, Limits};
use zenpixels::icc::{IdentificationUse, identify_common};
use zenpixels::{ColorPrimaries, PixelBuffer, PixelDescriptor, TransferFunction};
use zenpixels_convert::{
    ConvertOptions, ConvertPlan, PixelBufferConvertTypedExt as _, convert_row,
};
use zenpng::{Compression, EncodeConfig};

const EFFORT: u32 = 22;
/// The report columns of `png-sdr`.
const SDR_HEADER: &str = "id\tlayer\tpath\twidth\theight\tlayout\tsource_alpha\tcolour\tgain_map\tclipped\tbytes\tsha256\trgba_sha256\terror";
const TEXT_KEYWORD: &str = "imazen-26";

#[derive(Clone, Copy, Debug, PartialEq)]
enum Colour {
    Srgb,
    /// Untagged: written as sRGB and marked `assumed`.
    AssumedSrgb,
    DisplayP3,
    AdobeRgb,
}

impl Colour {
    fn name(self) -> &'static str {
        match self {
            Colour::Srgb => "srgb",
            Colour::AssumedSrgb => "assumed-srgb",
            Colour::DisplayP3 => "display-p3",
            Colour::AdobeRgb => "adobe-rgb",
        }
    }
    fn is_srgb(self) -> bool {
        matches!(self, Colour::Srgb | Colour::AssumedSrgb)
    }
    fn primaries(self) -> ColorPrimaries {
        match self {
            Colour::Srgb | Colour::AssumedSrgb => ColorPrimaries::Bt709,
            Colour::DisplayP3 => ColorPrimaries::DisplayP3,
            Colour::AdobeRgb => ColorPrimaries::AdobeRgb,
        }
    }
    fn transfer(self) -> TransferFunction {
        match self {
            Colour::AdobeRgb => TransferFunction::Gamma22,
            _ => TransferFunction::Srgb,
        }
    }
}

/// The gain map a source carries, as its own codec's probe names it: zenjpeg's container
/// probe (ISO 21496-1, `hdrgm` XMP, GContainer) or heic's (Apple's auxiliary image, `tmap`).
fn gain_map(data: &[u8], source: &str) -> Result<Option<String>, String> {
    let ext = source.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "jpg" | "jpeg" => {
            use zenjpeg::container::{GainMapPresence, Wants, probe};
            let p = probe(data, Wants::ALL);
            if p.truncated() {
                return Err("JPEG container probe stopped early".into());
            }
            Ok(match p.gainmap_presence() {
                GainMapPresence::None => None,
                other => Some(format!("jpeg-{other:?}")),
            })
        }
        "heic" | "heif" => {
            let info =
                heic::ImageInfo::from_bytes(data).map_err(|e| format!("heic probe: {e:?}"))?;
            Ok(info.has_gain_map.then(|| "heic".to_string()))
        }
        "png" => Ok(None),
        _ => Err(format!("no gain-map probe for .{ext}")),
    }
}

/// The ICC profile shared by every tile of a HEIC grid primary that has none of its own.
fn heic_tile_icc(data: &[u8]) -> Option<Vec<u8>> {
    use heic::heif::{ColorInfo, FourCC};
    let container = heic::heif::parse(data, &heic::Unstoppable).ok()?;
    let primary = container.primary_item()?;
    let mut found: Option<Vec<u8>> = None;
    for id in container.get_item_references(primary.id, FourCC(*b"dimg")) {
        let icc = match container.get_item(id).and_then(|t| t.color_info) {
            Some(ColorInfo::IccProfile(icc)) => icc,
            _ => return None,
        };
        match &found {
            None => found = Some(icc),
            Some(f) if *f == icc => {}
            Some(_) => return None,
        }
    }
    found
}

fn classify(icc: Option<&[u8]>) -> Result<Colour, String> {
    let Some(icc) = icc else {
        return Ok(Colour::AssumedSrgb);
    };
    let id = identify_common(icc).ok_or("ICC profile not recognized")?;
    if id.valid_use != IdentificationUse::MatrixTrcSubstitution {
        return Err(format!(
            "ICC profile needs a CMS ({:?} {:?})",
            id.primaries, id.transfer
        ));
    }
    match (id.primaries, id.transfer) {
        (ColorPrimaries::Bt709, TransferFunction::Srgb) => Ok(Colour::Srgb),
        (ColorPrimaries::DisplayP3, TransferFunction::Srgb) => Ok(Colour::DisplayP3),
        (ColorPrimaries::AdobeRgb, TransferFunction::Gamma22) => Ok(Colour::AdobeRgb),
        (p, t) => Err(format!("unsupported colour space {p:?} {t:?}")),
    }
}

/// 8-bit pixels in one of the layouts the PNG layers keep.
#[derive(Clone)]
enum Pixels {
    Gray(Vec<u8>),
    Rgb(Vec<u8>),
    Rgba(Vec<u8>),
}

impl Pixels {
    fn layout(&self) -> &'static str {
        match self {
            Pixels::Gray(_) => "gray8",
            Pixels::Rgb(_) => "rgb8",
            Pixels::Rgba(_) => "rgba8",
        }
    }
    fn rgba(&self) -> Vec<u8> {
        match self {
            Pixels::Gray(g) => g.iter().flat_map(|&v| [v, v, v, 255]).collect(),
            Pixels::Rgb(p) => p
                .as_chunks::<3>()
                .0
                .iter()
                .flat_map(|c| [c[0], c[1], c[2], 255])
                .collect(),
            Pixels::Rgba(p) => p.clone(),
        }
    }
}

/// The decoded buffer's code values in a kept layout, without colour management: the buffer
/// is relabelled sRGB first so the typed conversions only change the layout. Also says what
/// happened to the source's alpha: `none`, `kept`, or `dropped-opaque` (every value 255).
fn code_values(buf: PixelBuffer) -> Result<(Pixels, &'static str), String> {
    let desc = buf.descriptor();
    if desc.channel_type() != zenpixels::ChannelType::U8 {
        return Err(format!("not an 8-bit decode: {desc:?}"));
    }
    let gray = matches!(
        desc.format,
        zenpixels::PixelFormat::Gray8 | zenpixels::PixelFormat::GrayA8
    );
    // Straight, premultiplied or opaque-declared alpha; padding bytes (RGBX) are not alpha.
    let has_alpha = desc.has_alpha();
    if desc.alpha() == Some(zenpixels::AlphaMode::Premultiplied) {
        return Err("premultiplied decode".into());
    }
    let buf = buf
        .with_primaries(ColorPrimaries::Bt709)
        .with_transfer(TransferFunction::Srgb);
    let rgba = buf.to_rgba8().copy_to_contiguous_bytes();
    let opaque = !has_alpha || rgba.as_chunks::<4>().0.iter().all(|c| c[3] == 255);
    let alpha = match (has_alpha, opaque) {
        (false, _) => "none",
        (true, true) => "dropped-opaque",
        (true, false) => "kept",
    };
    let px = match (gray, opaque) {
        (true, true) => Pixels::Gray(rgba.as_chunks::<4>().0.iter().map(|c| c[0]).collect()),
        (_, true) => Pixels::Rgb(
            rgba.as_chunks::<4>()
                .0
                .iter()
                .flat_map(|c| [c[0], c[1], c[2]])
                .collect(),
        ),
        (_, false) => Pixels::Rgba(rgba),
    };
    Ok((px, alpha))
}

/// Apply `orientation` to decoded pixels (for decoders that report it instead of applying
/// it): each source pixel moves to `forward_map` of its position. Returns the new size.
fn orient_pixels(
    px: Pixels,
    w: usize,
    h: usize,
    orientation: zencodec::Orientation,
) -> (Pixels, usize, usize) {
    if orientation.is_identity() {
        return (px, w, h);
    }
    let (ow, oh) = orientation.output_dimensions(w as u32, h as u32);
    let turn = |src: &[u8], c: usize| {
        let mut out = vec![0u8; src.len()];
        for sy in 0..h {
            for sx in 0..w {
                let (dx, dy) = orientation.forward_map(sx as u32, sy as u32, w as u32, h as u32);
                let s = (sy * w + sx) * c;
                let d = (dy as usize * ow as usize + dx as usize) * c;
                out[d..d + c].copy_from_slice(&src[s..s + c]);
            }
        }
        out
    };
    let px = match px {
        Pixels::Gray(p) => Pixels::Gray(turn(&p, 1)),
        Pixels::Rgb(p) => Pixels::Rgb(turn(&p, 3)),
        Pixels::Rgba(p) => Pixels::Rgba(turn(&p, 4)),
    };
    (px, ow as usize, oh as usize)
}

/// Convert code values from `colour` to sRGB: linear light, the gamut matrix, clip, encode.
/// Returns the pixels and how many had a channel outside sRGB by more than half a code value.
fn to_srgb(px: &Pixels, w: usize, colour: Colour) -> Result<(Pixels, u64), String> {
    let (src, alpha): (Vec<u8>, Option<Vec<u8>>) = match px {
        Pixels::Gray(_) => return Ok((px.clone(), 0)),
        Pixels::Rgb(p) => (p.clone(), None),
        Pixels::Rgba(p) => (
            p.as_chunks::<4>()
                .0
                .iter()
                .flat_map(|c| [c[0], c[1], c[2]])
                .collect(),
            Some(p.as_chunks::<4>().0.iter().map(|c| c[3]).collect()),
        ),
    };
    let from = PixelDescriptor::RGB8_SRGB
        .with_primaries(colour.primaries())
        .with_transfer(colour.transfer());
    let linear = PixelDescriptor::RGBF32_LINEAR.with_primaries(ColorPrimaries::Bt709);
    let opts = ConvertOptions::permissive().with_clip_out_of_gamut(false);
    let plan =
        ConvertPlan::new_explicit(from, linear, &opts).map_err(|e| format!("plan: {e:?}"))?;
    let encode = ConvertPlan::new_explicit(
        linear,
        PixelDescriptor::RGB8_SRGB,
        &ConvertOptions::permissive(),
    )
    .map_err(|e| format!("plan: {e:?}"))?;
    let h = src.len() / 3 / w;
    let mut out = vec![0u8; src.len()];
    let mut lin = vec![0f32; w * 3];
    let mut clipped = 0u64;
    for y in 0..h {
        let row = &src[y * w * 3..(y + 1) * w * 3];
        convert_row(&plan, row, bytemuck_f32_mut(&mut lin), w as u32);
        for px in lin.as_chunks_mut::<3>().0 {
            let mut out_of_range = false;
            for v in px.iter_mut() {
                let e = srgb_encode(*v) * 255.0;
                if !(-0.5..=255.5).contains(&e) {
                    out_of_range = true;
                }
                *v = v.clamp(0.0, 1.0);
            }
            clipped += u64::from(out_of_range);
        }
        convert_row(
            &encode,
            bytemuck_f32(&lin),
            &mut out[y * w * 3..(y + 1) * w * 3],
            w as u32,
        );
    }
    let px = match alpha {
        None => Pixels::Rgb(out),
        Some(a) => Pixels::Rgba(
            out.as_chunks::<3>()
                .0
                .iter()
                .zip(&a)
                .flat_map(|(c, &a)| [c[0], c[1], c[2], a])
                .collect(),
        ),
    };
    Ok((px, clipped))
}

/// Sign-preserving sRGB encode, for measuring how far outside the gamut a value lands.
fn srgb_encode(v: f32) -> f32 {
    let a = v.abs();
    let e = if a <= 0.003_130_8 {
        a * 12.92
    } else {
        1.055 * a.powf(1.0 / 2.4) - 0.055
    };
    e.copysign(v)
}

fn bytemuck_f32(v: &[f32]) -> &[u8] {
    bytemuck::cast_slice(v)
}
fn bytemuck_f32_mut(v: &mut [f32]) -> &mut [u8] {
    bytemuck::cast_slice_mut(v)
}

/// Encode with zenpng; the provenance goes in a text chunk before the image data.
fn encode_png(
    px: &Pixels,
    w: usize,
    h: usize,
    colour: Colour,
    icc: Option<&[u8]>,
    provenance: &str,
    sub_byte_gray: Option<u8>,
) -> Result<Vec<u8>, String> {
    let mut cfg = EncodeConfig::default()
        .with_compression(Compression::Effort(EFFORT))
        .with_text(TEXT_KEYWORD, provenance);
    let mut meta = Metadata::default();
    if colour.is_srgb() {
        cfg = cfg.with_srgb_intent(Some(0));
    } else {
        let icc = icc.ok_or("a non-sRGB colour space without a profile")?;
        meta = meta.with_icc(icc.to_vec());
        if colour == Colour::DisplayP3 {
            cfg = cfg.with_cicp(Some(Cicp::new(12, 13, 0, true)));
        }
    }
    // A sub-byte greyscale source keeps its depth: zenpng's layout search on the expanded
    // pixels picks the sub-byte grey encoding, which the IHDR check below holds it to.
    if let (Pixels::Gray(_), Some(depth)) = (px, sub_byte_gray) {
        let c: Vec<rgb::Rgba<u8>> = px
            .rgba()
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
        let png = zenpng::encode_rgba8(
            imgref::Img::new(&c[..], w, h),
            Some(&meta),
            &cfg,
            &Unstoppable,
            &Unstoppable,
        )
        .map_err(|e| format!("encode: {e:?}"))?;
        let (got_depth, got_type) = (png[24], png[25]);
        if (got_depth, got_type) != (depth, 0) {
            return Err(format!(
                "wrote {got_depth}-bit colour type {got_type}, not the source's {depth}-bit grey"
            ));
        }
        return Ok(png);
    }
    match px {
        Pixels::Gray(p) => {
            let g: Vec<rgb::Gray<u8>> = p.iter().map(|&v| rgb::Gray::new(v)).collect();
            zenpng::encode_gray8(
                imgref::Img::new(&g[..], w, h),
                Some(&meta),
                &cfg,
                &Unstoppable,
                &Unstoppable,
            )
        }
        Pixels::Rgb(p) => {
            let c: Vec<rgb::Rgb<u8>> = p
                .as_chunks::<3>()
                .0
                .iter()
                .map(|c| rgb::Rgb {
                    r: c[0],
                    g: c[1],
                    b: c[2],
                })
                .collect();
            zenpng::encode_rgb8(
                imgref::Img::new(&c[..], w, h),
                Some(&meta),
                &cfg,
                &Unstoppable,
                &Unstoppable,
            )
        }
        Pixels::Rgba(p) => {
            let c: Vec<rgb::Rgba<u8>> = p
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
                imgref::Img::new(&c[..], w, h),
                Some(&meta),
                &cfg,
                &Unstoppable,
                &Unstoppable,
            )
        }
    }
    .map_err(|e| format!("encode: {e:?}"))
}

/// Decode a written PNG and check its pixels, size and provenance text.
fn check(png: &[u8], px: &Pixels, w: usize, h: usize, provenance: &str) -> Result<String, String> {
    let cfg = zenpng::PngDecodeConfig::default().with_max_pixels(1_000_000_000);
    let d = zenpng::decode(png, &cfg, &Unstoppable).map_err(|e| format!("re-decode: {e:?}"))?;
    if (d.info.width as usize, d.info.height as usize) != (w, h) {
        return Err("size changed".into());
    }
    // Relabelled sRGB so the comparison sees code values, not a gamut conversion.
    let back = d
        .pixels
        .with_primaries(ColorPrimaries::Bt709)
        .with_transfer(TransferFunction::Srgb)
        .to_rgba8()
        .copy_to_contiguous_bytes();
    let want = px.rgba();
    if back != want {
        return Err("PIXELS DIFFER".into());
    }
    let text = &d.info.text_chunks;
    if text.len() != 1
        || text[0].keyword != TEXT_KEYWORD
        || text[0].text != provenance
        || text[0].compressed
    {
        return Err("provenance text chunk missing or not the only one".into());
    }
    Ok(hex(&Sha256::digest(&want)))
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

struct Row<'a> {
    id: &'a str,
    source: &'a str,
    stem: &'a str,
    provenance: &'a str,
}

/// A source decoded for rendering: displayed orientation, code values, colour space.
struct Source {
    gain_map: Option<String>,
    alpha: &'static str,
    /// The bit depth of a greyscale PNG source stored below 8 bits (the 1-bit patent pages);
    /// its PNG layers keep that depth.
    sub_byte_gray: Option<u8>,
    colour: Colour,
    icc: Option<Vec<u8>>,
    px: Pixels,
    w: usize,
    h: usize,
}

fn load(row: &Row) -> Result<Source, String> {
    if row.source.to_ascii_lowercase().ends_with(".dng") {
        return Err("DNG: not rendered (EXPORT-PLAN, DNGs)".into());
    }
    let data = fs::read(row.source).map_err(|e| format!("read: {e}"))?;
    let gain_map = gain_map(&data, row.source)?;
    let limits = Limits::none()
        .with_max_pixels(400_000_000)
        .with_max_memory(12 << 30);
    let out = DecodeRequest::new(&data)
        .with_limits(&limits)
        .with_orientation(OrientationHint::Correct)
        .decode_full_frame()
        .map_err(|e| format!("decode: {e}"))?;
    let meta = out.metadata();
    let buf = out.into_buffer();
    let (w, h) = (buf.width() as usize, buf.height() as usize);
    let icc: Option<Vec<u8>> = meta
        .icc_profile
        .as_deref()
        .map(<[u8]>::to_vec)
        .or_else(|| heic_tile_icc(&data));
    let colour = classify(icc.as_deref())?;
    let (px, alpha) = code_values(buf)?;
    let sub_byte_gray = match zenpng::probe(&data) {
        Ok(info) if info.color_type == 0 && info.bit_depth < 8 => Some(info.bit_depth),
        _ => None,
    };
    Ok(Source {
        gain_map,
        alpha,
        sub_byte_gray,
        colour,
        icc,
        px,
        w,
        h,
    })
}

fn render(row: &Row, out_dir: &Path) -> Result<Vec<String>, String> {
    if !row.provenance.is_ascii() {
        return Err("provenance JSON must be ASCII (escape the rest as \\uXXXX)".into());
    }
    let Source {
        gain_map,
        alpha,
        sub_byte_gray,
        colour,
        icc,
        px,
        w,
        h,
    } = load(row)?;
    let name = format!("{}_{w}x{h}.png", row.stem);
    // The PNG layout column names a sub-byte grey file by its depth (gray1).
    let gray_layout = sub_byte_gray.map(|d| format!("gray{d}"));
    let layout_of = |px: &Pixels| -> String {
        gray_layout
            .clone()
            .filter(|_| matches!(px, Pixels::Gray(_)))
            .unwrap_or_else(|| px.layout().to_string())
    };
    let mut rows = Vec::new();

    // (layer, file, layout, rgba sha256, clipped pixels)
    let mut files: Vec<(&str, Vec<u8>, String, String, String)> = Vec::new();
    let png = encode_png(
        &px,
        w,
        h,
        colour,
        icc.as_deref(),
        row.provenance,
        sub_byte_gray,
    )?;
    let hash = check(&png, &px, w, h, row.provenance)?;
    if colour.is_srgb() {
        files.push((
            "png-p3",
            png.clone(),
            layout_of(&px),
            hash.clone(),
            String::new(),
        ));
        files.push(("png-srgb", png, layout_of(&px), hash, "0".into()));
    } else {
        files.push(("png-p3", png, layout_of(&px), hash, String::new()));
        let (spx, clipped) = to_srgb(&px, w, colour)?;
        let png = encode_png(
            &spx,
            w,
            h,
            Colour::Srgb,
            None,
            row.provenance,
            sub_byte_gray,
        )?;
        let hash = check(&png, &spx, w, h, row.provenance)?;
        files.push(("png-srgb", png, layout_of(&spx), hash, clipped.to_string()));
    }
    let gm = gain_map.as_deref().unwrap_or("");

    for (layer, png, layout, hash, clip) in &files {
        let path: PathBuf = out_dir.join(layer).join(&name);
        fs::create_dir_all(path.parent().unwrap()).map_err(|e| format!("mkdir: {e}"))?;
        fs::write(&path, png).map_err(|e| format!("write: {e}"))?;
        rows.push(format!(
            "{}\t{layer}\t{layer}/{name}\t{w}\t{h}\t{layout}\t{alpha}\t{}\t{gm}\t{clip}\t{}\t{}\t{hash}\t",
            row.id,
            colour.name(),
            png.len(),
            hex(&Sha256::digest(png)),
        ));
    }
    Ok(rows)
}

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let mut jobs = 1usize;
    if let Some(i) = args.iter().position(|a| a == "--jobs") {
        jobs = args
            .get(i + 1)
            .and_then(|v| v.parse().ok())
            .filter(|&n| n > 0)
            .unwrap_or_else(|| usage());
        args.drain(i..i + 2);
    }
    if let Some(i) = args.iter().position(|a| a == "--effort") {
        let effort = args
            .get(i + 1)
            .and_then(|v| v.parse().ok())
            .unwrap_or_else(|| usage());
        jxl::EFFORT.set(effort).expect("effort set once");
        args.drain(i..i + 2);
    }
    type Command = fn(&Row, &Path) -> Result<Vec<String>, String>;
    let (command, header): (Command, &str) = match (args.first().map(String::as_str), args.len()) {
        (Some("png-sdr"), 3) => (render, SDR_HEADER),
        (Some("png-hdr"), 3) => (hdr::render, hdr::HDR_HEADER),
        (Some("hdr-info"), 3) => (hdr::info, hdr::INFO_HEADER),
        (Some("jxl"), 3) => (jxl::render, jxl::JXL_HEADER),
        (Some("jxl-hdr"), 3) => (jxl::render_hdr, jxl::JXL_HEADER),
        _ => usage(),
    };
    let columns = header.split('\t').count();
    let list = fs::read_to_string(&args[1]).expect("read list");
    let out_dir = Path::new(&args[2]);
    let rows: Vec<Row> = list
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|line| {
            let f: Vec<&str> = line.splitn(4, '\t').collect();
            Row {
                id: f[0],
                source: f.get(1).copied().unwrap_or(""),
                stem: f.get(2).copied().unwrap_or(""),
                provenance: f.get(3).copied().unwrap_or("{}"),
            }
        })
        .collect();
    println!("{header}");
    let next = AtomicUsize::new(0);
    let failed = AtomicUsize::new(0);
    let done = AtomicUsize::new(0);
    let out = Mutex::new(std::io::stdout());
    let start = Instant::now();
    std::thread::scope(|scope| {
        for _ in 0..jobs.min(rows.len().max(1)) {
            scope.spawn(|| {
                loop {
                    let i = next.fetch_add(1, Ordering::Relaxed);
                    let Some(row) = rows.get(i) else { break };
                    let t = Instant::now();
                    let lines = match command(row, out_dir) {
                        Ok(lines) => lines,
                        Err(e) => {
                            failed.fetch_add(1, Ordering::Relaxed);
                            vec![format!(
                                "{}{}{}",
                                row.id,
                                "\t".repeat(columns - 1),
                                e.replace(['\t', '\n'], " ")
                            )]
                        }
                    };
                    let mut o = out.lock().unwrap();
                    for l in &lines {
                        writeln!(o, "{l}").expect("write report");
                    }
                    o.flush().expect("flush report");
                    drop(o);
                    let k = done.fetch_add(1, Ordering::Relaxed) + 1;
                    eprintln!(
                        "{k}/{} {} {:.1}s (elapsed {:.0}s, failed {})",
                        rows.len(),
                        row.id,
                        t.elapsed().as_secs_f64(),
                        start.elapsed().as_secs_f64(),
                        failed.load(Ordering::Relaxed)
                    );
                }
            });
        }
    });
    let failed = failed.into_inner();
    if failed > 0 {
        eprintln!("{failed} failed");
        std::process::exit(1);
    }
}

fn usage() -> ! {
    eprintln!(
        "usage: render-v4 <png-sdr|png-hdr|hdr-info|jxl|jxl-hdr> [--jobs N] [--effort N (jxl)] <list.tsv: id, source, out stem, provenance JSON> <out-dir>"
    );
    std::process::exit(2);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn buf(bytes: &[u8], w: u32, desc: PixelDescriptor) -> PixelBuffer {
        PixelBuffer::from_vec(bytes.to_vec(), w, 1, desc).unwrap()
    }

    #[test]
    fn orient_pixels_turns_like_exif_6() {
        // 3x2 stored, EXIF 6 (rotate 90 degrees clockwise) displays 2x3: the stored bottom-left
        // pixel lands top-left.
        let px = Pixels::Gray(vec![1, 2, 3, 4, 5, 6]);
        let (out, w, h) = orient_pixels(px, 3, 2, zencodec::Orientation::Rotate90);
        assert_eq!((w, h), (2, 3));
        let Pixels::Gray(g) = out else {
            panic!("layout changed")
        };
        assert_eq!(g, vec![4, 1, 5, 2, 6, 3]);
    }

    #[test]
    fn translucent_alpha_is_kept() {
        let (px, alpha) = code_values(buf(
            &[1, 2, 3, 255, 4, 5, 6, 128],
            2,
            PixelDescriptor::RGBA8_SRGB,
        ))
        .unwrap();
        assert_eq!(alpha, "kept");
        assert_eq!(px.layout(), "rgba8");
        assert_eq!(px.rgba(), [1, 2, 3, 255, 4, 5, 6, 128]);
    }

    #[test]
    fn opaque_alpha_is_dropped_and_reported() {
        let (px, alpha) = code_values(buf(
            &[1, 2, 3, 255, 4, 5, 6, 255],
            2,
            PixelDescriptor::RGBA8_SRGB,
        ))
        .unwrap();
        assert_eq!(alpha, "dropped-opaque");
        assert_eq!(px.layout(), "rgb8");
        assert_eq!(px.rgba(), [1, 2, 3, 255, 4, 5, 6, 255]);
    }

    #[test]
    fn padding_is_not_alpha() {
        let (px, alpha) = code_values(buf(
            &[1, 2, 3, 0, 4, 5, 6, 7],
            2,
            PixelDescriptor::RGBX8_SRGB,
        ))
        .unwrap();
        assert_eq!(alpha, "none");
        assert_eq!(px.layout(), "rgb8");
        assert_eq!(px.rgba(), [1, 2, 3, 255, 4, 5, 6, 255]);
    }

    #[test]
    fn opaque_gray_alpha_becomes_gray() {
        let (px, alpha) =
            code_values(buf(&[9, 255, 200, 255], 2, PixelDescriptor::GRAYA8_SRGB)).unwrap();
        assert_eq!(alpha, "dropped-opaque");
        assert_eq!(px.layout(), "gray8");
        assert_eq!(px.rgba(), [9, 9, 9, 255, 200, 200, 200, 255]);
    }
}
