//! The JPEG XL layers (EXPORT-PLAN.md, "JPEG XL"): `jxl-p3` and `jxl-srgb`, the twins of the
//! PNG layers, as `<layer>/<stem>_<W>x<H>.jxl`.
//!
//! - Sources that aren't JPEG: lossless JXL of exactly the pixels the PNG twin holds (`png-p3`
//!   code values; `png-srgb` converted), the colour in JXL's own encoding for sRGB and Display
//!   P3 and as the ICC profile for Adobe RGB, and the provenance JSON as XMP (one
//!   `imazen26:provenance` property in an `xml ` box).
//! - JPEG sources: JPEG-in-JXL, the JPEG's DCT coefficients plus `jbrd`, which rebuilds the
//!   original byte for byte. No provenance box: the JPEG's own XMP lives in that box for the
//!   rebuild (owner question 5, option A pending). In `jxl-srgb`, wide-gamut JPEGs need a
//!   colour conversion, so they are lossless renders of the `png-srgb` pixels instead.
//! - A JPEG whose reconstruction data can't be encoded (the 12 progressive Unsplash files:
//!   EOB-run counts beyond `jbrd`'s range) becomes a bare JXL codestream of the same
//!   coefficients, without reconstruction data (owner question 2, option A pending).
//! - Every file is decoded again: a lossless file must give the twin's pixel hash, its colour
//!   and its XMP; a JPEG-in-JXL file must rebuild the original's sha256. For both JPEG kinds the
//!   report gives the largest difference between the JXL decode and zenjpeg's decode of the
//!   original (displayed orientation), for information.

use std::fs;
use std::path::Path;
use std::sync::OnceLock;

use sha2::{Digest, Sha256};
use zencodec::{Metadata, OrientationHint};
use zencodecs::{DecodeRequest, EncodeRequest, ImageFormat, Limits};
use zenpixels::{PixelDescriptor, PixelSlice};

use super::{Colour, Pixels, Row, Source, code_values, hex, load, orient_pixels, to_srgb};

/// JPEG XL effort (`--effort`), set once before the workers start.
pub(crate) static EFFORT: OnceLock<u8> = OnceLock::new();

/// The report columns of `jxl`.
pub(crate) const JXL_HEADER: &str = "id\tlayer\tpath\twidth\theight\tkind\tcolour\tbytes\tsha256\tpixels_sha256\tjpeg_sha256\tjpeg_pixel_max_diff\tjhgm\terror";

/// Namespace of the provenance property in the XMP packet.
const XMP_NS: &str = "https://github.com/imazen/imazen-26#";

/// The provenance JSON as a minimal XMP packet.
fn provenance_xmp(json: &str) -> Vec<u8> {
    let text = json
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;");
    format!(
        "<?xpacket begin=\"\u{feff}\" id=\"W5M0MpCehiHzreSzNTczkc9d\"?>\n\
         <x:xmpmeta xmlns:x=\"adobe:ns:meta/\"><rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\
         <rdf:Description rdf:about=\"\" xmlns:imazen26=\"{XMP_NS}\"><imazen26:provenance>{text}</imazen26:provenance>\
         </rdf:Description></rdf:RDF></x:xmpmeta>\n<?xpacket end=\"r\"?>"
    )
    .into_bytes()
}

fn limits() -> Limits {
    Limits::none()
        .with_max_pixels(400_000_000)
        .with_max_memory(12 << 30)
}

/// Lossless JXL of 8-bit pixels with their colour and the provenance XMP.
fn encode_lossless(
    px: &Pixels,
    w: usize,
    h: usize,
    colour: Colour,
    icc: Option<&[u8]>,
    xmp: &[u8],
    effort: u8,
) -> Result<Vec<u8>, String> {
    let (bytes, base): (&[u8], PixelDescriptor) = match px {
        Pixels::Gray(p) => (p, PixelDescriptor::GRAY8_SRGB),
        Pixels::Rgb(p) => (p, PixelDescriptor::RGB8_SRGB),
        Pixels::Rgba(p) => (p, PixelDescriptor::RGBA8_SRGB),
    };
    // The code values go in labelled sRGB, so nothing on the way converts them; the colour
    // they are in is stated in the metadata, which zenjxl turns into the codestream's colour
    // encoding: the enum for sRGB and Display P3 (CICP 1/13, 12/13), the ICC for Adobe RGB.
    let slice = PixelSlice::new(bytes, w as u32, h as u32, w * base.bytes_per_pixel(), base)
        .map_err(|e| format!("pixel slice: {e:?}"))?;
    let mut meta = Metadata::default().with_xmp(xmp.to_vec());
    meta = match colour {
        Colour::Srgb | Colour::AssumedSrgb => meta.with_cicp(zencodec::Cicp::new(1, 13, 0, true)),
        Colour::DisplayP3 => meta.with_cicp(zencodec::Cicp::new(12, 13, 0, true)),
        Colour::AdobeRgb => meta.with_icc(icc.ok_or("Adobe RGB without its profile")?.to_vec()),
    };
    let out = EncodeRequest::new(ImageFormat::Jxl)
        .with_lossless(true)
        .with_effort(u32::from(effort))
        .with_metadata(meta)
        .encode(slice, matches!(px, Pixels::Rgba(_)))
        .map_err(|e| format!("jxl encode: {e}"))?;
    Ok(out.into_vec())
}

