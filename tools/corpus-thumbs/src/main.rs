//! Render thumbnail sprite sheets of corpus sources for a browsable gallery.
//!
//! Input: `id<TAB>path<TAB>colour` per line, where `colour` is the source's colour as
//! the signalling index established it (`srgb`, `p3`, `adobe`); zencodecs' probe misses
//! HEIC tile colour, so the caller supplies it. Each file is decoded with zencodecs
//! (orientation applied), converted to sRGB with zenpixels-convert when it isn't
//! already, fitted into a `CELL`×`CELL` box with zenresize (Lanczos, linear light), and
//! placed centred in a 10-column sheet on a transparent ground. The sheet is written as
//! WebP by zencodecs, with a TSV giving each id's cell and thumbnail size.
//!
//! Usage: corpus-thumbs <list.tsv> <out-prefix>   →  <out-prefix>.webp, <out-prefix>.tsv
//!
//! Preview mode writes one WebP per id instead of a sheet, fitted inside a
//! `max`×`max` box (never upscaled), for full-screen viewing:
//!   corpus-thumbs --preview <max> <quality> <list.tsv> <out-dir>
//!   →  <out-dir>/<id>.webp, <out-dir>/previews.tsv (id, w, h, bytes, orientation, error)
//!
//! dHash mode prints difference hashes of the oriented sRGB image for near-duplicate
//! search: 64-bit (9×8 luma) and 256-bit (17×16 luma), as hex.
//!   corpus-thumbs --dhash <list.tsv>   →  stdout: id, dhash64, dhash256, error
//!
//! To-JPEG mode re-encodes one 8-bit image as a baseline 4:4:4 JPEG with zenjpeg, keeping its
//! stored orientation and its code values (no colour management), and carrying only its ICC
//! profile and EXIF (which keeps the orientation tag). A HEIC grid whose colour sits only on
//! its tiles gets the tiles' ICC profile, provided every tile carries the same one. Tables:
//! `libjpeg100` is libjpeg's quality-100 scaling (every quantizer 1), `jpegli<q>` jpegli's
//! perceptual tables at quality q; adaptive quantization and deringing are off. It prints the
//! largest per-channel difference and the PSNR against the source's code values, and fails
//! unless the source (with its own HEIC transforms applied) and the JPEG (with its EXIF
//! orientation applied) display at the same size with the same pixels.
//!   corpus-thumbs --to-jpeg <libjpeg100|jpegli<q>> <in> <out.jpg>

#![forbid(unsafe_code)]

use std::fs;
use std::io::Write;

use zencodec::{Metadata, Orientation, OrientationHint};
use zencodecs::{DecodeRequest, EncodeRequest, ImageFormat, Limits};
use zenpixels::{ColorPrimaries, PixelDescriptor, TransferFunction};
use zenpixels_convert::{ConvertOptions, PixelBufferConvertTypedExt, RowConverter};
use zenresize::{Filter, ResizeConfig, Resizer};

const CELL: usize = 256;
const COLS: usize = 10;

struct Rgba {
    w: usize,
    h: usize,
    px: Vec<u8>,
}

/// Rotate/flip an RGBA image into display orientation (EXIF value).
fn orient(src: Rgba, o: u8) -> Rgba {
    if o <= 1 {
        return src;
    }
    let (w, h) = (src.w, src.h);
    let (dw, dh) = if o >= 5 { (h, w) } else { (w, h) };
    let mut px = vec![0u8; dw * dh * 4];
    for y in 0..dh {
        for x in 0..dw {
            let (sx, sy) = match o {
                2 => (w - 1 - x, y),
                3 => (w - 1 - x, h - 1 - y),
                4 => (x, h - 1 - y),
                5 => (y, x),
                6 => (y, h - 1 - x),
                7 => (w - 1 - y, h - 1 - x),
                _ => (w - 1 - y, x),
            };
            let s = (sy * w + sx) * 4;
            let d = (y * dw + x) * 4;
            px[d..d + 4].copy_from_slice(&src.px[s..s + 4]);
        }
    }
    Rgba { w: dw, h: dh, px }
}

