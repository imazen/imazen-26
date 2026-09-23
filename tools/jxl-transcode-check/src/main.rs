//! Validate lossless JPEG -> JXL transcodes of imazen-26 JPEG sources.
//!
//! For each `id<TAB>path` line of the input list:
//!   1. transcode with jxl-encoder (JBRD reconstruction box, no pixel round trip);
//!   2. rebuild the JPEG from the JXL with zenjxl-decoder and compare sha256 with the
//!      original — the transcode's whole promise;
//!   3. decode the JXL as a plain reader would (no colour management, no gain map) and
//!      compare its pixels with zenjpeg's decode of the original in stored orientation;
//!   4. report what colour, orientation and HDR information each container exposes: the
//!      ICC profile (and whether the JXL carries the same bytes), the EXIF orientation
//!      against the JXL header's, bytes after the JPEG's EOI (where UltraHDR keeps its
//!      gain-map image), whether zenjpeg finds a gain map in the original, and whether
//!      the JXL exposes one (`jhgm`).
//!
//! Two builds share this file: `Cargo.toml` pins the published crates, `head/Cargo.toml`
//! pins committed revisions and enables the `head` feature (the only API difference is
//! `read_jpeg`'s signature).
//!
//! Usage: jxl-transcode-check <list.tsv> <out.tsv>
//! Writes one row per input; failures are recorded in the `error` column, never skipped.

#![forbid(unsafe_code)]

use std::borrow::Cow;
use std::fs;
use std::io::Write;
use std::time::Instant;

use sha2::{Digest, Sha256};
use zenjpeg::decoder::{Decoder, GainMapHandling};

/// Decoder memory ceiling for the pixel comparison. zenjpeg's default (512 MiB)
/// refuses the largest sources (~50 MP).
const ZENJPEG_MAX_MEMORY: u64 = 4 << 30;

fn sha(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|x| format!("{x:02x}"))
        .collect()
}

/// The marker segments before the first SOS: `(marker, payload)`.
fn header_segments(data: &[u8]) -> Vec<(u8, &[u8])> {
    let mut out = Vec::new();
    let mut pos = 2usize;
    while pos + 4 <= data.len() {
        if data[pos] != 0xFF {
            break;
        }
        let m = data[pos + 1];
        if m == 0xD8 || m == 0x01 || (0xD0..=0xD7).contains(&m) {
            pos += 2;
            continue;
        }
        if m == 0xDA || m == 0xD9 {
            break;
        }
        let len = u16::from_be_bytes([data[pos + 2], data[pos + 3]]) as usize;
        if len < 2 || pos + 2 + len > data.len() {
            break;
        }
        out.push((m, &data[pos + 4..pos + 2 + len]));
        pos += 2 + len;
    }
    out
}

/// The ICC payload of a JPEG: APP2 `ICC_PROFILE\0` chunks, in sequence order.
fn jpeg_icc(data: &[u8]) -> Option<Vec<u8>> {
    let mut chunks: Vec<(u8, &[u8])> = header_segments(data)
        .into_iter()
        .filter(|(m, seg)| *m == 0xE2 && seg.len() > 14 && &seg[..12] == b"ICC_PROFILE\0")
        .map(|(_, seg)| (seg[12], &seg[14..]))
        .collect();
    if chunks.is_empty() {
        return None;
    }
    chunks.sort_by_key(|c| c.0);
    Some(
        chunks
            .into_iter()
            .flat_map(|c| c.1.iter().copied())
            .collect(),
    )
}

/// EXIF orientation (tag 0x0112) from the first APP1 `Exif\0\0` segment; 0 when absent.
fn exif_orientation(data: &[u8]) -> u16 {
    header_segments(data)
        .into_iter()
        .find(|(m, seg)| *m == 0xE1 && seg.starts_with(b"Exif\0\0"))
        .and_then(|(_, seg)| tiff_orientation(&seg[6..]))
        .unwrap_or(0)
}

fn tiff_orientation(t: &[u8]) -> Option<u16> {
    let le = match t.get(0..2)? {
        [b'I', b'I'] => true,
        [b'M', b'M'] => false,
        _ => return None,
    };
    let u16_at = |o: usize| {
        t.get(o..o + 2).map(|b| {
            if le {
                u16::from_le_bytes([b[0], b[1]])
            } else {
                u16::from_be_bytes([b[0], b[1]])
            }
        })
    };
    let u32_at = |o: usize| {
        t.get(o..o + 4).map(|b| {
            let a = [b[0], b[1], b[2], b[3]];
            if le {
                u32::from_le_bytes(a)
            } else {
                u32::from_be_bytes(a)
            }
        })
    };
    let ifd = u32_at(4)? as usize;
    let n = u16_at(ifd)? as usize;
    (0..n).find_map(|k| {
        let e = ifd + 2 + 12 * k;
        (u16_at(e)? == 0x0112).then(|| u16_at(e + 8)).flatten()
    })
}

