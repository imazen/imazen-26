//! The HDR pass: a 16-bit PQ render of every gain-map source (EXPORT-PLAN.md, "HDR"),
//! written as `png-p3/<stem>_<W>x<H>.hdr.png` beside the source's SDR `png-p3` file.
//!
//! - The SDR base is the same decode the SDR layers use (displayed orientation, code values).
//! - The gain map comes from the source's own codec: zencodecs' UltraHDR reader for JPEG,
//!   heic for HEIC (an ISO 21496-1 `tmap`, or Apple's legacy auxiliary image with its headroom
//!   in the EXIF MakerNote). It is oriented like the base (see [`orient_gain_map`]).
//! - ISO 21496-1 gain maps are applied by ultrahdr-core's `apply_gainmap` at the map's full
//!   headroom. Apple's legacy maps use Apple's own curve, `1 + (H - 1) * sRGB_EOTF(g)` for a
//!   stored value g (H the MakerNote headroom), which ISO parameters only approximate
//!   (heic#62), sampled exactly as ultrahdr-core samples ISO maps ([`sample_gains`]): gains
//!   blended with Shepard's weights at corner-aligned gain-map coordinates, as libultrahdr
//!   aligns them (it blends the stored values instead; on 11064 that differs by 0.011 stops
//!   at the 99.9th percentile).
//! - Linear 1.0 is SDR diffuse white at 203 nits (BT.2408). PQ is SMPTE ST 2084 computed in
//!   f64 and rounded to 16 bits. Primaries stay Display P3: `cICP` 12/16/0/1.
//! - `cLLI` holds MaxCLL and MaxFALL measured on the written code values (each pixel's
//!   largest channel, in nits, 0.0001 resolution): the maximum and the mean over the image.
//! - The same provenance `tEXt` chunk as the SDR files; zenpng at effort 22; every file is
//!   decoded again and must hold exactly the written samples, `cICP`, `cLLI` and text.

use std::fs;
use std::path::Path;

use enough::Unstoppable;
use sha2::{Digest, Sha256};
use ultrahdr_core::gainmap::{HdrOutputFormat, apply_gainmap};
use ultrahdr_core::{GainMap, GainMapMetadata};
use zencodec::{Cicp, Metadata, Orientation};
use zenpixels::{ColorPrimaries, PixelBuffer, PixelDescriptor, TransferFunction};
use zenpng::{Compression, EncodeConfig};

use super::{Colour, EFFORT, Row, Source, TEXT_KEYWORD, hex, load};

/// SDR diffuse white, in nits, that linear 1.0 stands for (BT.2408).
const SDR_WHITE_NITS: f64 = 203.0;

/// The report columns of `png-hdr`.
pub(crate) const HDR_HEADER: &str = "id\tlayer\tpath\twidth\theight\tcolour\tgain_map\tgain_map_size\tgain_map_orientation\theadroom_stops\tdiffuse_white_nits\tmax_cll\tmax_fall\tbytes\tsha256\trgb16_sha256\terror";

/// The report columns of `hdr-info`.
pub(crate) const INFO_HEADER: &str = "id\tsource_orientation\twidth\theight\tgain_map\tgain_map_size\tchannels\taspect\theadroom_stops\tparams\terror";

/// How a gain map scales linear light.
pub(crate) enum Curve {
    /// ISO 21496-1 parameters, applied by ultrahdr-core.
    Iso(GainMapMetadata),
    /// Apple's legacy curve, with the MakerNote headroom in stops.
    Apple { stops: f64 },
}

impl Curve {
    fn headroom_stops(&self) -> f64 {
        match self {
            Curve::Iso(m) => m.alternate_hdr_headroom,
            Curve::Apple { stops } => *stops,
        }
    }
}

