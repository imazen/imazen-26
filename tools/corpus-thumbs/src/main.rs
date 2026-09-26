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

#![forbid(unsafe_code)]

use std::fs;
use std::io::Write;

use zencodec::{Orientation, OrientationHint};
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

fn thumbnail(path: &str, colour: &str) -> Result<(Rgba, u8), String> {
    let data = fs::read(path).map_err(|e| format!("read: {e}"))?;
    let (img, o) = decode(&data)?;
    let mut img = orient(img, o);
    to_srgb(&mut img, colour)?;
    let scale = (CELL as f64 / img.w as f64)
        .min(CELL as f64 / img.h as f64)
        .min(1.0);
    let tw = ((img.w as f64 * scale).round() as usize).max(1);
    let th = ((img.h as f64 * scale).round() as usize).max(1);
    let config = ResizeConfig::builder(img.w as u32, img.h as u32, tw as u32, th as u32)
        .filter(Filter::Lanczos)
        .format(zenresize::PixelDescriptor::RGBA8_SRGB)
        .build();
    let px = Resizer::new(&config).resize(&img.px);
    Ok((Rgba { w: tw, h: th, px }, o))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: corpus-thumbs <list.tsv: id<TAB>path<TAB>colour> <out-prefix>");
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
        match thumbnail(path, colour) {
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