/// Decode a JXL in displayed orientation: its code values, size and metadata.
#[allow(clippy::type_complexity)]
fn decode(
    jxl: &[u8],
) -> Result<(Pixels, (usize, usize), Metadata, Option<zencodec::Cicp>), String> {
    let limits = limits();
    let out = DecodeRequest::new(jxl)
        .with_limits(&limits)
        .with_orientation(OrientationHint::Correct)
        .decode_full_frame()
        .map_err(|e| format!("jxl decode: {e}"))?;
    let meta = out.metadata().clone();
    let cicp = out.info().source_color.cicp;
    // zencodecs' JXL decode reports the header orientation instead of applying it.
    let orientation = out.info().orientation;
    let buf = out.into_buffer();
    let (w, h) = (buf.width() as usize, buf.height() as usize);
    let (px, _) = code_values(buf)?;
    let (px, w, h) = orient_pixels(px, w, h, orientation);
    Ok((px, (w, h), meta, cicp))
}

/// The colour a decoded lossless file must state.
fn check_colour(
    colour: Colour,
    meta: &Metadata,
    cicp: Option<zencodec::Cicp>,
    icc: Option<&[u8]>,
) -> Result<(), String> {
    let want = match colour {
        Colour::Srgb | Colour::AssumedSrgb => Some((1, 13)),
        Colour::DisplayP3 => Some((12, 13)),
        Colour::AdobeRgb => None,
    };
    match want {
        Some((p, t)) => match cicp {
            Some(c) if c.color_primaries == p && c.transfer_characteristics == t => Ok(()),
            other => match meta
                .icc_profile
                .as_deref()
                .and_then(zenpixels::icc::identify_common)
            {
                Some(id)
                    if id.primaries == colour.primaries() && id.transfer == colour.transfer() =>
                {
                    Ok(())
                }
                _ => Err(format!("decoded colour {other:?}, want CICP {p}/{t}")),
            },
        },
        None => {
            if meta.icc_profile.as_deref() == icc {
                Ok(())
            } else {
                Err("Adobe RGB profile did not survive".into())
            }
        }
    }
}

/// Largest per-channel difference between two equally sized pixel sets (RGBA view).
fn max_diff(a: &Pixels, b: &Pixels) -> Result<u8, String> {
    let (x, y) = (a.rgba(), b.rgba());
    if x.len() != y.len() {
        return Err(format!(
            "decoded size differs ({} vs {} bytes)",
            x.len(),
            y.len()
        ));
    }
    Ok(x.iter()
        .zip(&y)
        .map(|(p, q)| p.abs_diff(*q))
        .max()
        .unwrap_or(0))
}

/// JPEG-in-JXL with reconstruction data, or the bare codestream when `jbrd` can't hold it.
fn jpeg_in_jxl(data: &[u8], effort: u8) -> Result<(Vec<u8>, &'static str), String> {
    match zencodecs::transcode_jpeg_to_jxl_lossless(data, effort) {
        Ok(t) => Ok((t.data, "jpeg-in-jxl")),
        Err(e)
            if e.to_string()
                .contains("JPEG reconstruction data cannot carry") =>
        {
            let cs = zenjxl::LosslessConfig::new()
                .with_effort(effort)
                .encode_jpeg_transcode_codestream(data)
                .map_err(|e| format!("jpeg codestream transcode: {e}"))?;
            Ok((cs, "jpeg-in-jxl-codestream"))
        }
        Err(e) => Err(format!("jpeg transcode: {e}")),
    }
}