/// The gain map as its codec decodes it, with how it scales the base.
fn decode_gain_map(data: &[u8], source: &str) -> Result<(GainMap, Curve, &'static str), String> {
    let ext = source.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "jpg" | "jpeg" => {
            let (_, gm) = zencodecs::DecodeRequest::new(data)
                .decode_gain_map()
                .map_err(|e| format!("gain map decode: {e}"))?;
            let gm = gm.ok_or("no gain map")?;
            if gm.base_is_hdr {
                return Err("the base image is the HDR rendition".into());
            }
            Ok((gm.gain_map, Curve::Iso(gm.metadata), "jpeg-iso21496"))
        }
        "heic" | "heif" => {
            let cfg = heic::DecoderConfig::new();
            let g = cfg
                .decode_gain_map(data)
                .map_err(|e| format!("gain map decode: {e:?}"))?;
            let map = GainMap {
                width: g.width,
                height: g.height,
                channels: 1,
                data: g.data,
            };
            match g.origin {
                heic::GainMapOrigin::HeifTmap => {
                    let iso = g.iso21496.ok_or("tmap without its ISO 21496-1 payload")?;
                    let params = ultrahdr_core::parse_iso21496_fmt(
                        &iso,
                        ultrahdr_core::Iso21496Format::AvifTmap,
                    )
                    .map_err(|e| format!("tmap payload: {e:?}"))?;
                    params
                        .validate()
                        .map_err(|e| format!("tmap payload: {e:?}"))?;
                    if params.direction() != zencodec::gainmap::GainMapDirection::BaseIsSdr {
                        return Err("the base image is the HDR rendition".into());
                    }
                    Ok((map, Curve::Iso(params), "heic-tmap"))
                }
                heic::GainMapOrigin::AppleAuxItem => {
                    let exif = cfg
                        .extract_exif(data)
                        .map_err(|e| format!("EXIF: {e:?}"))?
                        .ok_or("legacy Apple gain map without EXIF")?;
                    let stops = ultrahdr_core::parse_exif_for_apple_hdr(&exif)
                        .and_then(|i| i.headroom_stops())
                        .ok_or("legacy Apple gain map without a MakerNote headroom")?;
                    Ok((map, Curve::Apple { stops }, "heic-apple-legacy"))
                }
                other => Err(format!("unknown gain-map origin {other:?}")),
            }
        }
        _ => Err(format!("no gain-map decode for .{ext}")),
    }
}

/// The orientation the source asks for, as zencodecs reads it (EXIF, or HEIF `irot`/`imir`).
fn source_orientation(data: &[u8]) -> Result<Orientation, String> {
    Ok(zencodecs::from_bytes(data)
        .map_err(|e| format!("probe: {e}"))?
        .orientation)
}

/// Whether two sizes have the same aspect ratio, to within 2%.
fn same_aspect(a: (f64, f64), b: (f64, f64)) -> bool {
    ((a.0 / a.1) / (b.0 / b.1) - 1.0).abs() < 0.02
}

/// Orient the gain map like the displayed base. A decoder may hand the map over as stored
/// (the JPEG secondary image) or already transformed, and the aspect ratio tells which when
/// the orientation swaps the axes; for other orientations the two are indistinguishable, so
/// those are refused rather than guessed (none of the corpus HDR sources has one).
fn orient_gain_map(
    map: GainMap,
    orientation: Orientation,
    base: (usize, usize),
) -> Result<(GainMap, &'static str), String> {
    let stored = (f64::from(map.width), f64::from(map.height));
    let display = (base.0 as f64, base.1 as f64);
    let as_is = same_aspect(stored, display);
    let swapped = same_aspect((stored.1, stored.0), display);
    if orientation.is_identity() {
        return if as_is {
            Ok((map, "as-stored"))
        } else {
            Err(format!(
                "gain map {}x{} does not fit the {}x{} base",
                map.width, map.height, base.0, base.1
            ))
        };
    }
    if !orientation.swaps_axes() {
        return Err(format!(
            "orientation {orientation:?}: cannot tell whether the decoder applied it to the gain map"
        ));
    }
    match (as_is, swapped) {
        (true, false) => Ok((map, "decoder-oriented")),
        (false, true) => {
            let (w, h) = (map.width, map.height);
            let (ow, oh) = orientation.output_dimensions(w, h);
            let c = usize::from(map.channels);
            let mut out = vec![0u8; map.data.len()];
            for sy in 0..h {
                for sx in 0..w {
                    let (dx, dy) = orientation.forward_map(sx, sy, w, h);
                    let s = (sy as usize * w as usize + sx as usize) * c;
                    let d = (dy as usize * ow as usize + dx as usize) * c;
                    out[d..d + c].copy_from_slice(&map.data[s..s + c]);
                }
            }
            Ok((
                GainMap {
                    width: ow,
                    height: oh,
                    channels: map.channels,
                    data: out,
                },
                "oriented-like-base",
            ))
        }
        _ => Err(format!(
            "gain map {}x{} vs base {}x{} under {orientation:?}: ambiguous",
            map.width, map.height, base.0, base.1
        )),
    }
}

