//! Check lossless JPEG transforms on corpus JPEGs, at the coefficient and pixel level.
//!
//! For each `id<TAB>path` line:
//!   1. **Sequential re-encode** — `zenjpeg::lossless::transform(None)`: the same DCT
//!      coefficients written as a baseline sequential JPEG with optimized Huffman tables.
//!      Checks the coefficients are identical, zenjpeg decodes both to identical pixels,
//!      and the JPEG-in-JXL transcode of the sequential file rebuilds it byte-exact.
//!   2. **Orientation** (EXIF orientation ≠ 1 only) — the coefficient-domain rotation
//!      zenjpeg's lossless module performs. With `RejectPartialBlocks` it succeeds only
//!      when the edge that moves to the top/left is MCU-aligned ("perfect"); otherwise the
//!      `TrimPartialBlocks` result is measured instead. The decoded result is compared
//!      with the pixel-rotated decode of the original — through zenjpeg, and through the
//!      JPEG-in-JXL transcode and zenjxl-decoder — overall, within 16 px of an edge, and
//!      in the interior.
//!
//! Usage: jpeg-lossless-check <list.tsv> <out.tsv>
//! Failures go into the `error` column; no input is skipped.

#![forbid(unsafe_code)]

use std::fs;
use std::io::Write;

use sha2::{Digest, Sha256};
use zenjpeg::decoder::Decoder;
use zenjpeg::lossless::{
    EdgeHandling, LosslessTransform, TransformConfig, parse_exif_orientation, transform,
};

const MAX_MEMORY: u64 = 4 << 30;
const BORDER: usize = 16;

const COLS: &[&str] = &[
    "id",
    "bytes",
    "progressive",
    "orientation",
    "seq_bytes",
    "seq_coeff_equal",
    "seq_pixel_maxdiff",
    "seq_jxl_bytes",
    "seq_jxl_rebuild_exact",
    "seq_vs_orig_jxl_pixels_equal",
    "orient_check",
    "rot_mode",
    "rot_w",
    "rot_h",
    "rot_lost_cols",
    "rot_lost_rows",
    "rot_zenjpeg_maxdiff",
    "rot_zenjpeg_border_maxdiff",
    "rot_zenjpeg_interior_maxdiff",
    "rot_zenjpeg_pct_diff",
    "rot_jxl_rebuild_exact",
    "rot_jxl_maxdiff",
    "rot_jxl_border_maxdiff",
    "rot_jxl_interior_maxdiff",
    "quant_tables_symmetric",
    "fixq_zenjpeg_maxdiff",
    "fixq_jxl_maxdiff",
    "fixq_jxl_border_maxdiff",
    "fixq_jxl_interior_maxdiff",
    "fixq_zenjpeg_interior_maxdiff",
    "error",
];

