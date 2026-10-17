//! Decode the imazen-26 JPEG XL and PNG layers and hash every decoded bitmap
//! (EXPORT-PLAN.md, "Gates"); read every `jhgm` gain map back with each decoder.
//!
//!   jxl-decode-check jxl [--jobs N] [--gainmap-dir DIR] < paths > rows.tsv
//!       Each JPEG XL file through zenjxl and jxl-rs (libjxl/libjxl_hash writes the same
//!       columns for libjxl): the base in displayed orientation, and for a `jhgm` box its
//!       bundle (zenjxl's parser for zenjxl; a plain reading of the box layout for jxl-rs, which
//!       only hands back the box) and its gain-map codestream decoded by the same decoder.
//!       With --gainmap-dir each decoded gain map is written as DIR/<decoder>/<name>.pgm|.ppm
//!       and its ISO 21496-1 metadata as DIR/<decoder>/<name>.iso21496.
//!   jxl-decode-check png [--jobs N] < paths > rows.tsv
//!       Each PNG through zenpng, hashed the same way (the PNG layers, the gain-map PNGs, and
//!       the PNGs the reader adapters of the compatibility census write).
//!   jxl-decode-check compare [--jobs N] < lines > rows.tsv
//!       Each `<reference>\t<output.png>[\t<alternate reference>]` line: the output (a reader's
//!       decode, as the compatibility census's adapters write it) hashed in its own layout and
//!       as 8-bit RGBA, and compared with our decode of the reference file (zenpng or zenjxl)
//!       and of the alternate one (the sRGB twin of a wide-gamut file). An alternate of
//!       `=srgb:display-p3` or `=srgb:adobe-rgb` is our decode of the reference converted to
//!       sRGB the way render-v4 makes its sRGB layer, for a wide-gamut JPEG-in-JXL file: its
//!       twin comes from the PNG layer, another decode of the JPEG. `alt_same` is then `within`
//!       when every sample is within what a decode one code value from ours becomes after the
//!       conversion, plus 2 (`srgb_of`). `same` is native, rgba8, no or size, or `stored` when an
//!       output of a JPEG XL file matches our decode in the file's stored orientation (the
//!       codestream's orientation not applied) better, and the differences are then against it.
//!   jxl-decode-check hdr [--jobs N] < pairs > rows.tsv
//!       Each `<jxl>\t<hdr.png>` pair: zenjxl's own HDR reconstruction of the JXL's gain map
//!       (GainMapRender::ReconstructHdr), compared in stops with the 16-bit PQ render.
//!
//! The hash is XXH3-64 (seed 0) of the interleaved samples in the image's own layout: gray,
//! gray+alpha, RGB or RGBA; 8-bit samples, or 16-bit little-endian when the image has more
//! than 8 bits per sample; rows packed. Every decoder is asked for exactly that layout, so equal
//! hashes mean equal pixels.
//!
//! jxl-rs and libjxl are third-party test oracles: they read, and never write anything shipped.

use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use rayon::prelude::*;
use xxhash_rust::xxh3::xxh3_64;
use zencodec::decode::{Decode as _, DecodeJob as _, DecoderConfig as _};

const HEADER: &str = "path\tdecoder\tstatus\twidth\theight\tchannels\tbits\torientation\txxh3\t\
jhgm_bytes\tjhgm_version\tmetadata_bytes\tmetadata_xxh3\thas_color_encoding\talt_icc_bytes\t\
gain_map_bytes\tgm_status\tgm_width\tgm_height\tgm_channels\tgm_bits\tgm_xxh3\terror";

/// A decoded bitmap in the canonical layout.
struct Bitmap {
    width: u32,
    height: u32,
    channels: u32,
    bits: u32,
    samples: Vec<u8>,
}

impl Bitmap {
    fn xxh3(&self) -> String {
        format!("{:016x}", xxh3_64(&self.samples))
    }
}

/// Decode limits wide enough for the corpus's largest image (render-v4 uses the same pixel
/// limit): zencodecs' and zenjxl's defaults refuse the 124 MP panorama.
fn limits() -> zencodecs::Limits {
    zencodecs::Limits::none()
        .with_max_pixels(400_000_000)
        .with_max_memory(24 << 30)
}

fn job_limits() -> zencodec::ResourceLimits {
    zencodec::ResourceLimits::none()
        .with_max_pixels(400_000_000)
        .with_max_memory(24 << 30)
}

/// What one decoder made of one file.
#[derive(Default)]
struct Row {
    status: &'static str,
    width: u32,
    height: u32,
    channels: u32,
    bits: u32,
    orientation: String,
    xxh3: String,
    jhgm: Option<Jhgm>,
    error: String,
}

#[derive(Default)]
struct Jhgm {
    bytes: usize,
    version: u8,
    metadata: Vec<u8>,
    has_color_encoding: bool,
    alt_icc_bytes: usize,
    gain_map_bytes: usize,
    gm: Option<Result<Bitmap, String>>,
}