fn srgb_eotf(v: f64) -> f64 {
    if v <= 0.04045 {
        v / 12.92
    } else {
        ((v + 0.055) / 1.055).powf(2.4)
    }
}

/// SMPTE ST 2084 inverse EOTF: absolute luminance in nits to a [0, 1] signal.
fn pq_from_nits(nits: f64) -> f64 {
    const M1: f64 = 2610.0 / 16384.0;
    const M2: f64 = 2523.0 / 4096.0 * 128.0;
    const C1: f64 = 3424.0 / 4096.0;
    const C2: f64 = 2413.0 / 4096.0 * 32.0;
    const C3: f64 = 2392.0 / 4096.0 * 32.0;
    let y = (nits / 10000.0).clamp(0.0, 1.0).powf(M1);
    ((C1 + C2 * y) / (1.0 + C3 * y)).powf(M2)
}

/// SMPTE ST 2084 EOTF: a [0, 1] signal to nits.
fn nits_from_pq(e: f64) -> f64 {
    const M1: f64 = 2610.0 / 16384.0;
    const M2: f64 = 2523.0 / 4096.0 * 128.0;
    const C1: f64 = 3424.0 / 4096.0;
    const C2: f64 = 2413.0 / 4096.0 * 32.0;
    const C3: f64 = 2392.0 / 4096.0 * 32.0;
    let p = e.clamp(0.0, 1.0).powf(1.0 / M2);
    10000.0 * ((p - C1).max(0.0) / (C2 - C3 * p)).powf(1.0 / M1)
}

/// Linear RGB (1.0 = SDR white), three values per pixel, from the base and the gain map.
pub(crate) fn reconstruct(
    px_rgba: Vec<u8>,
    w: usize,
    h: usize,
    map: &GainMap,
    curve: &Curve,
) -> Result<Vec<f64>, String> {
    match curve {
        Curve::Iso(meta) => {
            let desc = PixelDescriptor::RGBA8_SRGB
                .with_primaries(ColorPrimaries::DisplayP3)
                .with_transfer(TransferFunction::Srgb);
            let sdr = PixelBuffer::from_vec(px_rgba, w as u32, h as u32, desc)
                .map_err(|e| format!("base buffer: {e:?}"))?;
            let boost = ultrahdr_core::full_reconstruction_boost(meta);
            let hdr = apply_gainmap(
                &sdr,
                map,
                meta,
                boost,
                HdrOutputFormat::LinearFloat,
                Unstoppable,
            )
            .map_err(|e| format!("apply_gainmap: {e:?}"))?;
            let bytes = hdr.copy_to_contiguous_bytes();
            let f: &[f32] = bytemuck::cast_slice(&bytes);
            if f.len() != w * h * 4 {
                return Err("apply_gainmap returned an unexpected layout".into());
            }
            Ok(f.as_chunks::<4>()
                .0
                .iter()
                .flat_map(|p| [f64::from(p[0]), f64::from(p[1]), f64::from(p[2])])
                .collect())
        }
        Curve::Apple { stops } => {
            if map.channels != 1 {
                return Err("legacy Apple gain map with more than one channel".into());
            }
            // Apple's curve, sampled the way ultrahdr-core samples every ISO gain map.
            let headroom = 2f64.powf(*stops);
            let lut: Vec<f64> = (0..256)
                .map(|i| 1.0 + (headroom - 1.0) * srgb_eotf(f64::from(i) / 255.0))
                .collect();
            let gains = sample_gains(map, &lut, w, h);
            Ok(px_rgba
                .as_chunks::<4>()
                .0
                .iter()
                .zip(&gains)
                .flat_map(|(p, &g)| [0, 1, 2].map(|c| srgb_eotf(f64::from(p[c]) / 255.0) * g))
                .collect())
        }
    }
}