/// Decode to display-oriented RGBA8. Returns the image and the orientation the decoder
/// left for us to apply (the RAW adapter doesn't bake it).
fn decode(data: &[u8]) -> Result<(Rgba, u8), String> {
    let limits = Limits::none()
        .with_max_pixels(400_000_000)
        .with_max_memory(12 << 30);
    let out = DecodeRequest::new(data)
        .with_limits(&limits)
        .with_orientation(OrientationHint::Correct)
        .decode_full_frame()
        .map_err(|e| format!("decode: {e}"))?;
    let left = out.info().orientation;
    if std::env::var_os("DEBUG_DECODE").is_some() {
        let d = out.descriptor();
        let bytes = out
            .pixels()
            .as_contiguous_bytes()
            .map(|b| b.len())
            .unwrap_or(0);
        eprintln!(
            "DEBUG {}x{} {d:?} bytes={bytes} source_color={:?}",
            out.width(),
            out.height(),
            out.info().source_color
        );
        if let Some(b) = out.pixels().as_contiguous_bytes()
            && d.format == zenpixels::PixelFormat::Rgb16
        {
            let mut sum = [0f64; 3];
            let mut max = [0u16; 3];
            let n = b.len() / 6;
            for p in b.as_chunks::<6>().0 {
                for c in 0..3 {
                    let v = u16::from_ne_bytes([p[2 * c], p[2 * c + 1]]);
                    sum[c] += v as f64;
                    max[c] = max[c].max(v);
                }
            }
            eprintln!(
                "DEBUG rgb16 mean {:?} max {max:?}",
                sum.map(|s| s / n as f64)
            );
        }
    }
    let buf = out.into_buffer().to_rgba8();
    let (w, h) = (buf.width() as usize, buf.height() as usize);
    let px = buf.copy_to_contiguous_bytes();
    if std::env::var_os("DEBUG_DECODE").is_some() {
        let mut sum = [0f64; 4];
        for p in px.as_chunks::<4>().0 {
            for c in 0..4 {
                sum[c] += p[c] as f64;
            }
        }
        eprintln!("DEBUG rgba8 mean {:?}", sum.map(|s| s / (w * h) as f64));
    }
    let o = if left == Orientation::Identity {
        1
    } else {
        left.to_exif()
    };
    Ok((Rgba { w, h, px }, o))
}

/// Convert RGBA8 in place from the given source colour to sRGB.
fn to_srgb(img: &mut Rgba, colour: &str) -> Result<(), String> {
    let from = match colour {
        "p3" => PixelDescriptor::RGBA8_SRGB.with_primaries(ColorPrimaries::DisplayP3),
        "adobe" => PixelDescriptor::RGBA8_SRGB
            .with_primaries(ColorPrimaries::AdobeRgb)
            .with_transfer(TransferFunction::Gamma22),
        _ => return Ok(()),
    };
    let mut conv = RowConverter::new_explicit(
        from,
        PixelDescriptor::RGBA8_SRGB,
        &ConvertOptions::permissive(),
    )
    .map_err(|e| format!("convert: {e:?}"))?;
    let row = img.w * 4;
    let mut out = vec![0u8; row];
    for y in 0..img.h {
        let r = &mut img.px[y * row..(y + 1) * row];
        conv.convert_row(r, &mut out, img.w as u32);
        r.copy_from_slice(&out);
    }
    Ok(())
}

fn thumbnail(path: &str, colour: &str, cell: usize) -> Result<(Rgba, u8), String> {
    let data = fs::read(path).map_err(|e| format!("read: {e}"))?;
    let (img, o) = decode(&data)?;
    let mut img = orient(img, o);
    to_srgb(&mut img, colour)?;
    let scale = (cell as f64 / img.w as f64)
        .min(cell as f64 / img.h as f64)
        .min(1.0);
    let tw = ((img.w as f64 * scale).round() as usize).max(1);
    let th = ((img.h as f64 * scale).round() as usize).max(1);
    if (tw, th) == (img.w, img.h) {
        // Nothing to resize (a preview no smaller than the image): zenresize caps its output
        // at 100 MP, which the 124 MP panorama passes.
        return Ok((img, o));
    }
    let config = ResizeConfig::builder(img.w as u32, img.h as u32, tw as u32, th as u32)
        .filter(Filter::Lanczos)
        .format(zenresize::PixelDescriptor::RGBA8_SRGB)
        .build();
    let px = Resizer::new(&config).resize(&img.px);
    Ok((Rgba { w: tw, h: th, px }, o))
}

fn encode_webp(img: &Rgba, quality: f32) -> Result<Vec<u8>, String> {
    let pixels: Vec<rgb::Rgba<u8>> = img
        .px
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
    let view = imgref::ImgVec::new(pixels, img.w, img.h);
    EncodeRequest::new(ImageFormat::WebP)
        .with_quality(quality)
        .encode_full_frame_rgba8(view.as_ref())
        .map(|o| o.data().to_vec())
        .map_err(|e| format!("encode: {e}"))
}