/// The profile's `desc` text (v2 `desc` or v4 `mluc`), for the report only.
fn icc_desc(icc: &[u8]) -> String {
    let rd = |o: usize| {
        icc.get(o..o + 4)
            .map(|b| u32::from_be_bytes([b[0], b[1], b[2], b[3]]) as usize)
    };
    let Some(n) = rd(128) else { return "?".into() };
    for k in 0..n.min(64) {
        let e = 132 + 12 * k;
        if icc.get(e..e + 4) != Some(b"desc") {
            continue;
        }
        let (Some(off), Some(sz)) = (rd(e + 4), rd(e + 8)) else {
            break;
        };
        let Some(t) = icc.get(off..off + sz) else {
            break;
        };
        if t.starts_with(b"desc") && t.len() >= 12 {
            let l = u32::from_be_bytes([t[8], t[9], t[10], t[11]]) as usize;
            if let Some(s) = t.get(12..12 + l.saturating_sub(1)) {
                return String::from_utf8_lossy(s).into_owned();
            }
        } else if t.starts_with(b"mluc") && t.len() >= 28 {
            let l = u32::from_be_bytes([t[20], t[21], t[22], t[23]]) as usize;
            let o = u32::from_be_bytes([t[24], t[25], t[26], t[27]]) as usize;
            if let Some(s) = t.get(o..o + l) {
                let u: Vec<u16> = s
                    .as_chunks::<2>()
                    .0
                    .iter()
                    .map(|c| u16::from_be_bytes(*c))
                    .collect();
                return String::from_utf16_lossy(&u);
            }
        }
    }
    "?".into()
}

/// Bytes after the first EOI that ends the primary image's entropy-coded data.
fn tail_len(data: &[u8]) -> usize {
    // Walk markers to SOS, then scan entropy-coded data for FFD9 (EOI).
    let mut pos = 2usize;
    while pos + 4 <= data.len() {
        if data[pos] != 0xFF {
            return 0;
        }
        let m = data[pos + 1];
        if m == 0xD8 || m == 0x01 || (0xD0..=0xD7).contains(&m) {
            pos += 2;
            continue;
        }
        let len = u16::from_be_bytes([data[pos + 2], data[pos + 3]]) as usize;
        pos += 2 + len;
        if m == 0xDA {
            // entropy-coded segment(s) follow, possibly with more SOS for progressive
            let mut i = pos;
            while i + 1 < data.len() {
                if data[i] == 0xFF {
                    let n = data[i + 1];
                    if n == 0xD9 {
                        return data.len() - (i + 2);
                    }
                    if n == 0x00 || (0xD0..=0xD7).contains(&n) {
                        i += 2;
                        continue;
                    }
                    // another marker segment (e.g. DHT/SOS between progressive scans)
                    if i + 4 <= data.len() {
                        let l = u16::from_be_bytes([data[i + 2], data[i + 3]]) as usize;
                        i += 2 + l;
                        continue;
                    }
                }
                i += 1;
            }
            return 0;
        }
    }
    0
}

/// Payload size of the JXL container's `jbrd` box (JPEG reconstruction data); 0 if absent.
fn jbrd_len(jxl: &[u8]) -> usize {
    let mut pos = 0usize;
    while pos + 8 <= jxl.len() {
        let size = u32::from_be_bytes([jxl[pos], jxl[pos + 1], jxl[pos + 2], jxl[pos + 3]]) as u64;
        let (header, total) = match size {
            0 => (8u64, (jxl.len() - pos) as u64),
            1 => match jxl.get(pos + 8..pos + 16) {
                Some(b) => (
                    16,
                    u64::from_be_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]]),
                ),
                None => return 0,
            },
            n => (8, n),
        };
        if total < header {
            return 0;
        }
        if &jxl[pos + 4..pos + 8] == b"jbrd" {
            return (total - header) as usize;
        }
        pos = pos.saturating_add(total as usize);
    }
    0
}