/// Inverse-distance (Shepard's) weights of the four gain-map samples around a point at
/// offset (`fx`, `fy`) in [0, 1) from the top-left one, ordered top-left, bottom-left,
/// top-right, bottom-right; `next_x`/`next_y` is 1, or 0 where the right or bottom sample
/// is the clamped edge sample itself.
fn shepards(fx: f64, fy: f64, next_x: f64, next_y: f64) -> [f64; 4] {
    let d = [
        fx.hypot(fy),
        fx.hypot(fy - next_y),
        (fx - next_x).hypot(fy),
        (fx - next_x).hypot(fy - next_y),
    ];
    if let Some(i) = d.iter().position(|&v| v == 0.0) {
        let mut w = [0.0; 4];
        w[i] = 1.0;
        return w;
    }
    let inv = d.map(|v| 1.0 / v);
    let total: f64 = inv.iter().sum();
    inv.map(|v| v / total)
}

/// Each pixel's gain: the gain-map values mapped through `lut`, then blended with Shepard's
/// weights at corner-aligned coordinates (pixel x lands on gain-map x * gw / w), as
/// ultrahdr-core's `apply_gainmap` samples. Like it, an integer scale weights the clamped
/// right and bottom edge samples as coinciding with their neighbours, and any other scale
/// uses the plain four-corner weights. `gain_sampling_matches_ultrahdr_core` holds this to
/// ultrahdr-core's output.
fn sample_gains(map: &GainMap, lut: &[f64], w: usize, h: usize) -> Vec<f64> {
    let (gw, gh) = (map.width as usize, map.height as usize);
    let integer = w.is_multiple_of(gw)
        && h.is_multiple_of(gh)
        && (w / gw) * (h / gh) <= ultrahdr_core::limits::MAX_SHEPARDS_TABLE_ENTRIES as usize;
    let mut out = Vec::with_capacity(w * h);
    for y in 0..h {
        let (y0, fy) = if integer {
            (y / (h / gh), (y % (h / gh)) as f64 / (h / gh) as f64)
        } else {
            let g = (y as f32 * (1.0 / h as f32)) * gh as f32;
            (g.floor() as usize, f64::from(g - g.floor()))
        };
        let y0 = y0.min(gh - 1);
        let y1 = (y0 + 1).min(gh - 1);
        for x in 0..w {
            let (x0, fx) = if integer {
                (x / (w / gw), (x % (w / gw)) as f64 / (w / gw) as f64)
            } else {
                let g = (x as f32 * (1.0 / w as f32)) * gw as f32;
                (g.floor() as usize, f64::from(g - g.floor()))
            };
            let x0 = x0.min(gw - 1);
            let x1 = (x0 + 1).min(gw - 1);
            let (next_x, next_y) = if integer {
                (
                    if x0 == x1 { 0.0 } else { 1.0 },
                    if y0 == y1 { 0.0 } else { 1.0 },
                )
            } else {
                (1.0, 1.0)
            };
            let wt = shepards(fx, fy, next_x, next_y);
            let at = |xx: usize, yy: usize| lut[usize::from(map.data[yy * gw + xx])];
            out.push(
                wt[0] * at(x0, y0) + wt[1] * at(x0, y1) + wt[2] * at(x1, y0) + wt[3] * at(x1, y1),
            );
        }
    }
    out
}

/// A HEIC source's gain-map form for JPEG XL (`jhgm`, ISO 21496-1), with what it stands for.
pub(crate) struct JhgmForm {
    /// The gain map as written: oriented like the displayed base, ISO-form values.
    pub(crate) map: GainMap,
    pub(crate) meta: GainMapMetadata,
    pub(crate) kind: &'static str,
    /// The source's own gain map and curve, oriented alike, to compare the HDR against.
    pub(crate) source_map: GainMap,
    pub(crate) source_curve: Curve,
}