impl Row {
    fn line(&self, path: &str, decoder: &str) -> String {
        let mut f = vec![
            path.to_string(),
            decoder.to_string(),
            self.status.to_string(),
            self.width.to_string(),
            self.height.to_string(),
            self.channels.to_string(),
            self.bits.to_string(),
            self.orientation.clone(),
            self.xxh3.clone(),
        ];
        let mut error = self.error.clone();
        match &self.jhgm {
            None => f.extend(std::iter::repeat_n(String::new(), 13)),
            Some(j) => {
                f.push(j.bytes.to_string());
                f.push(j.version.to_string());
                f.push(j.metadata.len().to_string());
                f.push(format!("{:016x}", xxh3_64(&j.metadata)));
                f.push(u8::from(j.has_color_encoding).to_string());
                f.push(j.alt_icc_bytes.to_string());
                f.push(j.gain_map_bytes.to_string());
                match &j.gm {
                    Some(Ok(b)) => {
                        f.push("ok".into());
                        f.push(b.width.to_string());
                        f.push(b.height.to_string());
                        f.push(b.channels.to_string());
                        f.push(b.bits.to_string());
                        f.push(b.xxh3());
                    }
                    Some(Err(e)) => {
                        f.push("error".into());
                        f.extend(std::iter::repeat_n(String::new(), 5));
                        if error.is_empty() {
                            error = format!("gain map: {e}");
                        }
                    }
                    None => f.extend(std::iter::repeat_n(String::new(), 6)),
                }
            }
        }
        f.push(error.replace(['\t', '\n'], " "));
        f.join("\t")
    }
}

/// The boxes of a JPEG XL container: (type, payload). A bare codestream has none.
fn boxes(data: &[u8]) -> Vec<([u8; 4], &[u8])> {
    let mut out = Vec::new();
    if !data.starts_with(&[0, 0, 0, 0x0c, b'J', b'X', b'L', b' ']) {
        return out;
    }
    let mut pos = 0usize;
    while pos + 8 <= data.len() {
        let size = u32::from_be_bytes(data[pos..pos + 4].try_into().unwrap()) as u64;
        let ty: [u8; 4] = data[pos + 4..pos + 8].try_into().unwrap();
        let (header, size) = match size {
            0 => (8, (data.len() - pos) as u64),
            1 if pos + 16 <= data.len() => (
                16,
                u64::from_be_bytes(data[pos + 8..pos + 16].try_into().unwrap()),
            ),
            n => (8, n),
        };
        let end = pos.saturating_add(size as usize).min(data.len());
        if size < header as u64 || end < pos + header {
            break;
        }
        out.push((ty, &data[pos + header..end]));
        pos = end;
    }
    out
}

/// The jhgm bundle layout (libjxl `jxl/gain_map.h`), read plainly for the jxl-rs leg:
/// version u8, metadata size u16 BE, metadata, colour-encoding size u8, colour encoding,
/// alt-ICC size u32 BE, compressed alt ICC, then the gain map as a bare codestream.
struct PlainBundle<'a> {
    version: u8,
    metadata: &'a [u8],
    color_encoding: &'a [u8],
    alt_icc: &'a [u8],
    codestream: &'a [u8],
}

fn plain_bundle(b: &[u8]) -> Result<PlainBundle<'_>, String> {
    let take = |pos: &mut usize, n: usize| -> Result<&[u8], String> {
        let s = b.get(*pos..*pos + n).ok_or("jhgm box truncated")?;
        *pos += n;
        Ok(s)
    };
    let mut pos = 0;
    let version = take(&mut pos, 1)?[0];
    let n = u16::from_be_bytes(take(&mut pos, 2)?.try_into().unwrap()) as usize;
    let metadata = take(&mut pos, n)?;
    let n = take(&mut pos, 1)?[0] as usize;
    let color_encoding = take(&mut pos, n)?;
    let n = u32::from_be_bytes(take(&mut pos, 4)?.try_into().unwrap()) as usize;
    let alt_icc = take(&mut pos, n)?;
    Ok(PlainBundle {
        version,
        metadata,
        color_encoding,
        alt_icc,
        codestream: &b[pos..],
    })
}

/// Samples of a zen decode in the canonical layout.
fn zen_bitmap(px: &zenpixels::PixelSlice<'_>) -> Result<Bitmap, String> {
    use zenpixels::{ChannelType, PixelFormat};
    let desc = px.descriptor();
    let channels = match desc.pixel_format() {
        PixelFormat::Gray8 | PixelFormat::Gray16 => 1,
        PixelFormat::GrayA8 | PixelFormat::GrayA16 => 2,
        PixelFormat::Rgb8 | PixelFormat::Rgb16 => 3,
        PixelFormat::Rgba8 | PixelFormat::Rgba16 => 4,
        other => return Err(format!("unexpected zen layout {other:?}")),
    };
    let bits = match desc.channel_type() {
        ChannelType::U8 => 8,
        ChannelType::U16 => 16,
        other => return Err(format!("unexpected zen sample type {other:?}")),
    };
    let mut samples = px.contiguous_bytes().into_owned();
    if bits == 16 && cfg!(target_endian = "big") {
        for c in samples.as_chunks_mut::<2>().0 {
            c.swap(0, 1);
        }
    }
    Ok(Bitmap {
        width: px.width(),
        height: px.rows(),
        channels,
        bits,
        samples,
    })
}

fn zenjxl_decode(data: &[u8], components: bool) -> Result<zencodec::decode::DecodeOutput, String> {
    let job = zenjxl::JxlDecoderConfig::new()
        .job()
        .with_limits(job_limits())
        .with_orientation(zencodec::OrientationHint::Correct);
    let job = if components {
        job.with_gain_map_render(zencodec::GainMapRender::Components)
    } else {
        job
    };
    job.decoder(data.into(), &[])
        .map_err(|e| format!("zenjxl: {e}"))?
        .decode()
        .map_err(|e| format!("zenjxl: {e}"))
}