/// Whether a JXL container holds a box of this type at its top level.
fn has_box(jxl: &[u8], ty: &[u8; 4]) -> bool {
    let mut pos = 0usize;
    while pos + 8 <= jxl.len() {
        let size = u32::from_be_bytes(jxl[pos..pos + 4].try_into().unwrap()) as usize;
        if &jxl[pos + 4..pos + 8] == ty {
            return true;
        }
        let size = match size {
            0 => return false,
            1 if pos + 16 <= jxl.len() => {
                u64::from_be_bytes(jxl[pos + 8..pos + 16].try_into().unwrap()) as usize
            }
            n => n,
        };
        pos = pos.saturating_add(size.max(8));
    }
    false
}

/// The `jhgm` payload of a gain-map form: ISO 21496-1 metadata and the gain map as a
/// lossless JXL codestream.
fn jhgm_payload(form: &crate::hdr::JhgmForm, effort: u8) -> Result<Vec<u8>, String> {
    if form.map.channels != 1 {
        return Err("gain-map form with more than one channel".into());
    }
    let gray: Vec<rgb::Gray<u8>> = form.map.data.iter().map(|&v| rgb::Gray::new(v)).collect();
    let img = imgref::Img::new(&gray[..], form.map.width as usize, form.map.height as usize);
    let codestream =
        zenjxl::encode_gray8_lossless(img, &zenjxl::LosslessConfig::new().with_effort(effort))
            .map_err(|e| format!("gain map encode: {e}"))?;
    let metadata =
        ultrahdr_core::serialize_iso21496_fmt(&form.meta, ultrahdr_core::Iso21496Format::JxlJhgm);
    Ok(zenjxl::GainMapBundle {
        metadata,
        color_encoding: None,
        alt_icc_compressed: None,
        gain_map_codestream: codestream,
    }
    .serialize())
}

/// Largest |log2| ratio between two linear renditions, over values above 1e-3 in both.
fn worst_stops(a: &[f64], b: &[f64]) -> f64 {
    a.iter()
        .zip(b)
        .filter(|(x, y)| **x > 1e-3 && **y > 1e-3)
        .map(|(x, y)| (x / y).log2().abs())
        .fold(0.0, f64::max)
}

/// Read a gain-map form back and compare the HDR it gives with the source's own.
fn check_jhgm(
    jxl: &[u8],
    px: &Pixels,
    w: usize,
    h: usize,
    form: &crate::hdr::JhgmForm,
) -> Result<f64, String> {
    let (back, size, _, _) = decode(jxl)?;
    if size != (w, h) || back.rgba() != px.rgba() {
        return Err("the base changed when the jhgm box was added".into());
    }
    let (_, gm) = DecodeRequest::new(jxl)
        .decode_gain_map()
        .map_err(|e| format!("jhgm read: {e}"))?;
    let gm = gm.ok_or("the jhgm box did not read back")?;
    if (gm.gain_map.width, gm.gain_map.height, &gm.gain_map.data)
        != (form.map.width, form.map.height, &form.map.data)
    {
        return Err("the jhgm gain map did not read back unchanged".into());
    }
    let ours = crate::hdr::reconstruct(px.rgba(), w, h, &form.source_map, &form.source_curve)?;
    let from_jhgm = crate::hdr::reconstruct(
        px.rgba(),
        w,
        h,
        &gm.gain_map,
        &crate::hdr::Curve::Iso(gm.metadata),
    )?;
    let worst = worst_stops(&ours, &from_jhgm);
    // tmap: the same map and parameters (rational round trip only). Apple: half a code step.
    let limit = match form.source_curve {
        crate::hdr::Curve::Apple { stops } => stops / 510.0 + 1e-3,
        crate::hdr::Curve::Iso(_) => 1e-3,
    };
    if worst > limit {
        return Err(format!(
            "HDR from jhgm differs by {worst:.4} stops (limit {limit:.4})"
        ));
    }
    Ok(worst)
}

/// For an UltraHDR JPEG-in-JXL: the largest difference between the gain map its `jhgm` box
/// decodes to and zenjpeg's decode of the JPEG's own gain map (both as stored).
fn jpeg_jhgm_diff(jxl: &[u8], jpeg: &[u8]) -> Result<String, String> {
    let (_, a) = DecodeRequest::new(jxl)
        .decode_gain_map()
        .map_err(|e| format!("jhgm read: {e}"))?;
    let (_, b) = DecodeRequest::new(jpeg)
        .decode_gain_map()
        .map_err(|e| format!("jpeg gain map: {e}"))?;
    let (a, b) = (
        a.ok_or("jhgm did not read back")?,
        b.ok_or("the JPEG has no gain map")?,
    );
    if (a.gain_map.width, a.gain_map.height) != (b.gain_map.width, b.gain_map.height) {
        return Err("jhgm gain map size differs from the JPEG's".into());
    }
    let d = a
        .gain_map
        .data
        .iter()
        .zip(&b.gain_map.data)
        .map(|(x, y)| x.abs_diff(*y))
        .max()
        .unwrap_or(0);
    Ok(format!("jpeg gain map, max diff {d}"))
}