fn previews(args: &[String]) {
    let max: usize = args[2].parse().expect("max");
    let quality: f32 = args[3].parse().expect("quality");
    let list = fs::read_to_string(&args[4]).expect("read list");
    let out = std::path::Path::new(&args[5]);
    fs::create_dir_all(out).expect("create out dir");
    let mut tsv = String::from("id\tw\th\tbytes\torientation_applied\terror\n");
    let lines: Vec<&str> = list.lines().filter(|l| !l.trim().is_empty()).collect();
    for (n, line) in lines.iter().enumerate() {
        let f: Vec<&str> = line.split('\t').collect();
        let (id, path, colour) = (
            f[0],
            f.get(1).copied().unwrap_or(""),
            f.get(2).copied().unwrap_or("srgb"),
        );
        match thumbnail(path, colour, max)
            .and_then(|(t, o)| encode_webp(&t, quality).map(|b| (t, o, b)))
        {
            Ok((t, o, bytes)) => {
                fs::write(out.join(format!("{id}.webp")), &bytes).expect("write preview");
                tsv.push_str(&format!("{id}\t{}\t{}\t{}\t{o}\t\n", t.w, t.h, bytes.len()));
                eprintln!(
                    "[{}/{}] {id} {}x{} {} B",
                    n + 1,
                    lines.len(),
                    t.w,
                    t.h,
                    bytes.len()
                );
            }
            Err(e) => {
                let e = e.replace(['\t', '\n'], " ");
                tsv.push_str(&format!("{id}\t0\t0\t0\t\t{e}\n"));
                eprintln!("[{}/{}] {id} {e}", n + 1, lines.len());
            }
        }
    }
    fs::write(out.join("previews.tsv"), tsv).expect("write tsv");
}

/// Difference hash: resize to (w+1)×h luma, one bit per horizontal neighbour pair.
fn dhash(img: &Rgba, w: usize, h: usize) -> String {
    let config = ResizeConfig::builder(img.w as u32, img.h as u32, (w + 1) as u32, h as u32)
        .filter(Filter::Lanczos)
        .format(zenresize::PixelDescriptor::RGBA8_SRGB)
        .build();
    let px = Resizer::new(&config).resize(&img.px);
    let luma: Vec<f32> = px
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| 0.2126 * c[0] as f32 + 0.7152 * c[1] as f32 + 0.0722 * c[2] as f32)
        .collect();
    let mut bits = Vec::with_capacity(w * h);
    for y in 0..h {
        for x in 0..w {
            bits.push(luma[y * (w + 1) + x] < luma[y * (w + 1) + x + 1]);
        }
    }
    bits.chunks(4)
        .map(|n| format!("{:x}", n.iter().fold(0u8, |a, &b| (a << 1) | b as u8)))
        .collect()
}

fn dhashes(path: &str, colour: &str) -> Result<(String, String), String> {
    let data = fs::read(path).map_err(|e| format!("read: {e}"))?;
    let (img, o) = decode(&data)?;
    let mut img = orient(img, o);
    to_srgb(&mut img, colour)?;
    Ok((dhash(&img, 8, 8), dhash(&img, 16, 16)))
}

/// Decode in stored orientation to 8-bit RGB code values, without colour management: the
/// buffer is relabelled sRGB before the layout conversion, so no gamut or transfer conversion
/// runs. Sources deeper than 8 bits or with alpha are refused.
fn decode_stored(data: &[u8]) -> Result<(Vec<u8>, usize, usize, Metadata), String> {
    decode_code_values(data, OrientationHint::Preserve)
}

fn decode_code_values(
    data: &[u8],
    orientation: OrientationHint,
) -> Result<(Vec<u8>, usize, usize, Metadata), String> {
    let limits = Limits::none()
        .with_max_pixels(400_000_000)
        .with_max_memory(12 << 30);
    let out = DecodeRequest::new(data)
        .with_limits(&limits)
        .with_orientation(orientation)
        .decode_full_frame()
        .map_err(|e| format!("decode: {e}"))?;
    let meta = out.metadata();
    let buf = out.into_buffer();
    let desc = buf.descriptor();
    if desc.channel_type() != zenpixels::ChannelType::U8 || desc.alpha.is_some() {
        return Err(format!("not 8-bit RGB without alpha: {desc:?}"));
    }
    let buf = buf
        .with_primaries(zenpixels::ColorPrimaries::Bt709)
        .with_transfer(zenpixels::TransferFunction::Srgb)
        .to_rgb8();
    let (w, h) = (buf.width() as usize, buf.height() as usize);
    Ok((buf.copy_to_contiguous_bytes(), w, h, meta))
}