struct Row {
    cols: Vec<(&'static str, String)>,
}
impl Row {
    fn set(&mut self, k: &'static str, v: impl ToString) {
        self.cols.push((k, v.to_string()));
    }
}

fn sha(b: &[u8]) -> Vec<u8> {
    Sha256::digest(b).to_vec()
}

/// An 8-bit interleaved image.
struct Img {
    w: usize,
    h: usize,
    c: usize,
    px: Vec<u8>,
}

fn zenjpeg_decode(data: &[u8], auto_orient: bool) -> Result<Img, String> {
    let d = Decoder::new()
        .auto_orient(auto_orient)
        .max_memory(MAX_MEMORY)
        .decode(data, enough::Unstoppable)
        .map_err(|e| format!("zenjpeg decode: {e:?}"))?;
    let (w, h) = (d.width as usize, d.height as usize);
    let px = d.pixels_u8().ok_or("zenjpeg: no u8 pixels")?.to_vec();
    let c = px.len() / (w * h).max(1);
    Ok(Img { w, h, c, px })
}

fn jxl_decode(jxl: &[u8]) -> Result<Img, String> {
    let i = zenjxl_decoder::decode(jxl).map_err(|e| format!("jxl decode: {e:?}"))?;
    let c = i.data.len() / (i.width * i.height).max(1);
    Ok(Img {
        w: i.width,
        h: i.height,
        c,
        px: i.data,
    })
}

fn transcode(jpeg: &[u8]) -> Result<Vec<u8>, String> {
    let d = jxl_encoder::jpeg::read_jpeg(jpeg, None, None).map_err(|e| format!("parse: {e:?}"))?;
    jxl_encoder::jpeg::encode_jpeg_to_jxl_container(&d).map_err(|e| format!("encode: {e:?}"))
}

/// Rebuild the JPEG from a JXL and compare with `expected`: "1", "0", "none" or an error.
fn rebuild_exact(jxl: &[u8], expected: &[u8]) -> String {
    match zenjxl_decoder::reconstruct_jpeg(jxl) {
        Ok(Some(r)) => ((sha(&r) == sha(expected)) as u8).to_string(),
        Ok(None) => "none".into(),
        Err(e) => format!("err:{e:?}"),
    }
}

/// Display-orient an image by EXIF orientation value (1–8).
fn orient(src: &Img, o: u8) -> Img {
    let (w, h, c) = (src.w, src.h, src.c);
    let swaps = o >= 5;
    let (dw, dh) = if swaps { (h, w) } else { (w, h) };
    let mut px = vec![0u8; dw * dh * c];
    for y in 0..dh {
        for x in 0..dw {
            let (sx, sy) = match o {
                2 => (w - 1 - x, y),
                3 => (w - 1 - x, h - 1 - y),
                4 => (x, h - 1 - y),
                5 => (y, x),
                6 => (y, h - 1 - x),
                7 => (w - 1 - y, h - 1 - x),
                8 => (w - 1 - y, x),
                _ => (x, y),
            };
            let s = (sy * w + sx) * c;
            let d = (y * dw + x) * c;
            px[d..d + c].copy_from_slice(&src.px[s..s + c]);
        }
    }
    Img {
        w: dw,
        h: dh,
        c,
        px,
    }
}

struct Diff {
    max: u8,
    border_max: u8,
    interior_max: u8,
    pct: f64,
}

/// Compare `a` with the region of `b` whose top-left is at (`ox`, `oy`).
fn diff(a: &Img, b: &Img, ox: usize, oy: usize) -> Result<Diff, String> {
    if a.c != b.c || ox + a.w > b.w || oy + a.h > b.h {
        return Err(format!(
            "layout {}x{}x{} vs {}x{}x{} at +{ox}+{oy}",
            a.w, a.h, a.c, b.w, b.h, b.c
        ));
    }
    let (mut max, mut bmax, mut imax, mut n) = (0u8, 0u8, 0u8, 0u64);
    for y in 0..a.h {
        for x in 0..a.w {
            let border = x < BORDER || y < BORDER || x + BORDER >= a.w || y + BORDER >= a.h;
            for k in 0..a.c {
                let d = a.px[(y * a.w + x) * a.c + k]
                    .abs_diff(b.px[((y + oy) * b.w + x + ox) * b.c + k]);
                if d > 0 {
                    n += 1;
                }
                max = max.max(d);
                if border {
                    bmax = bmax.max(d);
                } else {
                    imax = imax.max(d);
                }
            }
        }
    }
    let pct = 100.0 * n as f64 / (a.w * a.h * a.c).max(1) as f64;
    Ok(Diff {
        max,
        border_max: bmax,
        interior_max: imax,
        pct,
    })
}

/// Where differences > `thr` fall, for diagnosing a transform (set `DIAG=1`).
fn diag(label: &str, a: &Img, b: &Img, ox: usize, oy: usize, thr: u8) {
    let mut per_ch = vec![0u8; a.c];
    let mut hist = [0u64; 9]; // |d| buckets: 0,1,2,3-4,5-8,9-16,17-32,33-64,>64
    let mut phase = vec![0u64; 16 * 16];
    let (mut n_big, mut bx0, mut bx1, mut by0, mut by1) = (0u64, usize::MAX, 0, usize::MAX, 0);
    for y in 0..a.h {
        for x in 0..a.w {
            for (k, ch_max) in per_ch.iter_mut().enumerate() {
                let d = a.px[(y * a.w + x) * a.c + k]
                    .abs_diff(b.px[((y + oy) * b.w + x + ox) * b.c + k]);
                *ch_max = (*ch_max).max(d);
                let bi = match d {
                    0 => 0,
                    1 => 1,
                    2 => 2,
                    3..=4 => 3,
                    5..=8 => 4,
                    9..=16 => 5,
                    17..=32 => 6,
                    33..=64 => 7,
                    _ => 8,
                };
                hist[bi] += 1;
                if d > thr {
                    n_big += 1;
                    phase[(y % 16) * 16 + x % 16] += 1;
                    bx0 = bx0.min(x / 16);
                    bx1 = bx1.max(x / 16);
                    by0 = by0.min(y / 16);
                    by1 = by1.max(y / 16);
                }
            }
        }
    }
    eprintln!(
        "DIAG {label}: per-channel max {per_ch:?}; |d| hist [0,1,2,3-4,5-8,9-16,17-32,33-64,>64] = {hist:?}"
    );
    eprintln!(
        "DIAG {label}: {n_big} samples > {thr}; MCU cols {bx0}..={bx1} rows {by0}..={by1} of {}x{}",
        a.w.div_ceil(16),
        a.h.div_ceil(16)
    );
    let rows: Vec<u64> = (0..16)
        .map(|py| (0..16).map(|px| phase[py * 16 + px]).sum())
        .collect();
    let cols: Vec<u64> = (0..16)
        .map(|px| (0..16).map(|py| phase[py * 16 + px]).sum())
        .collect();
    eprintln!("DIAG {label}: by y%16 {rows:?}");
    eprintln!("DIAG {label}: by x%16 {cols:?}");
}

/// JPEG zigzag index → natural (row-major) index.
const ZIGZAG: [usize; 64] = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20,
    13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59,
    52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
];