/// One file of the report.
struct Written {
    layer: &'static str,
    bytes: Vec<u8>,
    kind: &'static str,
    colour: &'static str,
    pixels_sha256: String,
    jpeg_sha256: String,
    jpeg_diff: String,
    jhgm: String,
}

/// `jxl`: write both JXL layers of one source.
pub(crate) fn render(row: &Row, out_dir: &Path) -> Result<Vec<String>, String> {
    if !row.provenance.is_ascii() {
        return Err("provenance JSON must be ASCII (escape the rest as \\uXXXX)".into());
    }
    let effort = *EFFORT.get().ok_or("no --effort")?;
    let Source {
        colour,
        icc,
        px,
        w,
        h,
        gain_map,
        ..
    } = load(row)?;
    let xmp = provenance_xmp(row.provenance);
    let data = fs::read(row.source).map_err(|e| format!("read: {e}"))?;
    let is_jpeg = matches!(
        row.source
            .rsplit('.')
            .next()
            .map(str::to_ascii_lowercase)
            .as_deref(),
        Some("jpg" | "jpeg")
    );
    let blank =
        |layer: &'static str, bytes: Vec<u8>, kind: &'static str, pixels_sha256: String| Written {
            layer,
            bytes,
            kind,
            colour: colour.name(),
            pixels_sha256,
            jpeg_sha256: String::new(),
            jpeg_diff: String::new(),
            jhgm: String::new(),
        };
    let lossless =
        |px: &Pixels, colour: Colour, icc: Option<&[u8]>| -> Result<(Vec<u8>, String), String> {
            let jxl = encode_lossless(px, w, h, colour, icc, &xmp, effort)?;
            let (back, size, meta, cicp) = decode(&jxl)?;
            if size != (w, h) {
                return Err(format!(
                    "lossless JXL decodes {}x{}, not {w}x{h}",
                    size.0, size.1
                ));
            }
            let (a, b) = (back.rgba(), px.rgba());
            if a != b {
                // Keep the rejected file for diagnosis, apart from the layers.
                let reject = out_dir.join("rejects").join(format!("{}.jxl", row.id));
                let _ = fs::create_dir_all(reject.parent().unwrap());
                let _ = fs::write(&reject, &jxl);
                let n = a.iter().zip(&b).filter(|(p, q)| p != q).count();
                let m = a
                    .iter()
                    .zip(&b)
                    .map(|(p, q)| p.abs_diff(*q))
                    .max()
                    .unwrap_or(0);
                return Err(format!(
                    "lossless JXL PIXELS DIFFER: {n} samples, max {m}; decoded {} from {}",
                    back.layout(),
                    px.layout()
                ));
            }
            if meta.xmp.as_deref() != Some(&xmp[..]) {
                return Err("provenance XMP did not survive".into());
            }
            check_colour(colour, &meta, cicp, icc)?;
            Ok((jxl, hex(&Sha256::digest(px.rgba()))))
        };
    let mut files: Vec<Written> = Vec::new();

    if is_jpeg {
        let (jxl, kind) = jpeg_in_jxl(&data, effort)?;
        let jpeg_sha256 = if kind == "jpeg-in-jxl" {
            let back = zencodecs::reconstruct_jpeg_from_jxl(&jxl)
                .map_err(|e| format!("jpeg rebuild: {e}"))?
                .ok_or("no reconstruction data in the transcode")?;
            if back != data {
                return Err("REBUILT JPEG DIFFERS".into());
            }
            hex(&Sha256::digest(&back))
        } else {
            String::new()
        };
        let (back, size, _, _) = decode(&jxl)?;
        if size != (w, h) {
            return Err(format!(
                "JPEG-in-JXL decodes {}x{}, not {w}x{h}",
                size.0, size.1
            ));
        }
        let diff = max_diff(&back, &px)?;
        // An UltraHDR JPEG's gain map must reach the JXL as a jhgm box (the transcode makes it).
        let (kind, jhgm) = match (gain_map.is_some(), has_box(&jxl, b"jhgm")) {
            (true, true) => (
                if kind == "jpeg-in-jxl" {
                    "jpeg-in-jxl+jhgm"
                } else {
                    "jpeg-in-jxl-codestream+jhgm"
                },
                jpeg_jhgm_diff(&jxl, &data)?,
            ),
            (true, false) => return Err("UltraHDR JPEG-in-JXL without a jhgm box".into()),
            (false, true) => return Err("jhgm box from a JPEG without a gain map".into()),
            (false, false) => (kind, String::new()),
        };
        let mut p3 = blank("jxl-p3", jxl, kind, hex(&Sha256::digest(back.rgba())));
        p3.jpeg_sha256 = jpeg_sha256;
        p3.jpeg_diff = diff.to_string();
        p3.jhgm = jhgm;
        if colour.is_srgb() {
            let mut srgb = blank(
                "jxl-srgb",
                p3.bytes.clone(),
                p3.kind,
                p3.pixels_sha256.clone(),
            );
            srgb.jpeg_sha256 = p3.jpeg_sha256.clone();
            srgb.jpeg_diff = p3.jpeg_diff.clone();
            srgb.jhgm = p3.jhgm.clone();
            files.push(srgb);
        } else {
            let (spx, _) = to_srgb(&px, w, colour)?;
            let (jxl, hash) = lossless(&spx, Colour::Srgb, None)?;
            files.push(blank("jxl-srgb", jxl, "lossless", hash));
        }
        files.push(p3);
    } else {
        let (jxl, hash) = lossless(&px, colour, icc.as_deref())?;
        if colour.is_srgb() {
            files.push(blank("jxl-srgb", jxl.clone(), "lossless", hash.clone()));
        } else {
            let (spx, _) = to_srgb(&px, w, colour)?;
            let (sjxl, shash) = lossless(&spx, Colour::Srgb, None)?;
            files.push(blank("jxl-srgb", sjxl, "lossless", shash));
        }
        // A HEIC with a gain map: its p3 file also carries the gain-map form (jhgm).
        let p3 = match crate::hdr::jhgm_form(&data, row.source, (w, h))? {
            None => blank("jxl-p3", jxl, "lossless", hash),
            Some(form) => {
                let with = zenjxl::append_gain_map_box(&jxl, &jhgm_payload(&form, effort)?);
                let worst = check_jhgm(&with, &px, w, h, &form)?;
                let mut f = blank("jxl-p3", with, "lossless+jhgm", hash);
                f.jhgm = format!("{}, {worst:.4} stops from the source's HDR", form.kind);
                f
            }
        };
        files.push(p3);
    }

    let name = format!("{}_{w}x{h}.jxl", row.stem);
    let mut rows = Vec::new();
    for f in &files {
        let path = out_dir.join(f.layer).join(&name);
        fs::create_dir_all(path.parent().unwrap()).map_err(|e| format!("mkdir: {e}"))?;
        fs::write(&path, &f.bytes).map_err(|e| format!("write: {e}"))?;
        rows.push(format!(
            "{}\t{}\t{}/{name}\t{w}\t{h}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t",
            row.id,
            f.layer,
            f.layer,
            f.kind,
            f.colour,
            f.bytes.len(),
            hex(&Sha256::digest(&f.bytes)),
            f.pixels_sha256,
            f.jpeg_sha256,
            f.jpeg_diff,
            f.jhgm,
        ));
    }
    Ok(rows)
}