fn zen_row(data: &[u8]) -> Row {
    let mut row = Row::default();
    let jhgm_box = boxes(data)
        .into_iter()
        .find(|(t, _)| t == b"jhgm")
        .map(|(_, p)| p);
    let out = match zenjxl_decode(data, jhgm_box.is_some()) {
        Ok(o) => o,
        Err(e) => {
            row.status = "error";
            row.error = e;
            return row;
        }
    };
    row.orientation = format!("{:?}", out.info().orientation);
    match zen_bitmap(&out.pixels()) {
        Ok(b) => {
            row.status = "ok";
            (row.width, row.height, row.channels, row.bits) =
                (b.width, b.height, b.channels, b.bits);
            row.xxh3 = b.xxh3();
        }
        Err(e) => {
            row.status = "error";
            row.error = e;
            return row;
        }
    }
    if let Some(raw) = jhgm_box {
        let mut j = Jhgm {
            bytes: raw.len(),
            version: raw.first().copied().unwrap_or(0),
            ..Jhgm::default()
        };
        match zenjxl::GainMapBundle::parse(raw) {
            Ok(b) => {
                j.metadata = b.metadata.clone();
                j.has_color_encoding = b.color_encoding.is_some();
                j.alt_icc_bytes = b.alt_icc_compressed.as_ref().map_or(0, |v| v.len());
                j.gain_map_bytes = b.gain_map_codestream.len();
                j.gm = Some(
                    out.extras::<zencodec::decode::DecodedGainMap>()
                        .ok_or_else(|| "zenjxl surfaced no gain map".to_string())
                        .and_then(|g| zen_bitmap(&g.pixels.as_slice())),
                );
            }
            Err(e) => j.gm = Some(Err(format!("zenjxl bundle parse: {e}"))),
        }
        row.jhgm = Some(j);
    }
    row
}

/// jxl-rs: the image in displayed orientation (its default) in the canonical layout, plus
/// any boxes of `want`.
fn jxlrs_decode(
    data: &[u8],
    want: Option<[u8; 4]>,
) -> Result<(Bitmap, String, Option<Vec<u8>>), String> {
    use jxl::api::{
        Endianness, JxlAuxBoxType, JxlColorType, JxlDataFormat, JxlDecoder, JxlDecoderOptions,
        JxlOutputBuffer, JxlPixelFormat, ProcessingResult, states,
    };
    use jxl::headers::extra_channels::ExtraChannel;
    let mut opts = JxlDecoderOptions::default();
    if let Some(t) = want {
        opts.request_aux_boxes = vec![JxlAuxBoxType(t)];
    }
    let mut input: &[u8] = data;
    let dec = JxlDecoder::<states::Initialized>::new(opts);
    let mut dec = match dec
        .process(&mut input, None)
        .map_err(|e| format!("jxl-rs: {e}"))?
    {
        ProcessingResult::Complete { result } => result,
        ProcessingResult::NeedsMoreInput { .. } => return Err("jxl-rs: truncated header".into()),
    };
    let info = dec.basic_info().clone();
    let gray = dec.embedded_color_profile().channels() == 1;
    let alpha_idx = info
        .extra_channels
        .iter()
        .position(|e| e.ec_type == ExtraChannel::Alpha);
    let bits = info.bit_depth.bits_per_sample();
    if matches!(info.bit_depth, jxl::api::JxlBitDepth::Float { .. }) {
        return Err("jxl-rs: float samples".into());
    }
    let (sample_bytes, fmt) = if bits <= 8 {
        (1, JxlDataFormat::U8 { bit_depth: 8 })
    } else {
        (
            2,
            JxlDataFormat::U16 {
                endianness: Endianness::LittleEndian,
                bit_depth: 16,
            },
        )
    };
    let color_type = match (gray, alpha_idx.is_some()) {
        (true, false) => JxlColorType::Grayscale,
        (true, true) => JxlColorType::GrayscaleAlpha,
        (false, false) => JxlColorType::Rgb,
        (false, true) => JxlColorType::Rgba,
    };
    let channels = match color_type {
        JxlColorType::Grayscale => 1,
        JxlColorType::GrayscaleAlpha => 2,
        JxlColorType::Rgb => 3,
        _ => 4,
    };
    // The alpha channel is interleaved into the colour buffer; any other extra channel is
    // not requested.
    let extra = vec![None; info.extra_channels.len()];
    dec.set_pixel_format(JxlPixelFormat {
        color_type,
        color_data_format: Some(fmt),
        extra_channel_format: extra,
    })
    .map_err(|e| format!("jxl-rs pixel format: {e}"))?;
    let orientation = format!("{:?}", info.orientation);
    let frame = match dec
        .process(&mut input, None)
        .map_err(|e| format!("jxl-rs: {e}"))?
    {
        ProcessingResult::Complete { result } => result,
        ProcessingResult::NeedsMoreInput { .. } => {
            return Err("jxl-rs: truncated frame header".into());
        }
    };
    // With adjust_orientation (the default), basic info already gives the displayed size.
    let (w, h) = info.size;
    let row_bytes = w * channels * sample_bytes;
    let mut samples = vec![0u8; row_bytes * h];
    let after = {
        let mut bufs = [JxlOutputBuffer::new(&mut samples, h, row_bytes)];
        match frame
            .process(&mut input, &mut bufs, None)
            .map_err(|e| format!("jxl-rs: {e}"))?
        {
            ProcessingResult::Complete { result } => result,
            ProcessingResult::NeedsMoreInput { .. } => return Err("jxl-rs: truncated frame".into()),
        }
    };
    let dec = dec_after_frames(after)?;
    let boxed = match want {
        None => None,
        Some(t) => {
            // Boxes after the codestream are parsed as trailing data.
            let trailing = dec
                .process_trailing_data(&mut input)
                .map_err(|e| format!("jxl-rs trailing: {e}"))?;
            let found = |b: &[jxl::api::JxlAuxBox]| b.first().map(|x| x.raw_data().to_vec());
            match trailing {
                ProcessingResult::Complete { result } => found(result.aux_boxes(JxlAuxBoxType(t))),
                ProcessingResult::NeedsMoreInput { fallback, .. } => {
                    found(fallback.aux_boxes(JxlAuxBoxType(t)))
                }
            }
        }
    };
    let bitmap = Bitmap {
        width: w as u32,
        height: h as u32,
        channels: channels as u32,
        bits: if bits <= 8 { 8 } else { 16 },
        samples,
    };
    Ok((bitmap, orientation, boxed))
}