/// Rewrite every DQT table before the first SOS with its transpose, in place. Returns
/// whether all tables were already symmetric. Used to test that transposing the tables
/// is what a dimension-swapping lossless transform is missing.
fn transpose_dqt(jpeg: &mut [u8]) -> bool {
    let mut symmetric = true;
    let mut pos = 2usize;
    while pos + 4 <= jpeg.len() && jpeg[pos] == 0xFF {
        let m = jpeg[pos + 1];
        if m == 0xD8 || m == 0x01 || (0xD0..=0xD7).contains(&m) {
            pos += 2;
            continue;
        }
        let len = u16::from_be_bytes([jpeg[pos + 2], jpeg[pos + 3]]) as usize;
        if m == 0xDA || pos + 2 + len > jpeg.len() {
            break;
        }
        if m == 0xDB {
            let (mut q, end) = (pos + 4, pos + 2 + len);
            while q < end {
                let wide = jpeg[q] >> 4 != 0;
                q += 1;
                let sz = if wide { 2 } else { 1 };
                let read = |b: &[u8], k: usize| {
                    if wide {
                        u16::from_be_bytes([b[q + 2 * k], b[q + 2 * k + 1]])
                    } else {
                        u16::from(b[q + k])
                    }
                };
                let mut nat = [0u16; 64];
                for k in 0..64 {
                    nat[ZIGZAG[k]] = read(jpeg, k);
                }
                for k in 0..64 {
                    let (r, c) = (ZIGZAG[k] / 8, ZIGZAG[k] % 8);
                    let v = nat[c * 8 + r];
                    symmetric &= v == nat[r * 8 + c];
                    if wide {
                        jpeg[q + 2 * k..q + 2 * k + 2].copy_from_slice(&v.to_be_bytes());
                    } else {
                        jpeg[q + k] = v as u8;
                    }
                }
                q += 64 * sz;
            }
        }
        pos += 2 + len;
    }
    symmetric
}