/// `jxl-hdr`: the lossless twin of each `.hdr.png` from `png-hdr`, as
/// `jxl-p3/<stem>_<W>x<H>.hdr.jxl`. It reads the PNG's 16-bit PQ samples, cLLI and provenance
/// and encodes exactly those samples, the colour stated as CICP 12/16 (Display P3, PQ) and
/// MaxCLL as the codestream's intensity target (JXL has no MaxFALL field). The file must decode
/// to the same samples and colour.
pub(crate) fn render_hdr(row: &Row, out_dir: &Path) -> Result<Vec<String>, String> {
    let effort = *EFFORT.get().ok_or("no --effort")?;
    let (class, file) = row
        .stem
        .split_once('/')
        .ok_or("stem without a class folder")?;
    let dir = out_dir.join("png-p3").join(class);
    let prefix = format!("{file}_");
    let png_name = fs::read_dir(&dir)
        .map_err(|e| format!("read {}: {e}", dir.display()))?
        .filter_map(Result::ok)
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .find(|n| n.starts_with(&prefix) && n.ends_with(".hdr.png"))
        .ok_or("no .hdr.png for this row (run png-hdr first)")?;
    let png = fs::read(dir.join(&png_name)).map_err(|e| format!("read: {e}"))?;
    let d = zenpng::decode(
        &png,
        &zenpng::PngDecodeConfig::default().with_max_pixels(1_000_000_000),
        &enough::Unstoppable,
    )
    .map_err(|e| format!("png decode: {e:?}"))?;
    let (w, h) = (d.info.width as usize, d.info.height as usize);
    let samples = d.pixels.copy_to_contiguous_bytes();
    if samples.len() != w * h * 6 {
        return Err(format!("{png_name} is not 16-bit RGB"));
    }
    if d.info.cicp != Some(zencodec::Cicp::new(12, 16, 0, true)) {
        return Err(format!("{png_name} is not CICP 12/16"));
    }
    let [cll, fall] = d.info.content_light_level_raw.ok_or("no cLLI")?;
    let provenance = d
        .info
        .text_chunks
        .first()
        .map(|t| t.text.clone())
        .ok_or("no provenance text")?;
    if provenance != row.provenance {
        return Err("the PNG's provenance differs from the list's".into());
    }
    let xmp = provenance_xmp(&provenance);
    let max_cll = (f64::from(cll) / 10000.0).ceil().min(65535.0) as u16;
    let max_fall = (f64::from(fall) / 10000.0).round().min(65535.0) as u16;
    let cicp = zencodec::Cicp::new(12, 16, 0, true);
    // Labelled as plain 16-bit sRGB so nothing converts the samples; the metadata states PQ.
    let desc = PixelDescriptor::RGB16_SRGB;
    let slice = PixelSlice::new(&samples, w as u32, h as u32, w * 6, desc)
        .map_err(|e| format!("pixel slice: {e:?}"))?;
    let meta = Metadata::default()
        .with_xmp(xmp.clone())
        .with_cicp(cicp)
        .with_content_light_level(zenpixels::hdr::ContentLightLevel::new(max_cll, max_fall));
    let jxl = EncodeRequest::new(ImageFormat::Jxl)
        .with_lossless(true)
        .with_effort(u32::from(effort))
        .with_metadata(meta)
        .encode(slice, false)
        .map_err(|e| format!("jxl encode: {e}"))?
        .into_vec();

    let limits = limits();
    let back = DecodeRequest::new(&jxl)
        .with_limits(&limits)
        .decode_full_frame()
        .map_err(|e| format!("jxl decode: {e}"))?;
    let got_cicp = back.info().source_color.cicp;
    let got_meta = back.metadata().clone();
    let buf = back.into_buffer();
    let got = buf.copy_to_contiguous_bytes();
    if (buf.width() as usize, buf.height() as usize) != (w, h) || got != samples {
        return Err(format!(
            "HDR JXL decodes different samples ({:?}, {} bytes)",
            buf.descriptor(),
            got.len()
        ));
    }
    match got_cicp {
        Some(c) if c.color_primaries == 12 && c.transfer_characteristics == 16 => {}
        other => return Err(format!("HDR JXL colour {other:?}, want CICP 12/16")),
    }
    if got_meta.xmp.as_deref() != Some(&xmp[..]) {
        return Err("provenance XMP did not survive".into());
    }

    let name = png_name.replace(".hdr.png", ".hdr.jxl");
    let path = out_dir.join("jxl-p3").join(class).join(&name);
    fs::create_dir_all(path.parent().unwrap()).map_err(|e| format!("mkdir: {e}"))?;
    fs::write(&path, &jxl).map_err(|e| format!("write: {e}"))?;
    Ok(vec![format!(
        "{}\tjxl-p3-hdr\tjxl-p3/{class}/{name}\t{w}\t{h}\tlossless-pq\tdisplay-p3-pq\t{}\t{}\t{}\t\t\t",
        row.id,
        jxl.len(),
        hex(&Sha256::digest(&jxl)),
        hex(&Sha256::digest(&samples)),
    )])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provenance_xmp_escapes_markup() {
        let x = String::from_utf8(provenance_xmp("{\"t\":\"a<b&c\"}")).unwrap();
        assert!(x.contains("<imazen26:provenance>{\"t\":\"a&lt;b&amp;c\"}</imazen26:provenance>"));
        assert!(x.starts_with("<?xpacket begin=\"\u{feff}\""));
    }
}