/// After the last frame: a still image has no more frames.
fn dec_after_frames(
    dec: jxl::api::JxlDecoder<jxl::api::states::WithImageInfo>,
) -> Result<jxl::api::JxlDecoder<jxl::api::states::WithImageInfo>, String> {
    if dec.has_more_frames() {
        return Err("jxl-rs: more than one frame".into());
    }
    Ok(dec)
}

fn jxlrs_row(data: &[u8]) -> Row {
    let mut row = Row::default();
    let has_jhgm = boxes(data).iter().any(|(t, _)| t == b"jhgm");
    match jxlrs_decode(data, has_jhgm.then_some(*b"jhgm")) {
        Err(e) => {
            row.status = "error";
            row.error = e;
        }
        Ok((b, orientation, raw)) => {
            row.status = "ok";
            (row.width, row.height, row.channels, row.bits) =
                (b.width, b.height, b.channels, b.bits);
            row.xxh3 = b.xxh3();
            row.orientation = orientation;
            if has_jhgm {
                let mut j = Jhgm::default();
                match raw {
                    None => j.gm = Some(Err("jxl-rs returned no jhgm box".into())),
                    Some(raw) => {
                        j.bytes = raw.len();
                        match plain_bundle(&raw) {
                            Err(e) => j.gm = Some(Err(e)),
                            Ok(p) => {
                                j.version = p.version;
                                j.metadata = p.metadata.to_vec();
                                j.has_color_encoding = !p.color_encoding.is_empty();
                                j.alt_icc_bytes = p.alt_icc.len();
                                j.gain_map_bytes = p.codestream.len();
                                j.gm = Some(jxlrs_decode(p.codestream, None).map(|(b, _, _)| b));
                            }
                        }
                    }
                }
                row.jhgm = Some(j);
            }
        }
    }
    row
}

fn write_gainmap(
    dir: &Path,
    decoder: &str,
    name: &str,
    b: &Bitmap,
    metadata: &[u8],
) -> Result<(), String> {
    if b.bits != 8 || !(b.channels == 1 || b.channels == 3) {
        return Err(format!("gain map layout {}x{}", b.channels, b.bits));
    }
    let d = dir.join(decoder);
    std::fs::create_dir_all(&d).map_err(|e| e.to_string())?;
    let mut pnm = format!(
        "P{}\n{} {}\n255\n",
        if b.channels == 1 { 5 } else { 6 },
        b.width,
        b.height
    )
    .into_bytes();
    pnm.extend_from_slice(&b.samples);
    let ext = if b.channels == 1 { "pgm" } else { "ppm" };
    std::fs::write(d.join(format!("{name}.{ext}")), pnm).map_err(|e| e.to_string())?;
    std::fs::write(d.join(format!("{name}.iso21496")), metadata).map_err(|e| e.to_string())
}

fn png_row(data: &[u8]) -> Row {
    let mut row = Row::default();
    let out = zencodecs::DecodeRequest::new(data)
        .with_limits(&limits())
        .with_format(zencodec::ImageFormat::Png)
        .decode_full_frame();
    match out
        .map_err(|e| format!("zenpng: {e}"))
        .and_then(|o| zen_bitmap(&o.pixels()))
    {
        Ok(b) => {
            row.status = "ok";
            (row.width, row.height, row.channels, row.bits) =
                (b.width, b.height, b.channels, b.bits);
            row.xxh3 = b.xxh3();
        }
        Err(e) => {
            row.status = "error";
            row.error = e;
        }
    }
    row
}

/// SMPTE ST 2084 EOTF: a PQ code value in [0, 1] to nits.
fn pq_to_nits(e: f64) -> f64 {
    let (m1, m2) = (2610.0 / 16384.0, 2523.0 / 4096.0 * 128.0);
    let (c1, c2, c3) = (
        3424.0 / 4096.0,
        2413.0 / 4096.0 * 32.0,
        2392.0 / 4096.0 * 32.0,
    );
    let p = e.powf(1.0 / m2);
    10000.0 * ((p - c1).max(0.0) / (c2 - c3 * p)).powf(1.0 / m1)
}