fn coeffs_equal(a: &[u8], b: &[u8]) -> Result<bool, String> {
    let dc = zenjpeg::decoder::DecodeConfig::new();
    let x = dc
        .decode_coefficients(a, enough::Unstoppable)
        .map_err(|e| format!("coeffs: {e:?}"))?;
    let y = dc
        .decode_coefficients(b, enough::Unstoppable)
        .map_err(|e| format!("coeffs: {e:?}"))?;
    Ok(x.width == y.width
        && x.height == y.height
        && x.quant_tables == y.quant_tables
        && x.components.len() == y.components.len()
        && x.components.iter().zip(&y.components).all(|(p, q)| {
            p.coeffs == q.coeffs
                && (p.blocks_wide, p.blocks_high, p.h_samp, p.v_samp)
                    == (q.blocks_wide, q.blocks_high, q.h_samp, q.v_samp)
        }))
}

fn check(id: &str, path: &str) -> Row {
    let mut r = Row {
        cols: vec![("id", id.to_string())],
    };
    if let Err(e) = run(path, &mut r) {
        r.set("error", e);
    }
    r
}

fn run(path: &str, r: &mut Row) -> Result<(), String> {
    let orig = fs::read(path).map_err(|e| format!("read: {e}"))?;
    r.set("bytes", orig.len());
    let info = Decoder::new()
        .read_info(&orig)
        .map_err(|e| format!("info: {e:?}"))?;
    r.set("progressive", format!("{:?}", info.mode));
    let o = info
        .exif
        .as_deref()
        .and_then(parse_exif_orientation)
        .unwrap_or(1);
    r.set("orientation", o);

    // 1. sequential re-encode of the same coefficients
    let none = TransformConfig {
        transform: LosslessTransform::None,
        edge_handling: EdgeHandling::RejectPartialBlocks,
    };
    let seq =
        transform(&orig, &none, enough::Unstoppable).map_err(|e| format!("sequential: {e:?}"))?;
    r.set("seq_bytes", seq.len());
    r.set("seq_coeff_equal", coeffs_equal(&orig, &seq)? as u8);
    let (po, ps) = (zenjpeg_decode(&orig, false)?, zenjpeg_decode(&seq, false)?);
    r.set("seq_pixel_maxdiff", diff(&ps, &po, 0, 0)?.max);
    let (jo, js) = (transcode(&orig)?, transcode(&seq)?);
    r.set("seq_jxl_bytes", js.len());
    r.set("seq_jxl_rebuild_exact", rebuild_exact(&js, &seq));
    let (xo, xs) = (jxl_decode(&jo)?, jxl_decode(&js)?);
    r.set(
        "seq_vs_orig_jxl_pixels_equal",
        (xo.w == xs.w && xo.h == xs.h && xo.px == xs.px) as u8,
    );

    // ALL_TRANSFORMS=1: apply every EXIF orientation's transform (needs a file aligned
    // in both dimensions) and compare with the matching pixel orientation.
    if std::env::var_os("ALL_TRANSFORMS").is_some() {
        for t_o in 2u8..=8 {
            let t = LosslessTransform::from_exif_orientation(t_o).ok_or("no transform")?;
            let cfg = TransformConfig {
                transform: t,
                edge_handling: EdgeHandling::RejectPartialBlocks,
            };
            match transform(&orig, &cfg, enough::Unstoppable) {
                Ok(j) => {
                    let dz = diff(&zenjpeg_decode(&j, false)?, &orient(&po, t_o), 0, 0)?;
                    let dj = diff(&jxl_decode(&transcode(&j)?)?, &orient(&xo, t_o), 0, 0)?;
                    eprintln!(
                        "ALL exif {t_o} {t:?}: zenjpeg max {} ({:.2}% differ), jxl max {} ({:.2}% differ)",
                        dz.max, dz.pct, dj.max, dj.pct
                    );
                }
                Err(e) => eprintln!("ALL exif {t_o} {t:?}: {e:?}"),
            }
        }
    }
    if o == 1 {
        return Ok(());
    }
    // 2. orientation: coefficient-domain rotation vs pixel rotation
    let t = LosslessTransform::from_exif_orientation(o).ok_or("no transform for orientation")?;
    let reference = orient(&po, o);
    // our index-map rotation must agree with zenjpeg's own auto-orient decode
    let auto = zenjpeg_decode(&orig, true)?;
    r.set(
        "orient_check",
        (auto.w == reference.w && auto.h == reference.h && auto.px == reference.px) as u8,
    );
    let perfect = transform(
        &orig,
        &TransformConfig {
            transform: t,
            edge_handling: EdgeHandling::RejectPartialBlocks,
        },
        enough::Unstoppable,
    );
    let (rot, mode) = match perfect {
        Ok(j) => (j, "perfect"),
        Err(_) => (
            transform(
                &orig,
                &TransformConfig {
                    transform: t,
                    edge_handling: EdgeHandling::TrimPartialBlocks,
                },
                enough::Unstoppable,
            )
            .map_err(|e| format!("trim: {e:?}"))?,
            "trim",
        ),
    };
    r.set("rot_mode", mode);
    let pr = zenjpeg_decode(&rot, false)?;
    r.set("rot_w", pr.w);
    r.set("rot_h", pr.h);
    // what trimming removed sits on the leading (top/left) edge of the display image
    let (ox, oy) = (reference.w - pr.w, reference.h - pr.h);
    r.set("rot_lost_cols", ox);
    r.set("rot_lost_rows", oy);
    if std::env::var_os("DIAG").is_some() {
        diag("zenjpeg", &pr, &reference, ox, oy, 8);
    }
    let d = diff(&pr, &reference, ox, oy)?;
    r.set("rot_zenjpeg_maxdiff", d.max);
    r.set("rot_zenjpeg_border_maxdiff", d.border_max);
    r.set("rot_zenjpeg_interior_maxdiff", d.interior_max);
    r.set("rot_zenjpeg_pct_diff", format!("{:.4}", d.pct));
    // the same through JPEG-in-JXL: transcode of the rotated file vs rotated decode of the original's transcode
    let jr = transcode(&rot)?;
    r.set("rot_jxl_rebuild_exact", rebuild_exact(&jr, &rot));
    let (xr, xref) = (jxl_decode(&jr)?, orient(&xo, o));
    if std::env::var_os("DIAG").is_some() {
        diag("jxl", &xr, &xref, ox, oy, 8);
    }
    let dj = diff(&xr, &xref, ox, oy)?;
    r.set("rot_jxl_maxdiff", dj.max);
    r.set("rot_jxl_border_maxdiff", dj.border_max);
    r.set("rot_jxl_interior_maxdiff", dj.interior_max);
    if t.swaps_dimensions() {
        let mut fixed = rot.clone();
        r.set("quant_tables_symmetric", transpose_dqt(&mut fixed) as u8);
        let fz = diff(&zenjpeg_decode(&fixed, false)?, &reference, ox, oy)?;
        let fj = diff(&jxl_decode(&transcode(&fixed)?)?, &xref, ox, oy)?;
        r.set("fixq_zenjpeg_maxdiff", fz.max);
        r.set("fixq_jxl_maxdiff", fj.max);
        r.set("fixq_jxl_border_maxdiff", fj.border_max);
        r.set("fixq_jxl_interior_maxdiff", fj.interior_max);
        r.set("fixq_zenjpeg_interior_maxdiff", fz.interior_max);
    }
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: jpeg-lossless-check <list.tsv: id<TAB>path> <out.tsv>");
        std::process::exit(2);
    }
    let list = fs::read_to_string(&args[1]).expect("read list");
    let mut out = fs::File::create(&args[2]).expect("create out");
    writeln!(out, "{}", COLS.join("\t")).unwrap();
    let lines: Vec<&str> = list.lines().filter(|l| !l.trim().is_empty()).collect();
    for (n, line) in lines.iter().enumerate() {
        let mut it = line.splitn(2, '\t');
        let (id, path) = (it.next().unwrap_or(""), it.next().unwrap_or(""));
        let row = check(id, path);
        let vals: Vec<String> = COLS
            .iter()
            .map(|c| {
                row.cols
                    .iter()
                    .rev()
                    .find(|(k, _)| k == c)
                    .map_or(String::new(), |(_, v)| v.replace(['\t', '\n', '\r'], " "))
            })
            .collect();
        writeln!(out, "{}", vals.join("\t")).unwrap();
        eprintln!(
            "[{}/{}] {} {}",
            n + 1,
            lines.len(),
            id,
            vals[COLS.len() - 1]
        );
    }
}
