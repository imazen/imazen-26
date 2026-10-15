//! Losslessly recompress ("crush") corpus PNGs with zenpng.
//!
//! Each input is decoded with zenpng, re-encoded with the requested compression preset,
//! decoded again and compared with the source pixel by pixel (as RGBA8, which is exact
//! for 8-bit and sub-byte sources). The output is written only when the pixels match.
//!
//! Carried over: ICC profile, EXIF, gamma, sRGB intent, chromaticities, cICP, cLLI,
//! mDCV and pHYs. Dropped, by the owner's decisions of 2026-10-15: text chunks (tEXt,
//! zTXt, iTXt: the IPTC and XMP packets on three AI images), XMP, C2PA (caBX) and every
//! other unknown chunk, sBIT, bKGD and tIME. zenpng picks the smallest lossless layout
//! (RGB, grey, palette, sub-byte grey; a fully opaque alpha channel is removed).
//!
//! Usage: png-crush <effort|crush|maniac> <list.tsv> <out-dir>
//!   list: id<TAB>input path<TAB>output relative path
//!   →  <out-dir>/<output relative path>, and a TSV report on stdout:
//!      id, in_bytes, out_bytes, ms, in_layout, out_layout, dropped, error

#![forbid(unsafe_code)]

use std::fs;
use std::path::Path;
use std::time::Instant;

use enough::Unstoppable;
use zencodec::Metadata;
use zenpixels_convert::PixelBufferConvertTypedExt as _;
use zenpng::{Compression, EncodeConfig, PngDecodeConfig, decode, encode_rgba8};

fn layout(info: &zenpng::PngInfo) -> String {
    let ct = match info.color_type {
        0 => "gray",
        2 => "rgb",
        3 => "palette",
        4 => "gray+alpha",
        6 => "rgba",
        _ => "?",
    };
    format!("{}-bit {ct}", info.bit_depth)
}

fn crush(input: &Path, output: &Path, compression: Compression) -> Result<(u64, u64, u128, String, String, String), String> {
    let src = fs::read(input).map_err(|e| format!("read: {e}"))?;
    let cfg = PngDecodeConfig::default()
        .with_max_pixels(1_000_000_000)
        .with_collect_unknown_chunks(true);
    let a = decode(&src, &cfg, &Unstoppable).map_err(|e| format!("decode: {e:?}"))?;
    let info = &a.info;
    if info.bit_depth > 8 {
        return Err("16-bit source: not handled by this tool".into());
    }

    let mut dropped = Vec::new();
    if !info.text_chunks.is_empty() {
        dropped.push(format!("text×{}", info.text_chunks.len()));
    }
    if info.xmp.is_some() {
        dropped.push("xmp".into());
    }
    for c in &info.unknown_chunks {
        dropped.push(String::from_utf8_lossy(&c.tag).into_owned());
    }
    if let Some(sb) = &info.significant_bits {
        dropped.push(format!("sBIT{sb:?}").replace(' ', ""));
    }
    if info.background.is_some() {
        dropped.push("bKGD".into());
    }
    if info.last_modified.is_some() {
        dropped.push("tIME".into());
    }

    let mut meta = Metadata::default();
    if let Some(icc) = &info.icc_profile {
        meta = meta.with_icc(icc.clone());
    }
    if let Some(exif) = &info.exif {
        meta = meta.with_exif(exif.clone());
    }
    let mut enc = EncodeConfig::default()
        .with_compression(compression)
        .with_preserve_transparent_rgb(true)
        .with_source_gamma(info.source_gamma)
        .with_srgb_intent(info.srgb_intent)
        .with_chromaticities(info.chromaticities)
        .with_cicp(info.cicp)
        .with_content_light_level_raw(info.content_light_level_raw)
        .with_mastering_display_raw(info.mastering_display_raw);
    if let (Some(x), Some(y), Some(unit)) = (info.pixels_per_unit_x, info.pixels_per_unit_y, info.phys_unit) {
        enc = enc.with_phys(x, y, unit);
    }

    let rgba = a.pixels.to_rgba8();
    let t = Instant::now();
    let out = encode_rgba8(rgba.as_imgref(), Some(&meta), &enc, &Unstoppable, &Unstoppable)
        .map_err(|e| format!("encode: {e:?}"))?;
    let ms = t.elapsed().as_millis();

    let b = decode(&out, &cfg, &Unstoppable).map_err(|e| format!("re-decode: {e:?}"))?;
    if b.info.width != info.width || b.info.height != info.height {
        return Err("dimensions changed".into());
    }
    let rgba_b = b.pixels.to_rgba8();
    if rgba.copy_to_contiguous_bytes() != rgba_b.copy_to_contiguous_bytes() {
        return Err("PIXELS DIFFER".into());
    }
    if b.info.icc_profile != info.icc_profile || b.info.exif != info.exif {
        return Err("ICC or EXIF not carried".into());
    }
    if (b.info.pixels_per_unit_x, b.info.pixels_per_unit_y) != (info.pixels_per_unit_x, info.pixels_per_unit_y) {
        return Err("pHYs not carried".into());
    }
    if let Some(dir) = output.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("mkdir: {e}"))?;
    }
    fs::write(output, &out).map_err(|e| format!("write: {e}"))?;
    Ok((src.len() as u64, out.len() as u64, ms, layout(info), layout(&b.info), dropped.join(",")))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        eprintln!("usage: png-crush <effort|crush|maniac> <list.tsv: id<TAB>in<TAB>out-rel> <out-dir>");
        std::process::exit(2);
    }
    let compression = match args[1].as_str() {
        "crush" => Compression::Crush,
        "maniac" => Compression::Maniac,
        n => Compression::Effort(n.parse().expect("effort number, crush or maniac")),
    };
    let list = fs::read_to_string(&args[2]).expect("read list");
    let out_dir = Path::new(&args[3]);
    println!("id\tin_bytes\tout_bytes\tms\tin_layout\tout_layout\tdropped\terror");
    for line in list.lines().filter(|l| !l.trim().is_empty()) {
        let f: Vec<&str> = line.split('\t').collect();
        let (id, input, rel) = (f[0], f[1], f[2]);
        match crush(Path::new(input), &out_dir.join(rel), compression) {
            Ok((a, b, ms, li, lo, d)) => println!("{id}\t{a}\t{b}\t{ms}\t{li}\t{lo}\t{d}\t"),
            Err(e) => println!("{id}\t\t\t\t\t\t\t{}", e.replace(['\t', '\n'], " ")),
        }
    }
}