/// SMPTE ST 2084 inverse EOTF: nits to a PQ code value in [0, 1].
fn nits_to_pq(nits: f64) -> f64 {
    let (m1, m2) = (2610.0 / 16384.0, 2523.0 / 4096.0 * 128.0);
    let (c1, c2, c3) = (
        3424.0 / 4096.0,
        2413.0 / 4096.0 * 32.0,
        2392.0 / 4096.0 * 32.0,
    );
    let y = (nits / 10000.0).clamp(0.0, 1.0).powf(m1);
    ((c1 + c2 * y) / (1.0 + c3 * y)).powf(m2)
}

/// zenjxl's HDR reconstruction of `jxl` against the PQ render `hdr_png` (diffuse white at
/// 203 nits), per channel: the difference in 10-bit PQ code values over every sample (PQ is
/// close to perceptually uniform, so dark samples weigh no more than their visibility), and
/// |log2| ratios over samples at or above 5% of SDR white in the render.
fn hdr_line(jxl_path: &str, png_path: &str) -> String {
    let run = || -> Result<String, String> {
        let jxl = std::fs::read(jxl_path).map_err(|e| e.to_string())?;
        let png = std::fs::read(png_path).map_err(|e| e.to_string())?;
        let hdr = zenjxl::JxlDecoderConfig::new()
            .job()
            .with_limits(job_limits())
            .with_orientation(zencodec::OrientationHint::Correct)
            .with_gain_map_render(zencodec::GainMapRender::ReconstructHdr {
                target_headroom: None,
            })
            .decoder(jxl.as_slice().into(), &[])
            .map_err(|e| format!("zenjxl: {e}"))?
            .decode()
            .map_err(|e| format!("zenjxl reconstruct: {e}"))?;
        let px = hdr.pixels();
        let desc = px.descriptor();
        if desc.pixel_format() != zenpixels::PixelFormat::RgbaF32 {
            return Err(format!("reconstruction gave {:?}", desc.pixel_format()));
        }
        let ours = zencodecs::DecodeRequest::new(&png)
            .with_limits(&limits())
            .with_format(zencodec::ImageFormat::Png)
            .decode_full_frame()
            .map_err(|e| format!("zenpng: {e}"))?;
        let ours = zen_bitmap(&ours.pixels())?;
        if (px.width(), px.rows()) != (ours.width, ours.height) {
            return Err(format!(
                "reconstruction is {}x{}, the PQ render {}x{}",
                px.width(),
                px.rows(),
                ours.width,
                ours.height
            ));
        }
        if ours.bits != 16 || ours.channels != 3 {
            return Err("the PQ render is not 16-bit RGB".into());
        }
        let rec = px.contiguous_bytes();
        let rec: Vec<f32> = rec
            .as_chunks::<4>()
            .0
            .iter()
            .map(|c| f32::from_le_bytes(*c))
            .collect();
        let lut: Vec<f64> = (0..65536)
            .map(|v| pq_to_nits(v as f64 / 65535.0) / 203.0)
            .collect();
        let mut codes = Vec::with_capacity(rec.len() / 4 * 3);
        let mut stops = Vec::new();
        for (i, c) in ours.samples.as_chunks::<2>().0.iter().enumerate() {
            let code = u16::from_le_bytes(*c);
            let want = lut[code as usize];
            let got = (rec[i / 3 * 4 + i % 3] as f64).max(0.0);
            codes.push(((nits_to_pq(got * 203.0) - code as f64 / 65535.0) * 1023.0).abs());
            if want >= 0.05 {
                stops.push((got.max(1e-6) / want).log2().abs());
            }
        }
        let q = |v: &mut Vec<f64>, p: f64| {
            v.sort_by(f64::total_cmp);
            v.get(((v.len() as f64 - 1.0) * p).round() as usize)
                .copied()
                .unwrap_or(0.0)
        };
        let (c50, c999, cmax) = (q(&mut codes, 0.5), q(&mut codes, 0.999), q(&mut codes, 1.0));
        let (s50, s999, smax) = (q(&mut stops, 0.5), q(&mut stops, 0.999), q(&mut stops, 1.0));
        Ok(format!(
            "ok\t{}\t{}\t{c50:.3}\t{c999:.3}\t{cmax:.3}\t{s50:.4}\t{s999:.4}\t{smax:.4}\t{}\t",
            px.width(),
            px.rows(),
            stops.len()
        ))
    };
    let tail = run()
        .unwrap_or_else(|e| format!("error\t\t\t\t\t\t\t\t\t\t{}", e.replace(['\t', '\n'], " ")));
    format!("{jxl_path}\t{png_path}\tzenjxl-reconstruct-hdr\t{tail}")
}

/// Our decode of a JPEG XL file in its stored orientation: the codestream's orientation left
/// unapplied, as a reader that hands orientation to the caller (ImageMagick) returns it.
fn stored_bitmap(path: &str) -> Result<Bitmap, String> {
    let data = std::fs::read(path).map_err(|e| format!("{path}: {e}"))?;
    let out = zenjxl::JxlDecoderConfig::new()
        .job()
        .with_limits(job_limits())
        .with_orientation(zencodec::OrientationHint::Preserve)
        .decoder(data.as_slice().into(), &[])
        .map_err(|e| format!("zenjxl: {e}"))?
        .decode()
        .map_err(|e| format!("zenjxl: {e}"))?;
    zen_bitmap(&out.pixels())
}

