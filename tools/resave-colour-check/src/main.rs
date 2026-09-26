//! Locate a re-saved crop inside its camera original and test what the re-save did to
//! colour. Both files are decoded by zencodecs with orientation applied; the crop is
//! found by searching offsets on a luma grid; then the crop's pixels are compared with
//! the original's pixels under two hypotheses:
//!
//! - `raw`:  the re-save copied the original's sample values and dropped the profile;
//! - `srgb`: the re-save converted the original from `--from` primaries to sRGB.
//!
//! The decisive numbers are on pixels where the two hypotheses differ by more than
//! `SPLIT` levels: whichever hypothesis the crop sits close to there is what happened.
//!
//! Usage: resave-colour-check <original> <crop> [--from p3|adobe]

#![forbid(unsafe_code)]

use std::fs;

use zencodec::{Orientation, OrientationHint};
use zencodecs::{DecodeRequest, Limits};
use zenpixels::{ColorPrimaries, PixelDescriptor, TransferFunction};
use zenpixels_convert::{ConvertOptions, PixelBufferConvertTypedExt, RowConverter};

/// Pixels whose two hypotheses differ by more than this (max over channels) decide.
const SPLIT: i32 = 8;

struct Rgba {
    w: usize,
    h: usize,
    px: Vec<u8>,
}

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

fn decode(path: &str) -> Rgba {
    let data = fs::read(path).expect("read");
    let limits = Limits::none()
        .with_max_pixels(400_000_000)
        .with_max_memory(12 << 30);
    let out = DecodeRequest::new(&data)
        .with_limits(&limits)
        .with_orientation(OrientationHint::Correct)
        .decode_full_frame()
        .expect("decode");
    let left = out.info().orientation;
    let buf = out.into_buffer().to_rgba8();
    let img = Rgba {
        w: buf.width() as usize,
        h: buf.height() as usize,
        px: buf.copy_to_contiguous_bytes(),
    };
    let o = if left == Orientation::Identity {
        1
    } else {
        left.to_exif()
    };
    orient(img, o)
}

fn wide(from: &str) -> PixelDescriptor {
    match from {
        "adobe" => PixelDescriptor::RGBA8_SRGB
            .with_primaries(ColorPrimaries::AdobeRgb)
            .with_transfer(TransferFunction::Gamma22),
        _ => PixelDescriptor::RGBA8_SRGB.with_primaries(ColorPrimaries::DisplayP3),
    }
}

fn convert(img: &Rgba, src: PixelDescriptor, dst: PixelDescriptor) -> Rgba {
    let mut conv =
        RowConverter::new_explicit(src, dst, &ConvertOptions::permissive()).expect("converter");
    let row = img.w * 4;
    let mut px = vec![0u8; img.px.len()];
    for y in 0..img.h {
        conv.convert_row(
            &img.px[y * row..(y + 1) * row],
            &mut px[y * row..(y + 1) * row],
            img.w as u32,
        );
    }
    Rgba {
        w: img.w,
        h: img.h,
        px,
    }
}

fn luma(p: &[u8]) -> i32 {
    (p[0] as i32 * 2 + p[1] as i32 * 5 + p[2] as i32) / 8
}

/// Mean absolute luma difference of `crop` placed at (dx, dy) in `orig`, sampled every `step`.
fn score(orig: &Rgba, crop: &Rgba, dx: usize, dy: usize, step: usize) -> f64 {
    let (mut sum, mut n) = (0i64, 0i64);
    for y in (0..crop.h).step_by(step) {
        for x in (0..crop.w).step_by(step) {
            let c = (y * crop.w + x) * 4;
            let o = ((y + dy) * orig.w + x + dx) * 4;
            sum += (luma(&crop.px[c..c + 4]) - luma(&orig.px[o..o + 4])).abs() as i64;
            n += 1;
        }
    }
    sum as f64 / n as f64
}

