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
pub(crate) const JXL_HEADER: &str = "id\tlayer\tpath\twidth\theight\tkind\tcolour\tbytes\tsha256\tpixels_sha256\tjpeg_sha256\tjpeg_pixel_max_diff\terror";

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

/// One file of the report.
struct Written {
    layer: &'static str,
    bytes: Vec<u8>,
    kind: &'static str,
    colour: &'static str,
    pixels_sha256: String,
    jpeg_sha256: String,
    jpeg_diff: String,
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
    let mut files: Vec<Written> = Vec::new();

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
        let written = Written {
            layer: "jxl-p3",
            bytes: jxl,
            kind,
            colour: colour.name(),
            pixels_sha256: hex(&Sha256::digest(back.rgba())),
            jpeg_sha256,
            jpeg_diff: diff.to_string(),
        };
        if colour.is_srgb() {
            files.push(Written {
                layer: "jxl-srgb",
                bytes: written.bytes.clone(),
                kind,
                colour: written.colour,
                pixels_sha256: written.pixels_sha256.clone(),
                jpeg_sha256: written.jpeg_sha256.clone(),
                jpeg_diff: written.jpeg_diff.clone(),
            });
        } else {
            let (spx, _) = to_srgb(&px, w, colour)?;
            let (jxl, hash) = lossless(&spx, Colour::Srgb, None)?;
            files.push(Written {
                layer: "jxl-srgb",
                bytes: jxl,
                kind: "lossless",
                colour: colour.name(),
                pixels_sha256: hash,
                jpeg_sha256: String::new(),
                jpeg_diff: String::new(),
            });
        }
        files.push(written);
    } else {
        let (jxl, hash) = lossless(&px, colour, icc.as_deref())?;
        if colour.is_srgb() {
            files.push(Written {
                layer: "jxl-srgb",
                bytes: jxl.clone(),
                kind: "lossless",
                colour: colour.name(),
                pixels_sha256: hash.clone(),
                jpeg_sha256: String::new(),
                jpeg_diff: String::new(),
            });
        } else {
            let (spx, _) = to_srgb(&px, w, colour)?;
            let (sjxl, shash) = lossless(&spx, Colour::Srgb, None)?;
            files.push(Written {
                layer: "jxl-srgb",
                bytes: sjxl,
                kind: "lossless",
                colour: colour.name(),
                pixels_sha256: shash,
                jpeg_sha256: String::new(),
                jpeg_diff: String::new(),
            });
        }
        files.push(Written {
            layer: "jxl-p3",
            bytes: jxl,
            kind: "lossless",
            colour: colour.name(),
            pixels_sha256: hash,
            jpeg_sha256: String::new(),
            jpeg_diff: String::new(),
        });
    }

    let name = format!("{}_{w}x{h}.jxl", row.stem);
    let mut rows = Vec::new();
    for f in &files {
        let path = out_dir.join(f.layer).join(&name);
        fs::create_dir_all(path.parent().unwrap()).map_err(|e| format!("mkdir: {e}"))?;
        fs::write(&path, &f.bytes).map_err(|e| format!("write: {e}"))?;
        rows.push(format!(
            "{}\t{}\t{}/{name}\t{w}\t{h}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t",
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
        ));
    }
    Ok(rows)
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