/// Our decode of `path`: zenjxl for a JPEG XL file, zenpng for anything else.
fn reference_bitmap(path: &str) -> Result<Bitmap, String> {
    let data = std::fs::read(path).map_err(|e| format!("{path}: {e}"))?;
    if path.ends_with(".jxl") {
        zen_bitmap(&zenjxl_decode(&data, false)?.pixels())
    } else {
        let out = zencodecs::DecodeRequest::new(&data)
            .with_limits(&limits())
            .with_format(zencodec::ImageFormat::Png)
            .decode_full_frame()
            .map_err(|e| format!("zenpng: {e}"))?;
        zen_bitmap(&out.pixels())
    }
}

/// Our decode converted to sRGB as render-v4's `to_srgb` makes the sRGB layer (8-bit code values
/// to linear light through the gamut matrix, clipped, encoded as 8-bit sRGB; alpha unchanged),
/// and how far each sample of a correct colour-managed decode may land from it.
///
/// A wide-gamut JPEG-in-JXL file decodes up to a few code values away from the PNG its sRGB twin
/// was made from (another decode of the JPEG), and conforming decoders of the file land within
/// one code value of ours (measured: every libjxl-based reader and glycin's jxl-oxide). The
/// conversion is steep where a saturated colour puts an sRGB channel near zero, so one code
/// value in the wide gamut can move the sRGB value by ten or more. The tolerance of a sample is
/// the most any decode within one code value per channel of ours moves it after the
/// conversion, plus 2 for the reader's own colour arithmetic.
fn srgb_of(b: &Bitmap, colour: &str) -> Result<(Bitmap, Vec<u8>), String> {
    use zenpixels::{ColorPrimaries, PixelDescriptor, TransferFunction};
    use zenpixels_convert::{ConvertOptions, ConvertPlan, convert_row};
    let (primaries, transfer) = match colour {
        "display-p3" => (ColorPrimaries::DisplayP3, TransferFunction::Srgb),
        "adobe-rgb" => (ColorPrimaries::AdobeRgb, TransferFunction::Gamma22),
        other => return Err(format!("no sRGB conversion for colour {other}")),
    };
    if b.bits != 8 || !matches!(b.channels, 3 | 4) {
        return Err(format!(
            "the sRGB conversion takes 8-bit RGB or RGBA, not {} channels of {} bits",
            b.channels, b.bits
        ));
    }
    let from = PixelDescriptor::RGB8_SRGB
        .with_primaries(primaries)
        .with_transfer(transfer);
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
    let (w, c) = (b.width as usize, b.channels as usize);
    let mut lin = vec![0f32; w * 3];
    let mut convert = |rgb: &[u8], out: &mut [u8]| {
        convert_row(&plan, rgb, bytemuck::cast_slice_mut(&mut lin), w as u32);
        for v in &mut lin {
            *v = v.clamp(0.0, 1.0);
        }
        convert_row(&encode, bytemuck::cast_slice(&lin), out, w as u32);
    };
    let mut samples = b.samples.clone();
    let mut tolerance = vec![0u8; b.width as usize * b.height as usize * 4];
    let (mut rgb, mut out, mut moved, mut shifted, mut far) = (
        vec![0u8; w * 3],
        vec![0u8; w * 3],
        vec![0u8; w * 3],
        vec![0u8; w * 3],
        vec![0u8; w * 3],
    );
    for (row, tol) in samples
        .chunks_exact_mut(w * c)
        .zip(tolerance.chunks_exact_mut(w * 4))
    {
        for (d, s) in rgb
            .as_chunks_mut::<3>()
            .0
            .iter_mut()
            .zip(row.chunks_exact(c))
        {
            d.copy_from_slice(&s[..3]);
        }
        convert(&rgb, &mut out);
        far.fill(0);
        for e in 0..27u8 {
            let step = [e % 3, e / 3 % 3, e / 9];
            if step == [1, 1, 1] {
                continue;
            }
            for (d, s) in moved
                .as_chunks_mut::<3>()
                .0
                .iter_mut()
                .zip(rgb.as_chunks::<3>().0)
            {
                for k in 0..3 {
                    d[k] = (s[k] as i16 + step[k] as i16 - 1).clamp(0, 255) as u8;
                }
            }
            convert(&moved, &mut shifted);
            for ((f, x), y) in far.iter_mut().zip(&shifted).zip(&out) {
                *f = (*f).max(x.abs_diff(*y));
            }
        }
        for ((d, s), (t, f)) in row.chunks_exact_mut(c).zip(out.as_chunks::<3>().0).zip(
            tol.as_chunks_mut::<4>()
                .0
                .iter_mut()
                .zip(far.as_chunks::<3>().0),
        ) {
            d[..3].copy_from_slice(s);
            for k in 0..3 {
                t[k] = f[k].saturating_add(2);
            }
        }
    }
    let bitmap = Bitmap {
        width: b.width,
        height: b.height,
        channels: b.channels,
        bits: 8,
        samples,
    };
    Ok((bitmap, tolerance))
}

/// A bitmap as 8-bit RGBA: gray spread to RGB, an opaque alpha where there is none, 16-bit
/// samples rounded to 8 bits.
fn rgba8(b: &Bitmap) -> Vec<u8> {
    let c = b.channels as usize;
    let n = b.width as usize * b.height as usize;
    let sample = |i: usize| -> u8 {
        if b.bits == 16 {
            let v = u16::from_le_bytes([b.samples[2 * i], b.samples[2 * i + 1]]) as u32;
            ((v * 255 + 32767) / 65535) as u8
        } else {
            b.samples[i]
        }
    };
    let mut out = Vec::with_capacity(n * 4);
    for p in 0..n {
        let s = |k: usize| sample(p * c + k);
        out.extend_from_slice(&match c {
            1 => [s(0), s(0), s(0), 255],
            2 => [s(0), s(0), s(0), s(1)],
            3 => [s(0), s(1), s(2), 255],
            _ => [s(0), s(1), s(2), s(3)],
        });
    }
    out
}