fn to_jpeg(input: &str, output: &str, tables: &str) -> Result<String, String> {
    use zencodecs::config::jpeg::{
        ChromaSubsampling, EncoderConfig, Exif, JpegPixelLayout, Quality,
    };
    let config = if tables == "libjpeg100" {
        EncoderConfig::ycbcr(Quality::ApproxMozjpeg(100), ChromaSubsampling::None)
            .quant_table_config(zenjpeg::encoder::QuantTableConfig::MozjpegRobidoux {
                chroma_quality: None,
            })
    } else if let Some(q) = tables.strip_prefix("jpegli") {
        let q: f32 = q.parse().map_err(|_| format!("bad quality in {tables}"))?;
        EncoderConfig::ycbcr(q, ChromaSubsampling::None)
    } else {
        return Err(format!("unknown tables {tables}"));
    }
    .force_baseline()
    .aq_enabled(false)
    .deringing(false);

    let data = fs::read(input).map_err(|e| format!("read: {e}"))?;
    let (rgb, w, h, meta) = decode_stored(&data)?;
    let (icc, icc_note) = match meta.icc_profile.as_deref() {
        Some(icc) => (Some(icc.to_vec()), "icc from primary"),
        None => match heic_tile_icc(&data)? {
            Some(icc) => (Some(icc), "icc from tiles"),
            None => (None, "no icc"),
        },
    };
    let mut request = config.request();
    if let Some(icc) = &icc {
        request = request.icc_profile(icc);
    }
    if let Some(exif) = meta.exif.as_deref() {
        request = request.exif(Exif::raw(exif.to_vec()));
    }
    let jpg = request
        .encode_bytes(&rgb, w as u32, h as u32, JpegPixelLayout::Rgb8Srgb)
        .map_err(|e| format!("encode: {e}"))?;
    fs::write(output, &jpg).map_err(|e| format!("write: {e}"))?;

    let (back, bw, bh, back_meta) = decode_stored(&jpg)?;
    if (bw, bh) != (w, h) {
        return Err(format!("size changed: {w}x{h} -> {bw}x{bh}"));
    }
    if back_meta.icc_profile.as_deref() != icc.as_deref() || back_meta.exif != meta.exif {
        return Err("ICC or EXIF not carried".into());
    }
    let mut max = 0u8;
    let mut se = 0f64;
    for (a, b) in rgb.iter().zip(back.iter()) {
        let d = a.abs_diff(*b);
        max = max.max(d);
        se += (d as f64) * (d as f64);
    }
    let mse = se / rgb.len() as f64;
    let psnr = if mse == 0.0 {
        f64::INFINITY
    } else {
        10.0 * (255.0f64 * 255.0 / mse).log10()
    };

    // Both files must display the same way: the source with its own transforms (HEIC
    // irot/imir) applied, the JPEG with its EXIF orientation applied.
    let (src_shown, sw, sh, _) = decode_code_values(&data, OrientationHint::Correct)?;
    let (jpg_shown, jw, jh, _) = decode_code_values(&jpg, OrientationHint::Correct)?;
    if (sw, sh) != (jw, jh) {
        return Err(format!(
            "displayed size differs: source {sw}x{sh}, jpeg {jw}x{jh}"
        ));
    }
    let shown_max = src_shown
        .iter()
        .zip(&jpg_shown)
        .map(|(a, b)| a.abs_diff(*b))
        .max()
        .unwrap_or(0);
    if shown_max != max {
        return Err(format!(
            "displayed pixels differ by up to {shown_max}, stored by {max}"
        ));
    }
    Ok(format!(
        "{w}x{h} stored, {sw}x{sh} displayed, {} bytes, {icc_note}, max diff {max}, PSNR {psnr:.2} dB",
        jpg.len()
    ))
}