fn locate(orig: &Rgba, crop: &Rgba) -> (usize, usize, f64) {
    assert!(
        crop.w <= orig.w && crop.h <= orig.h,
        "crop is larger than the original"
    );
    // coarse: every 4th offset, sparse samples
    let mut coarse = (0, 0, f64::MAX);
    for dy in (0..=orig.h - crop.h).step_by(4) {
        for dx in (0..=orig.w - crop.w).step_by(4) {
            let s = score(orig, crop, dx, dy, 16);
            if s < coarse.2 {
                coarse = (dx, dy, s);
            }
        }
    }
    // fine: every offset within 4 of the coarse best, denser samples
    let mut best = (coarse.0, coarse.1, f64::MAX);
    for dy in coarse.1.saturating_sub(4)..=(coarse.1 + 4).min(orig.h - crop.h) {
        for dx in coarse.0.saturating_sub(4)..=(coarse.0 + 4).min(orig.w - crop.w) {
            let s = score(orig, crop, dx, dy, 4);
            if s < best.2 {
                best = (dx, dy, s);
            }
        }
    }
    (best.0, best.1, score(orig, crop, best.0, best.1, 1))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: resave-colour-check <original> <crop> [--from p3|adobe]");
        std::process::exit(2);
    }
    let from = args
        .iter()
        .position(|a| a == "--from")
        .and_then(|i| args.get(i + 1))
        .map_or("p3", |s| s.as_str());
    let orig = decode(&args[1]);
    let crop = decode(&args[2]);
    println!("original {}x{}, crop {}x{}", orig.w, orig.h, crop.w, crop.h);
    let (dx, dy, luma_mae) = locate(&orig, &crop);
    println!("crop offset ({dx}, {dy}), luma MAE {luma_mae:.3}");
    let hyps = [
        ("raw values, profile dropped".to_string(), None),
        (
            format!("converted {from} -> sRGB"),
            Some(convert(&orig, wide(from), PixelDescriptor::RGBA8_SRGB)),
        ),
        (
            format!("treated as sRGB, converted -> {from}"),
            Some(convert(&orig, PixelDescriptor::RGBA8_SRGB, wide(from))),
        ),
    ];
    let conv = hyps[1].1.as_ref().unwrap();
    let pick = |h: &Option<Rgba>, o: usize| h.as_ref().map_or(orig.px[o], |r| r.px[o]) as i32;
    let n_hyp = hyps.len();
    let (mut all, mut dec, mut bias) = (
        vec![[0i64; 3]; n_hyp],
        vec![[0i64; 3]; n_hyp],
        vec![[0i64; 3]; n_hyp],
    );
    let (mut n_all, mut n_dec) = (0i64, 0i64);
    // least-squares fit crop = a * raw + b per channel, all pixels
    let (mut sx, mut sy, mut sxx, mut sxy) = ([0f64; 3], [0f64; 3], [0f64; 3], [0f64; 3]);
    for y in 0..crop.h {
        for x in 0..crop.w {
            let c = (y * crop.w + x) * 4;
            let o = ((y + dy) * orig.w + x + dx) * 4;
            let split = (0..3)
                .map(|k| (orig.px[o + k] as i32 - conv.px[o + k] as i32).abs())
                .max()
                .unwrap();
            let deciding = split > SPLIT;
            for k in 0..3 {
                let cv = crop.px[c + k] as i32;
                for (h, (_, img)) in hyps.iter().enumerate() {
                    let e = cv - pick(img, o + k);
                    all[h][k] += e.abs() as i64;
                    if deciding {
                        dec[h][k] += e.abs() as i64;
                        bias[h][k] += e as i64;
                    }
                }
                let r = orig.px[o + k] as f64;
                sx[k] += r;
                sy[k] += cv as f64;
                sxx[k] += r * r;
                sxy[k] += r * cv as f64;
            }
            n_all += 1;
            if deciding {
                n_dec += 1;
            }
        }
    }
    let f = |a: [i64; 3], n: i64| {
        a.map(|v| format!("{:.2}", v as f64 / n.max(1) as f64))
            .join(" / ")
    };
    println!(
        "hypothesis\tall pixels MAE R/G/B\tdeciding pixels ({n_dec} of {n_all}) MAE R/G/B\tdeciding bias R/G/B"
    );
    for (h, (name, _)) in hyps.iter().enumerate() {
        println!(
            "{name}\t{}\t{}\t{}",
            f(all[h], n_all),
            f(dec[h], n_dec),
            f(bias[h], n_dec)
        );
    }
    let n = n_all as f64;
    let fit: Vec<String> = (0..3)
        .map(|k| {
            let a = (n * sxy[k] - sx[k] * sy[k]) / (n * sxx[k] - sx[k] * sx[k]);
            let b = (sy[k] - a * sx[k]) / n;
            format!("{a:.3}x{b:+.1}")
        })
        .collect();
    println!("fit crop = a * raw + b (R, G, B): {}", fit.join(", "));
}