/// The `jhgm` form of a HEIC source with a gain map; `None` for any other source. A `tmap`
/// gain map is already ISO 21496-1 and goes in as it is. Apple's legacy map is re-quantized
/// onto an ISO curve with min 0, max = the headroom H in stops, gamma 1 and no offsets: each
/// stored value g becomes round(255 * log2(1 + (H - 1) * sRGB_EOTF(g / 255)) / H), within half
/// a code step (H / 510 stops) of Apple's curve.
pub(crate) fn jhgm_form(
    data: &[u8],
    source: &str,
    base: (usize, usize),
) -> Result<Option<JhgmForm>, String> {
    let ext = source.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    if !matches!(ext.as_str(), "heic" | "heif") {
        return Ok(None);
    }
    let info = heic::ImageInfo::from_bytes(data).map_err(|e| format!("heic probe: {e:?}"))?;
    if !info.has_gain_map {
        return Ok(None);
    }
    let (map, curve, _) = decode_gain_map(data, source)?;
    let (map, _) = orient_gain_map(map, source_orientation(data)?, base)?;
    match curve {
        Curve::Iso(meta) => Ok(Some(JhgmForm {
            map: map.clone(),
            meta: meta.clone(),
            kind: "heic-tmap",
            source_map: map,
            source_curve: Curve::Iso(meta),
        })),
        Curve::Apple { stops } => {
            let headroom = 2f64.powf(stops);
            let lut: Vec<u8> = (0..256)
                .map(|g| {
                    let l = (1.0 + (headroom - 1.0) * srgb_eotf(f64::from(g) / 255.0)).log2();
                    (255.0 * l / stops).round().clamp(0.0, 255.0) as u8
                })
                .collect();
            let iso = GainMap {
                width: map.width,
                height: map.height,
                channels: 1,
                data: map.data.iter().map(|&g| lut[usize::from(g)]).collect(),
            };
            let mut meta = GainMapMetadata::default();
            meta.base_hdr_headroom = 0.0;
            meta.alternate_hdr_headroom = stops;
            for c in &mut meta.channels {
                c.min = 0.0;
                c.max = stops;
                c.gamma = 1.0;
                c.base_offset = 0.0;
                c.alternate_offset = 0.0;
            }
            Ok(Some(JhgmForm {
                map: iso,
                meta,
                kind: "heic-apple-legacy-as-iso",
                source_map: map,
                source_curve: Curve::Apple { stops },
            }))
        }
    }
}

/// The source's SDR base and gain map, oriented alike; shared by `hdr-info` and `png-hdr`.
struct Prepared {
    source: Source,
    orientation: Orientation,
    map: GainMap,
    stored: (u32, u32),
    curve: Curve,
    kind: &'static str,
    placement: &'static str,
}

fn prepare(row: &Row) -> Result<Prepared, String> {
    let data = fs::read(row.source).map_err(|e| format!("read: {e}"))?;
    let orientation = source_orientation(&data)?;
    let (map, curve, kind) = decode_gain_map(&data, row.source)?;
    let stored = (map.width, map.height);
    let source = load(row)?;
    if source.colour != Colour::DisplayP3 {
        return Err(format!(
            "HDR base is {}, not Display P3",
            source.colour.name()
        ));
    }
    let (map, placement) = orient_gain_map(map, orientation, (source.w, source.h))?;
    Ok(Prepared {
        source,
        orientation,
        map,
        stored,
        curve,
        kind,
        placement,
    })
}

fn params_summary(curve: &Curve) -> String {
    match curve {
        // Full precision: the oracle reads these back, and Apple's tmap offsets are tiny.
        Curve::Iso(m) => {
            let c = &m.channels[0];
            format!(
                "base {:e} alt {:e}; min {:e} max {:e} gamma {:e} offsets {:e}/{:e}",
                m.base_hdr_headroom,
                m.alternate_hdr_headroom,
                c.min,
                c.max,
                c.gamma,
                c.base_offset,
                c.alternate_offset,
            )
        }
        Curve::Apple { stops } => format!("apple legacy, headroom {stops:e} stops"),
    }
}

/// `hdr-info`: what the HDR pass would use, without writing anything.
pub(crate) fn info(row: &Row, _out: &Path) -> Result<Vec<String>, String> {
    let p = prepare(row)?;
    Ok(vec![format!(
        "{}\t{:?}\t{}\t{}\t{}\t{}x{}\t{}\t{}\t{:.3}\t{}\t",
        row.id,
        p.orientation,
        p.source.w,
        p.source.h,
        p.kind,
        p.stored.0,
        p.stored.1,
        p.map.channels,
        p.placement,
        p.curve.headroom_stops(),
        params_summary(&p.curve),
    )])
}