/// The ICC profile shared by every tile of a HEIC grid primary, when the grid item itself
/// has none. `Ok(None)` for non-HEIC input, a non-grid primary, or tiles without an ICC
/// profile; an error when the tiles disagree.
fn heic_tile_icc(data: &[u8]) -> Result<Option<Vec<u8>>, String> {
    use heic::heif::{ColorInfo, FourCC};
    let Ok(container) = heic::heif::parse(data, &heic::Unstoppable) else {
        return Ok(None);
    };
    let Some(primary) = container.primary_item() else {
        return Ok(None);
    };
    let tiles = container.get_item_references(primary.id, FourCC(*b"dimg"));
    let mut found: Option<Vec<u8>> = None;
    for id in &tiles {
        let icc = match container.get_item(*id).and_then(|t| t.color_info) {
            Some(ColorInfo::IccProfile(icc)) => icc,
            _ => return Ok(None),
        };
        match &found {
            None => found = Some(icc),
            Some(f) if *f == icc => {}
            Some(_) => {
                return Err(format!(
                    "tiles of item {} carry different ICC profiles",
                    primary.id
                ));
            }
        }
    }
    Ok(found)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() == 5 && args[1] == "--to-jpeg" {
        match to_jpeg(&args[3], &args[4], &args[2]) {
            Ok(s) => println!("{s}"),
            Err(e) => {
                eprintln!("{e}");
                std::process::exit(1);
            }
        }
        return;
    }
    if args.len() == 3 && args[1] == "--dhash" {
        let list = fs::read_to_string(&args[2]).expect("read list");
        let mut out = std::io::stdout().lock();
        for line in list.lines().filter(|l| !l.trim().is_empty()) {
            let f: Vec<&str> = line.split('\t').collect();
            let (id, path, colour) = (
                f[0],
                f.get(1).copied().unwrap_or(""),
                f.get(2).copied().unwrap_or("srgb"),
            );
            match dhashes(path, colour) {
                Ok((a, b)) => writeln!(out, "{id}\t{a}\t{b}\t").unwrap(),
                Err(e) => writeln!(out, "{id}\t\t\t{}", e.replace(['\t', '\n'], " ")).unwrap(),
            }
        }
        return;
    }
    if args.len() == 6 && args[1] == "--preview" {
        previews(&args);
        return;
    }
    if args.len() != 3 {
        eprintln!("usage: corpus-thumbs <list.tsv: id<TAB>path<TAB>colour> <out-prefix>");
        eprintln!("       corpus-thumbs --preview <max> <quality> <list.tsv> <out-dir>");
        eprintln!("       corpus-thumbs --dhash <list.tsv>");
        std::process::exit(2);
    }
    let list = fs::read_to_string(&args[1]).expect("read list");
    let lines: Vec<&str> = list.lines().filter(|l| !l.trim().is_empty()).collect();
    let rows = lines.len().div_ceil(COLS);
    let (sw, sh) = (COLS * CELL, rows * CELL);
    let mut sheet = vec![0u8; sw * sh * 4];
    let mut tsv = String::from("id\tcol\trow\tw\th\torientation_applied\terror\n");
    for (n, line) in lines.iter().enumerate() {
        let f: Vec<&str> = line.split('\t').collect();
        let (id, path, colour) = (
            f[0],
            f.get(1).copied().unwrap_or(""),
            f.get(2).copied().unwrap_or("srgb"),
        );
        let (col, row) = (n % COLS, n / COLS);
        match thumbnail(path, colour, CELL) {
            Ok((t, o)) => {
                let (ox, oy) = (col * CELL + (CELL - t.w) / 2, row * CELL + (CELL - t.h) / 2);
                for y in 0..t.h {
                    let d = ((oy + y) * sw + ox) * 4;
                    sheet[d..d + t.w * 4].copy_from_slice(&t.px[y * t.w * 4..(y + 1) * t.w * 4]);
                }
                tsv.push_str(&format!("{id}\t{col}\t{row}\t{}\t{}\t{o}\t\n", t.w, t.h));
                eprintln!("[{}/{}] {id}", n + 1, lines.len());
            }
            Err(e) => {
                let e = e.replace(['\t', '\n'], " ");
                tsv.push_str(&format!("{id}\t{col}\t{row}\t0\t0\t\t{e}\n"));
                eprintln!("[{}/{}] {id} {e}", n + 1, lines.len());
            }
        }
    }
    let pixels: Vec<rgb::Rgba<u8>> = sheet
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
    let img = imgref::ImgVec::new(pixels, sw, sh);
    let webp = EncodeRequest::new(ImageFormat::WebP)
        .with_quality(80.0)
        .encode_full_frame_rgba8(img.as_ref())
        .expect("encode sheet");
    fs::write(format!("{}.webp", args[2]), webp.data()).expect("write sheet");
    fs::File::create(format!("{}.tsv", args[2]))
        .and_then(|mut f| f.write_all(tsv.as_bytes()))
        .expect("write tsv");
}