/// Largest per-sample difference, mean difference per sample, and pixels with any difference,
/// between two RGBA8 images of one size.
fn diff_stats(a: &[u8], b: &[u8]) -> (u8, f64, u64) {
    let (mut max, mut sum, mut pixels) = (0u8, 0u64, 0u64);
    for (x, y) in a.as_chunks::<4>().0.iter().zip(b.as_chunks::<4>().0) {
        let mut any = false;
        for k in 0..4 {
            let d = x[k].abs_diff(y[k]);
            max = max.max(d);
            sum += u64::from(d);
            any |= d != 0;
        }
        pixels += u64::from(any);
    }
    (max, sum as f64 / a.len().max(1) as f64, pixels)
}

const COMPARE_HEADER: &str = "reference\toutput\tstatus\twidth\theight\tchannels\tbits\txxh3\t\
rgba8_xxh3\tsame\tmax_diff\tmean_diff\tdiff_pixels\talt_same\talt_max_diff\terror";

/// An alternate reference's size and RGBA8 samples, with each sample's tolerance for a converted
/// one (`srgb_of`), or why it didn't decode.
type AltReference = Result<(u32, u32, Vec<u8>, Option<Vec<u8>>), String>;

/// One reference and the outputs compared with it.
fn compare_group(reference: &str, outputs: &[(String, Option<String>)]) -> Vec<String> {
    let want = reference_bitmap(reference);
    let want_rgba = want.as_ref().ok().map(rgba8);
    let mut alts: std::collections::HashMap<String, AltReference> =
        std::collections::HashMap::new();
    let mut stored: Option<Result<(u32, u32, Vec<u8>), String>> = None;
    outputs
        .iter()
        .map(|(out, alt)| {
            let line = |rest: String| format!("{reference}\t{out}\t{rest}");
            let want = match (&want, &want_rgba) {
                (Ok(w), Some(r)) => (w, r),
                _ => {
                    let e = want.as_ref().err().cloned().unwrap_or_default();
                    return line(format!("error{}\treference: {e}", "\t".repeat(12)));
                }
            };
            let got = std::fs::read(out)
                .map_err(|e| e.to_string())
                .and_then(|d| {
                    let o = zencodecs::DecodeRequest::new(&d)
        .with_limits(&limits())
                        .with_format(zencodec::ImageFormat::Png)
                        .decode_full_frame()
                        .map_err(|e| format!("zenpng: {e}"))?;
                    zen_bitmap(&o.pixels())
                });
            let got = match got {
                Ok(g) => g,
                Err(e) => return line(format!("error{}\t{}", "\t".repeat(12), e.replace(['\t', '\n'], " "))),
            };
            let got_rgba = rgba8(&got);
            let (w, h) = (got.width, got.height);
            let same = if (w, h) != (want.0.width, want.0.height) {
                "size"
            } else if (got.channels, got.bits, &got.samples) == (want.0.channels, want.0.bits, &want.0.samples) {
                "native"
            } else if got_rgba == *want.1 {
                "rgba8"
            } else {
                "no"
            };
            let mut stats = (same != "size").then(|| diff_stats(&got_rgba, want.1));
            // A reader that leaves a JPEG XL file's orientation to the caller: compared with our
            // decode in the stored orientation, it is `stored` when that is the closer match.
            let mut same = same;
            if reference.ends_with(".jxl") && (same == "size" || stats.is_some_and(|s| s.0 > 6)) {
                let s = stored.get_or_insert_with(|| {
                    stored_bitmap(reference).map(|b| (b.width, b.height, rgba8(&b)))
                });
                if let Ok((sw, sh, sr)) = s
                    && (*sw, *sh) == (w, h)
                {
                    let st = diff_stats(&got_rgba, sr);
                    if stats.is_none_or(|x| st.0 < x.0) {
                        same = "stored";
                        stats = Some(st);
                    }
                }
            }
            let (max, mean, pixels) = match stats {
                None => (String::new(), String::new(), String::new()),
                Some((m, a, p)) => (m.to_string(), format!("{a:.4}"), p.to_string()),
            };
            let (alt_same, alt_max) = match alt {
                None => (String::new(), String::new()),
                Some(a) => {
                    let r = alts.entry(a.clone()).or_insert_with(|| match a.strip_prefix("=srgb:") {
                        Some(colour) => srgb_of(want.0, colour)
                            .map(|(b, t)| (b.width, b.height, rgba8(&b), Some(t))),
                        None => reference_bitmap(a).map(|b| (b.width, b.height, rgba8(&b), None)),
                    });
                    match r {
                        Ok((aw, ah, ar, tol)) if (*aw, *ah) == (w, h) => {
                            let (m, _, _) = diff_stats(&got_rgba, ar);
                            let within = |t: &Vec<u8>| {
                                got_rgba.iter().zip(ar.iter()).zip(t).all(|((x, y), t)| x.abs_diff(*y) <= *t)
                            };
                            let same = if *ar == got_rgba {
                                "yes"
                            } else if tol.as_ref().is_some_and(within) {
                                "within"
                            } else {
                                "no"
                            };
                            (same.to_string(), m.to_string())
                        }
                        Ok(_) => ("size".to_string(), String::new()),
                        Err(e) => (format!("error: {e}"), String::new()),
                    }
                }
            };
            line(format!(
                "ok\t{w}\t{h}\t{}\t{}\t{}\t{:016x}\t{same}\t{max}\t{mean}\t{pixels}\t{alt_same}\t{alt_max}\t",
                got.channels,
                got.bits,
                got.xxh3(),
                xxh3_64(&got_rgba)
            ))
        })
        .collect()
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mode = args.first().map(String::as_str).unwrap_or("");
    let mut jobs = 8usize;
    let mut gm_dir: Option<PathBuf> = None;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--jobs" => {
                jobs = args
                    .get(i + 1)
                    .and_then(|v| v.parse().ok())
                    .unwrap_or_else(|| usage());
                i += 2;
            }
            "--gainmap-dir" => {
                gm_dir = Some(PathBuf::from(args.get(i + 1).unwrap_or_else(|| usage())));
                i += 2;
            }
            _ => usage(),
        }
    }
    rayon::ThreadPoolBuilder::new()
        .num_threads(jobs)
        .build_global()
        .unwrap();
    let lines: Vec<String> = std::io::stdin()
        .lock()
        .lines()
        .map_while(Result::ok)
        .filter(|l| !l.is_empty())
        .collect();
    let out = Mutex::new(std::io::stdout());
    let failures = std::sync::atomic::AtomicUsize::new(0);
    let emit = |s: String| {
        let mut o = out.lock().unwrap();
        writeln!(o, "{s}").unwrap();
        o.flush().unwrap();
    };
    match mode {
        "jxl" | "png" => {
            emit(HEADER.to_string());
            lines.par_iter().for_each(|p| {
                let data = match std::fs::read(p) {
                    Ok(d) => d,
                    Err(e) => {
                        let row = Row {
                            status: "error",
                            error: format!("read: {e}"),
                            ..Row::default()
                        };
                        emit(row.line(p, if mode == "png" { "zenpng" } else { "zenjxl" }));
                        failures.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                        return;
                    }
                };
                let rows: Vec<(&str, Row)> = if mode == "png" {
                    vec![("zenpng", png_row(&data))]
                } else {
                    vec![("zenjxl", zen_row(&data)), ("jxl-rs", jxlrs_row(&data))]
                };
                for (decoder, mut row) in rows {
                    if let (Some(dir), Some(j)) = (&gm_dir, &row.jhgm)
                        && let Some(Ok(b)) = &j.gm
                    {
                        let name = Path::new(p)
                            .file_name()
                            .unwrap()
                            .to_string_lossy()
                            .to_string();
                        if let Err(e) = write_gainmap(dir, decoder, &name, b, &j.metadata) {
                            row.error = format!("write gain map: {e}");
                        }
                    }
                    let bad = row.status != "ok"
                        || !row.error.is_empty()
                        || row
                            .jhgm
                            .as_ref()
                            .is_some_and(|j| !matches!(j.gm, Some(Ok(_))));
                    if bad {
                        failures.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    }
                    emit(row.line(p, decoder));
                }
            });
        }
        "compare" => {
            emit(COMPARE_HEADER.to_string());
            let mut groups: std::collections::BTreeMap<String, Vec<(String, Option<String>)>> =
                std::collections::BTreeMap::new();
            for l in &lines {
                let mut f = l.split('\t');
                let (Some(r), Some(o)) = (f.next(), f.next()) else {
                    usage()
                };
                let alt = f.next().filter(|a| !a.is_empty()).map(String::from);
                groups
                    .entry(r.to_string())
                    .or_default()
                    .push((o.to_string(), alt));
            }
            let groups: Vec<_> = groups.into_iter().collect();
            groups.par_iter().for_each(|(r, outs)| {
                for line in compare_group(r, outs) {
                    if line.split('\t').nth(2) != Some("ok") {
                        failures.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    }
                    emit(line);
                }
            });
        }
        "hdr" => {
            emit("jxl\thdr_png\tdecoder\tstatus\twidth\theight\tpq10_p50\tpq10_p999\tpq10_max\tstops_p50\tstops_p999\tstops_max\tsamples_over_5pct\terror".into());
            lines.par_iter().for_each(|l| {
                let (j, p) = l.split_once('\t').unwrap_or_else(|| usage());
                let line = hdr_line(j, p);
                if !line.split('\t').nth(3).is_some_and(|s| s == "ok") {
                    failures.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                }
                emit(line);
            });
        }
        _ => usage(),
    }
    let n = failures.load(std::sync::atomic::Ordering::Relaxed);
    eprintln!("{} inputs, {n} rows with errors", lines.len());
    std::process::exit(if n == 0 { 0 } else { 1 });
}

fn usage() -> ! {
    eprintln!(
        "usage: jxl-decode-check jxl [--jobs N] [--gainmap-dir DIR] < paths\n       \
         jxl-decode-check png [--jobs N] < paths\n       \
         jxl-decode-check compare [--jobs N] < lines (reference TAB output.png [TAB alternate])\n       \
         jxl-decode-check hdr [--jobs N] < pairs (jxl TAB hdr.png)"
    );
    std::process::exit(2)
}