/// `png-hdr`: write the 16-bit PQ render.
pub(crate) fn render(row: &Row, out_dir: &Path) -> Result<Vec<String>, String> {
    if !row.provenance.is_ascii() {
        return Err("provenance JSON must be ASCII (escape the rest as \\uXXXX)".into());
    }
    let p = prepare(row)?;
    let (w, h) = (p.source.w, p.source.h);
    let linear = reconstruct(p.source.px.rgba(), w, h, &p.map, &p.curve)?;

    let mut samples = Vec::with_capacity(w * h);
    let (mut max_cll, mut sum_fall) = (0f64, 0f64);
    for px in linear.as_chunks::<3>().0 {
        let code = px.map(|v| (pq_from_nits(v.max(0.0) * SDR_WHITE_NITS) * 65535.0).round() as u16);
        let peak = code
            .iter()
            .map(|&c| nits_from_pq(f64::from(c) / 65535.0))
            .fold(0.0, f64::max);
        max_cll = max_cll.max(peak);
        sum_fall += peak;
        samples.push(rgb::Rgb {
            r: code[0],
            g: code[1],
            b: code[2],
        });
    }
    let max_fall = sum_fall / (w * h) as f64;
    let clli = [
        (max_cll * 10000.0).round() as u32,
        (max_fall * 10000.0).round() as u32,
    ];
    let cicp = Cicp::new(12, 16, 0, true);
    let cfg = EncodeConfig::default()
        .with_compression(Compression::Effort(EFFORT))
        .with_text(TEXT_KEYWORD, row.provenance)
        .with_cicp(Some(cicp))
        .with_content_light_level_raw(Some(clli));
    let png = zenpng::encode_rgb16(
        imgref::Img::new(&samples[..], w, h),
        Some(&Metadata::default()),
        &cfg,
        &Unstoppable,
        &Unstoppable,
    )
    .map_err(|e| format!("encode: {e:?}"))?;

    // Decode again: samples, cICP, cLLI and the provenance text must come back unchanged.
    let d = zenpng::decode(
        &png,
        &zenpng::PngDecodeConfig::default().with_max_pixels(1_000_000_000),
        &Unstoppable,
    )
    .map_err(|e| format!("re-decode: {e:?}"))?;
    let back = d.pixels.copy_to_contiguous_bytes();
    let want: Vec<u8> = samples
        .iter()
        .flat_map(|s| [s.r, s.g, s.b])
        .flat_map(u16::to_ne_bytes)
        .collect();
    if (d.info.width as usize, d.info.height as usize) != (w, h) || back != want {
        return Err(format!("PIXELS DIFFER ({:?})", d.pixels.descriptor()));
    }
    if d.info.cicp != Some(cicp) {
        return Err(format!("cICP read back as {:?}", d.info.cicp));
    }
    if d.info.content_light_level_raw != Some(clli) {
        return Err(format!(
            "cLLI read back as {:?}",
            d.info.content_light_level_raw
        ));
    }
    let text = &d.info.text_chunks;
    if text.len() != 1 || text[0].keyword != TEXT_KEYWORD || text[0].text != row.provenance {
        return Err("provenance text chunk missing or not the only one".into());
    }

    let name = format!("{}_{w}x{h}.hdr.png", row.stem);
    let path = out_dir.join("png-p3").join(&name);
    fs::create_dir_all(path.parent().unwrap()).map_err(|e| format!("mkdir: {e}"))?;
    fs::write(&path, &png).map_err(|e| format!("write: {e}"))?;
    Ok(vec![format!(
        "{}\tpng-p3-hdr\tpng-p3/{name}\t{w}\t{h}\tdisplay-p3-pq\t{}\t{}x{}\t{}\t{:.3}\t{SDR_WHITE_NITS}\t{:.4}\t{:.4}\t{}\t{}\t{}\t",
        row.id,
        p.kind,
        p.stored.0,
        p.stored.1,
        p.placement,
        p.curve.headroom_stops(),
        max_cll,
        max_fall,
        png.len(),
        hex(&Sha256::digest(&png)),
        hex(&Sha256::digest(&want)),
    )])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pq_round_trips_and_hits_reference_points() {
        // ST 2084 reference values: 0 nits -> c1^m2 (7.3e-7, code 0 at 16 bits), 10000 nits -> 1,
        // 100 nits -> 0.5081 (to 4 places).
        assert!((pq_from_nits(0.0) - 0.835_937_5f64.powf(78.843_75)).abs() < 1e-15);
        assert_eq!((pq_from_nits(0.0) * 65535.0).round(), 0.0);
        assert!((pq_from_nits(10000.0) - 1.0).abs() < 1e-12);
        assert!((pq_from_nits(100.0) - 0.508_08).abs() < 1e-4);
        for nits in [0.01, 1.0, 203.0, 1000.0, 4000.0] {
            assert!((nits_from_pq(pq_from_nits(nits)) - nits).abs() / nits < 1e-9);
        }
    }

    #[test]
    fn gain_sampling_matches_ultrahdr_core() {
        // The same ISO LUT through sample_gains and through apply_gainmap must give the same
        // gains, for an integer scale (4x) and a non-integer one.
        let mut meta = GainMapMetadata::default();
        for ch in &mut meta.channels {
            ch.min = 0.0;
            ch.max = 2.3;
            ch.gamma = 1.0;
            ch.base_offset = 0.0;
            ch.alternate_offset = 0.0;
        }
        meta.base_hdr_headroom = 0.0;
        meta.alternate_hdr_headroom = 2.3;
        let lut_f32 = ultrahdr_core::gainmap::GainMapLut::new(&meta, 1.0);
        let lut: Vec<f64> = (0..=255u8)
            .map(|i| f64::from(lut_f32.lookup(i, 0)))
            .collect();
        for (w, h, gw, gh) in [(64usize, 48usize, 16u32, 12u32), (50, 30, 16, 12)] {
            let data: Vec<u8> = (0..gw * gh).map(|i| ((i * 97 + 13) % 256) as u8).collect();
            let map = GainMap {
                width: gw,
                height: gh,
                channels: 1,
                data,
            };
            // A white base (linear 1.0 in both) leaves the gain itself in the output: this
            // compares the sampling, not the two sRGB decodes.
            let base = vec![255u8; w * h * 4];
            let ours = sample_gains(&map, &lut, w, h);
            let desc = PixelDescriptor::RGBA8_SRGB.with_primaries(ColorPrimaries::DisplayP3);
            let sdr = PixelBuffer::from_vec(base.clone(), w as u32, h as u32, desc).unwrap();
            let hdr = apply_gainmap(
                &sdr,
                &map,
                &meta,
                2f32.powf(2.3),
                HdrOutputFormat::LinearFloat,
                Unstoppable,
            )
            .unwrap();
            let bytes = hdr.copy_to_contiguous_bytes();
            let theirs: &[f32] = bytemuck::cast_slice(&bytes);
            for i in 0..w * h {
                for c in 0..3 {
                    let want = f64::from(theirs[i * 4 + c]);
                    let got = ours[i];
                    assert!(
                        (got - want).abs() <= 1e-5 * want.max(1e-3),
                        "{w}x{h} px {i} ch {c}: {got} vs {want}"
                    );
                }
            }
        }
    }

    #[test]
    fn gain_map_orientation_follows_the_base() {
        // A 4x2 stored map whose base displays as 2x4 under Rotate90: rotated like the base.
        let map = GainMap {
            width: 4,
            height: 2,
            channels: 1,
            data: (0..8).collect(),
        };
        let (m, how) = orient_gain_map(map.clone(), Orientation::Rotate90, (200, 400)).unwrap();
        assert_eq!((m.width, m.height, how), (2, 4, "oriented-like-base"));
        let mut expect = vec![0u8; 8];
        for sy in 0..2 {
            for sx in 0..4 {
                let (dx, dy) = Orientation::Rotate90.forward_map(sx, sy, 4, 2);
                expect[(dy * 2 + dx) as usize] = map.data[(sy * 4 + sx) as usize];
            }
        }
        assert_eq!(m.data, expect);
        // Already oriented by the decoder: kept.
        let (m, how) = orient_gain_map(map.clone(), Orientation::Rotate90, (400, 200)).unwrap();
        assert_eq!((m.width, how), (4, "decoder-oriented"));
        // A 180-degree turn can't be told apart from none: refused.
        assert!(orient_gain_map(map, Orientation::Rotate180, (400, 200)).is_err());
    }
}