/// Interleaved 8-bit pixels to RGB: grey and grey+alpha are replicated, alpha dropped.
fn to_rgb(px: &[u8], w: usize, h: usize) -> Option<Vec<u8>> {
    let n = w * h;
    if n == 0 || !px.len().is_multiple_of(n) {
        return None;
    }
    match px.len() / n {
        1 => Some(px.iter().flat_map(|&v| [v, v, v]).collect()),
        2 => Some(
            px.as_chunks::<2>()
                .0
                .iter()
                .flat_map(|c| [c[0], c[0], c[0]])
                .collect(),
        ),
        3 => Some(px.to_vec()),
        4 => Some(
            px.as_chunks::<4>()
                .0
                .iter()
                .flat_map(|c| [c[0], c[1], c[2]])
                .collect(),
        ),
        _ => None,
    }
}

struct Row {
    cols: Vec<(&'static str, String)>,
}
impl Row {
    fn set(&mut self, k: &'static str, v: impl ToString) {
        self.cols.push((k, v.to_string()));
    }
}

const COLS: &[&str] = &[
    "id",
    "jpeg_bytes",
    "jxl_bytes",
    "ratio",
    "encode_ms",
    "jbrd_bytes",
    "recon_exact",
    "recon_len",
    "recon_first_diff",
    "recon_diff_ctx",
    "tail_bytes",
    "tail_is_jpeg",
    "icc_bytes",
    "icc_desc",
    "jxl_profile",
    "jxl_icc_equal",
    "exif_orientation",
    "jxl_orientation",
    "jpeg_gain_map",
    "jpeg_gain_map_bytes",
    "jxl_gain_map",
    "jxl_w",
    "jxl_h",
    "jpeg_w",
    "jpeg_h",
    "pixel_compare",
    "max_diff",
    "mean_diff",
    "pct_diff_gt2",
    "error",
];

/// Offset of the first differing byte, and the JPEG marker nearest before it.
fn first_diff(a: &[u8], b: &[u8]) -> (usize, String) {
    let n = a
        .iter()
        .zip(b.iter())
        .position(|(x, y)| x != y)
        .unwrap_or(a.len().min(b.len()));
    let mut m = n.min(a.len().saturating_sub(1));
    while m > 0 && !(a[m] == 0xFF && a.get(m + 1).is_some_and(|&c| c != 0x00 && c != 0xFF)) {
        m -= 1;
    }
    let marker = a
        .get(m + 1)
        .map_or(String::from("?"), |c| format!("FF{c:02X}@{m}"));
    (n, marker)
}

fn compare(a: &[u8], b: &[u8], r: &mut Row) {
    let mut max = 0u8;
    let mut sum = 0u64;
    let mut gt2 = 0u64;
    for (x, y) in a.iter().zip(b.iter()) {
        let d = x.abs_diff(*y);
        max = max.max(d);
        sum += d as u64;
        gt2 += (d > 2) as u64;
    }
    r.set("pixel_compare", "stored");
    r.set("max_diff", max);
    r.set("mean_diff", format!("{:.4}", sum as f64 / a.len() as f64));
    r.set(
        "pct_diff_gt2",
        format!("{:.4}", 100.0 * gt2 as f64 / a.len() as f64),
    );
}

/// Parse and transcode. `read_jpeg` gained two optional arguments after 0.3.1.
fn transcode(orig: &[u8]) -> Result<Vec<u8>, String> {
    #[cfg(feature = "head")]
    let parsed = jxl_encoder::jpeg::read_jpeg(orig, None, None);
    #[cfg(not(feature = "head"))]
    let parsed = jxl_encoder::jpeg::read_jpeg(orig);
    let d = parsed.map_err(|e| format!("parse: {e:?}"))?;
    jxl_encoder::jpeg::encode_jpeg_to_jxl_container(&d).map_err(|e| format!("encode: {e:?}"))
}

fn check(id: &str, path: &str) -> Row {
    let mut r = Row {
        cols: vec![("id", id.to_string())],
    };
    let orig = match fs::read(path) {
        Ok(b) => b,
        Err(e) => {
            r.set("error", format!("read: {e}"));
            return r;
        }
    };
    r.set("jpeg_bytes", orig.len());
    let tail = tail_len(&orig);
    r.set("tail_bytes", tail);
    r.set(
        "tail_is_jpeg",
        (tail >= 2 && orig[orig.len() - tail..].starts_with(&[0xFF, 0xD8])) as u8,
    );
    let icc = jpeg_icc(&orig);
    r.set("icc_bytes", icc.as_ref().map_or(0, |v| v.len()));
    r.set(
        "icc_desc",
        icc.as_deref().map_or_else(|| "-".to_string(), icc_desc),
    );
    r.set("exif_orientation", exif_orientation(&orig));

    // 1. transcode
    let t0 = Instant::now();
    let jxl = match transcode(&orig) {
        Ok(j) => j,
        Err(e) => {
            r.set("error", e);
            return r;
        }
    };
    r.set("encode_ms", t0.elapsed().as_millis());
    r.set("jxl_bytes", jxl.len());
    r.set(
        "ratio",
        format!("{:.4}", jxl.len() as f64 / orig.len() as f64),
    );

    // 2. byte-exact reconstruction. `reconstruct_jpeg` returns `Ok(None)` both when
    // there is no jbrd box and when rebuilding the JPEG from one fails, so the box is
    // looked up separately to tell the two apart.
    let jbrd = jbrd_len(&jxl);
    r.set("jbrd_bytes", jbrd);
    match zenjxl_decoder::reconstruct_jpeg(&jxl) {
        Ok(Some(rec)) => {
            let exact = sha(&rec) == sha(&orig);
            r.set("recon_exact", exact as u8);
            r.set("recon_len", rec.len());
            if !exact {
                let (n, ctx) = first_diff(&orig, &rec);
                r.set("recon_first_diff", n);
                r.set("recon_diff_ctx", ctx);
            }
        }
        Ok(None) if jbrd > 0 => r.set("recon_exact", "rebuild-failed"),
        Ok(None) => r.set("recon_exact", "no-jbrd"),
        Err(e) => r.set("recon_exact", format!("err:{e:?}")),
    }

    // 3/4. plain decode of the JXL: pixels, profile, orientation, gain map
    let img = match zenjxl_decoder::decode(&jxl) {
        Ok(i) => i,
        Err(e) => {
            r.set("error", format!("jxl decode: {e:?}"));
            return r;
        }
    };
    r.set("jxl_w", img.width);
    r.set("jxl_h", img.height);
    let prof = match &img.embedded_profile {
        zenjxl_decoder::api::JxlColorProfile::Icc(v) => {
            r.set(
                "jxl_icc_equal",
                icc.as_deref().map_or(0, |o| (o == v.as_slice()) as u8),
            );
            format!("icc:{}B", v.len())
        }
        other => {
            let eq = match (other.try_as_icc(), icc.as_deref()) {
                (Some(Cow::Borrowed(a)), Some(o)) => (a.as_slice() == o) as u8,
                (Some(Cow::Owned(a)), Some(o)) => (a.as_slice() == o) as u8,
                _ => 0,
            };
            r.set("jxl_icc_equal", eq);
            format!("{other:?}")
        }
    };
    r.set("jxl_profile", prof);
    r.set("jxl_gain_map", img.gain_map.is_some() as u8);
    r.set("jxl_orientation", format!("{:?}", img.info.orientation));

    // zenjpeg decode of the original in stored orientation — the pixels the JXL
    // codestream holds — with any UltraHDR gain map kept as raw bytes.
    let decoder = Decoder::new()
        .auto_orient(false)
        .max_memory(ZENJPEG_MAX_MEMORY)
        .gain_map(GainMapHandling::PreserveRaw);
    match decoder.decode(&orig, enough::Unstoppable) {
        Ok(d) => {
            r.set("jpeg_gain_map", d.gain_map.is_some() as u8);
            r.set(
                "jpeg_gain_map_bytes",
                d.gain_map.as_ref().map_or(0, |g| g.jpeg.len()),
            );
            r.set("jpeg_w", d.width);
            r.set("jpeg_h", d.height);
            let (w, h) = (d.width as usize, d.height as usize);
            if (w, h) != (img.width, img.height) {
                r.set("pixel_compare", "dims-differ");
            } else {
                match (
                    d.pixels_u8().and_then(|p| to_rgb(p, w, h)),
                    to_rgb(&img.data, w, h),
                ) {
                    (Some(a), Some(b)) if a.len() == b.len() => compare(&a, &b, &mut r),
                    _ => r.set("pixel_compare", "layout-unsupported"),
                }
            }
        }
        Err(e) => r.set("error", format!("zenjpeg decode: {e:?}")),
    }
    r
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: jxl-transcode-check <list.tsv: id<TAB>path> <out.tsv>");
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
        // Last write wins per column; tabs and newlines in values (error text) would
        // break the TSV, so they become spaces.
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
