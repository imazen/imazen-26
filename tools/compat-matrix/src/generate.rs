//! Fixture generation: encode the test pattern through every imazen encoder
//! with each signalling variant, plus byte-level container edits, then emit
//! the manifest + hypothesis tables.
//!
//! All files are written by imazen code: zen* encoders for codestreams, this
//! crate's writers for ICC/EXIF/container surgery. Third-party encoders never
//! touch a fixture byte.

use crate::exif::{self, ExifSpec};
use crate::heif::{self, Demux, RemuxSignalling};
use crate::icc;
use crate::jpeg;
use crate::jxl;
use crate::manifest::{Colour, FixtureRow, Hyp, synth_colour_hyps, synth_orient_hyps};
use crate::pattern;
use crate::png;
use crate::{Rgb16, orient_display};

use rgb::FromSlice;
use sha2::{Digest, Sha256};
use std::fmt::Write as _;
use std::path::{Path, PathBuf};

/// (fixture id, declared colour, ICC bytes, EXIF spec, description)
type ColorCase<'a> = (&'a str, Colour, Option<&'a [u8]>, Option<ExifSpec>, &'a str);
/// (id, class, colour, encoder config, description, orientation, hyps)
type AvifCase = (
    &'static str,
    &'static str,
    Colour,
    zenavif::EncoderConfig,
    &'static str,
    u8,
    Vec<Hyp>,
);

pub fn sha256_hex_pub(d: &[u8]) -> String {
    sha256_hex(d)
}

fn sha256_hex(d: &[u8]) -> String {
    let mut s = String::with_capacity(64);
    for b in Sha256::digest(d) {
        let _ = write!(s, "{b:02x}");
    }
    s
}

// Canonical read-only copy of the archived-serializer AVIF on block storage;
// see assets/tmap-archived-serializer.pointer.md. Fails loudly on absence or
// hash mismatch — a silently skipped fixture would corrupt the matrix.
const ARCHIVED_TMAP_PATH: &str =
    "/mnt/v/output/imazen-26-compat/fixtures-archive/tmap-archived-serializer.avif";
const ARCHIVED_TMAP_SHA256: &str =
    "0dcffa65716e4d062ac60538f1e4dd6608dd73e835f7467aa037e7368f3d3d18";

/// Pinned HEIC remux donor (round-10 M-1): the canonical corpus copy the
/// census measures — `1000-lilith-photos-general/1071_…_ip8plus_…_4032x3024.heic`
/// under the corpus root. Other copies of the same filename differ in item
/// payloads (XMP mime item, thumbnail `colr prof` length) and produce
/// different fixtures; `generate` refuses any other sha. Recorded on every
/// HEIC row's `donor_sha` and in the result pointers.
pub const HEIC_DONOR_SHA256: &str =
    "4a5679749537b67e44d726c13a85c1be2b8af5054f22de62c7517ab0c8eb1c28";

fn archived_tmap_bytes() -> Vec<u8> {
    let bytes = std::fs::read(ARCHIVED_TMAP_PATH).unwrap_or_else(|e| {
        panic!("cannot read archived tmap fixture at {ARCHIVED_TMAP_PATH}: {e}")
    });
    let hash = sha256_hex(&bytes);
    assert_eq!(
        hash, ARCHIVED_TMAP_SHA256,
        "archived tmap fixture at {ARCHIVED_TMAP_PATH} has sha256 {hash}, \
         expected {ARCHIVED_TMAP_SHA256}"
    );
    bytes
}

struct Sink {
    dir: PathBuf,
    rows: Vec<FixtureRow>,
    /// Set while the HEIC family runs: every row it emits records the pinned
    /// donor sha (round-10 M-1 donor provenance on the manifest).
    donor_sha: String,
}

impl Sink {
    fn emit(&mut self, mut row: FixtureRow, bytes: &[u8]) {
        row.donor_sha.clone_from(&self.donor_sha);
        let path = self.dir.join(&row.file);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, bytes).unwrap();
        self.rows.push(row);
    }

    /// A precomputed hypothesis render: the generator holds the true linear
    /// HDR buffer for UltraHDR fixtures, so `gainmap-applied` is emitted
    /// from that buffer directly — decoder-independent ground truth rather
    /// than a reconstruction (probe --hdr can't parse ISO 21496-1 APP2
    /// params; trusting it there silently collapses the hyp to `stored`).
    fn emit_hyp_asset(&mut self, id: &str, hyp: &str, png_bytes: &[u8]) {
        let path = self.dir.join("hyps").join(id).join(format!("{hyp}.png"));
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, png_bytes).unwrap();
    }
}

#[allow(clippy::too_many_arguments)]
fn row(
    id: &str,
    class: &str,
    file: &str,
    w: u32,
    h: u32,
    expect_orient: u8,
    colour: Colour,
    gainmap: &str,
    desc: &str,
    bytes: &[u8],
    hyps: Vec<Hyp>,
) -> FixtureRow {
    FixtureRow {
        id: id.to_string(),
        class: class.to_string(),
        file: file.to_string(),
        w,
        h,
        expect_orient,
        colour,
        gainmap: gainmap.to_string(),
        signal_desc: desc.to_string(),
        sha256: sha256_hex(bytes),
        donor_sha: String::new(),
        hyps,
        expect: expect::expect_tokens(id, file),
    }
}

// ---------------------------------------------------------------- encoders

fn jpeg_encode(
    img: &Rgb16,
    icc: Option<&[u8]>,
    exif: Option<ExifSpec>,
    xmp: Option<&[u8]>,
) -> Vec<u8> {
    use zenjpeg::encoder::{ChromaSubsampling, EncoderConfig, Exif};
    // Baseline sequential at q95 by default (the camera-photo case);
    // jpeg-progressive is the sole progressive fixture.
    let cfg = EncoderConfig::ycbcr(95.0, ChromaSubsampling::None).progressive(false);
    let mut req = cfg.request();
    if let Some(p) = icc {
        req = req.icc_profile(p);
    }
    if let Some(e) = exif {
        req = req.exif(Exif::raw(exif::build_tiff(&e)));
    }
    if let Some(x) = xmp {
        req = req.xmp(x);
    }
    let px8 = img.to_rgb8();
    req.encode(px8.as_rgb(), img.w, img.h).expect("jpeg encode")
}

fn png_encode(
    img: &Rgb16,
    depth16: bool,
    meta: Option<zencodec::Metadata>,
    mut cfg: zenpng::EncodeConfig,
) -> Vec<u8> {
    // Keep the encoder deterministic: 1 thread, effort default.
    cfg.parallel = false;
    let meta_ref = meta.as_ref();
    let res = if depth16 {
        let px: Vec<rgb::Rgb<u16>> = img
            .px
            .as_chunks::<3>()
            .0
            .iter()
            .map(|c| rgb::Rgb {
                r: c[0],
                g: c[1],
                b: c[2],
            })
            .collect();
        zenpng::encode_rgb16(
            imgref::ImgRef::new(&px, img.w as usize, img.h as usize),
            meta_ref,
            &cfg,
            &enough::Unstoppable,
            &enough::Unstoppable,
        )
    } else {
        let px: Vec<rgb::Rgb<u8>> = img
            .to_rgb8()
            .as_chunks::<3>()
            .0
            .iter()
            .map(|c| rgb::Rgb {
                r: c[0],
                g: c[1],
                b: c[2],
            })
            .collect();
        zenpng::encode_rgb8(
            imgref::ImgRef::new(&px, img.w as usize, img.h as usize),
            meta_ref,
            &cfg,
            &enough::Unstoppable,
            &enough::Unstoppable,
        )
    };
    res.expect("png encode")
}

fn webp_encode(img: &Rgb16, icc: Option<&[u8]>, exif: Option<Vec<u8>>) -> Vec<u8> {
    let cfg = zenwebp::LosslessConfig::new().with_quality(90.0);
    let px = img.to_rgb8();
    let mut req =
        zenwebp::EncodeRequest::lossless(&cfg, &px, zenwebp::PixelLayout::Rgb8, img.w, img.h);
    if let Some(p) = icc {
        req = req.with_icc_profile(p);
    }
    if let Some(e) = exif.as_deref() {
        req = req.with_exif(e);
    }
    req.encode().expect("webp encode")
}

fn avif_encode(img: &Rgb16, cfg: &zenavif::EncoderConfig) -> Vec<u8> {
    let px: Vec<rgb::Rgb<u8>> = img
        .to_rgb8()
        .as_chunks::<3>()
        .0
        .iter()
        .map(|c| rgb::Rgb {
            r: c[0],
            g: c[1],
            b: c[2],
        })
        .collect();
    let imgref = imgref::ImgRef::new(&px, img.w as usize, img.h as usize);
    zenavif::encode_rgb8(
        imgref,
        cfg,
        almost_enough::StopToken::new(almost_enough::Unstoppable),
    )
    .expect("avif encode")
    .avif_file
}

fn jxl_encode(
    img: &Rgb16,
    meta: &jxl_encoder::api::ImageMetadata<'_>,
    ce: jxl_encoder::ColorEncoding,
    bare: bool,
    trigger_extra_fields: bool,
) -> Vec<u8> {
    let cfg = jxl_encoder::LosslessConfig::new().with_container_mode(if bare {
        jxl_encoder::ContainerMode::Never
    } else {
        jxl_encoder::ContainerMode::Auto
    });
    let req = cfg
        .encode_request(img.w, img.h, jxl_encoder::PixelLayout::Rgb8)
        .with_metadata(meta)
        .with_color_encoding(ce);
    // jxl-encoder has no public orientation API, and the public
    // `extra_fields` trigger that doesn't corrupt the header is the
    // tone-mapping bundle: `with_intrinsic_size` writes intrinsic dims
    // as two plain u2S values where spec/jxl-rs expect a full Size
    // bundle (small bit + ratio selector) — desyncing every decoder.
    // `relative_to_max_display=true` flips extra_fields on while
    // writing a fully-parsable ToneMapping bundle; semantic effect on
    // an SDR image is nil (intensity/min/linear stay default).
    let req = if trigger_extra_fields {
        req.with_relative_to_max_display(true)
    } else {
        req
    };
    let out = req.encode(&img.to_rgb8()).expect("jxl encode");
    if bare { out } else { jxl_container_wrap(out) }
}

/// Wrap a bare codestream via the encoder's own container writer (signature,
/// ftyp, jxlc). ContainerMode::Always isn't honoured in this encoder rev,
/// and real .jxl files in the wild are containers — so fixtures must be too.
pub(crate) fn jxl_container_wrap(out: Vec<u8>) -> Vec<u8> {
    if out.starts_with(b"\x00\x00\x00\x0cJXL ") {
        return out;
    }
    jxl_encoder::container::wrap_in_container(&out, None, None)
}

/// Encode UltraHDR JPEG with the given gain-map signalling format. Returns
/// the JPEG bytes plus the "gainmap-applied" SDR rendition (linear HDR
/// clipped to 1.0 through the sRGB OETF) rendered from the input buffer.
fn ultrahdr_encode_fmt(
    img: &Rgb16,
    fmt: zenjpeg::ultrahdr::GainMapEncodingFormat,
) -> (Vec<u8>, Vec<u8>) {
    use ultrahdr_core::gainmap::GainMapConfig;
    // M-5: the boost lives on a dedicated mid-tone band. The old wedge ran
    // over the pattern's ~0.87-linear background, so a 4x boost clipped into
    // already-saturated white and the applied rendition was identical to the
    // base. The band is painted at ~0.25 linear (encoded ~0.537, ≈137/255)
    // in the SDR base and boosted 4x — applied output clips to 255, a ≥40
    // level separation. The SDR base is authored directly, NOT tonemapped
    // from the HDR buffer (tonemapping the boosted band lifts it back to
    // white and erases the signal).
    let in_band = |y: u32| y >= img.h / 16 && y < img.h / 3;
    const BAND_ENC: f32 = 0.537; // 0.25 linear through the sRGB OETF
    let band_u16 = (BAND_ENC * 65535.0) as u16;
    let mut f32px = Vec::with_capacity((img.w * img.h * 4) as usize);
    let mut sdr_px = Vec::with_capacity((img.w * img.h * 4) as usize);
    for y in 0..img.h {
        for x in 0..img.w {
            let [r, g, b] = if in_band(y) {
                [band_u16, band_u16, band_u16]
            } else {
                img.get(x, y)
            };
            sdr_px.extend_from_slice(&[(r >> 8) as u8, (g >> 8) as u8, (b >> 8) as u8, 255]);
            let boost = if in_band(y) { 4.0f32 } else { 1.0 };
            f32px.push((r as f32 / 65535.0) * boost);
            f32px.push((g as f32 / 65535.0) * boost);
            f32px.push((b as f32 / 65535.0) * boost);
            f32px.push(1.0f32);
        }
    }
    let bytes: Vec<u8> = f32px.iter().flat_map(|v| v.to_le_bytes()).collect();
    let buf = ultrahdr_core::pixel_buffer_from_vec(
        bytes,
        img.w,
        img.h,
        zenpixels::PixelFormat::RgbaF32,
        ultrahdr_core::ColorPrimaries::Bt709,
        ultrahdr_core::TransferFunction::Linear,
    )
    .expect("pixel buffer");
    let sdr = ultrahdr_core::pixel_buffer_from_vec(
        sdr_px,
        img.w,
        img.h,
        zenpixels::PixelFormat::Rgba8,
        ultrahdr_core::ColorPrimaries::Bt709,
        ultrahdr_core::TransferFunction::Srgb,
    )
    .expect("sdr buffer");
    let (gainmap, metadata) = ultrahdr_core::gainmap::compute::compute_gainmap(
        &buf,
        &sdr,
        &GainMapConfig::default(),
        enough::Unstoppable,
    )
    .expect("gainmap");
    use zenjpeg::encoder::{ChromaSubsampling, EncoderConfig};
    // baseline SOF0 4:4:4 at q95 like the rest of the JPEG set — the UltraHDR
    // signallings must test metadata handling, not scan/subsampling support.
    let enc = EncoderConfig::ycbcr(95.0, ChromaSubsampling::None).progressive(false);
    let jpg = zenjpeg::ultrahdr::encode_with_gainmap_format(
        &sdr,
        &gainmap,
        &metadata,
        &enc,
        95.0,
        fmt,
        enough::Unstoppable,
    )
    .expect("ultrahdr encode");
    // applied rendition: sRGB OETF over the clipped linear HDR buffer — the
    // "reader applied the map, no HDR headroom" output.
    fn oetf(v: f32) -> u8 {
        let v = v.clamp(0.0, 1.0);
        let e = if v <= 0.003_130_8 {
            12.92 * v
        } else {
            1.055 * v.powf(1.0 / 2.4) - 0.055
        };
        (e * 255.0).round() as u8
    }
    let px: Vec<rgb::Rgb<u8>> = f32px
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| rgb::Rgb {
            r: oetf(c[0]),
            g: oetf(c[1]),
            b: oetf(c[2]),
        })
        .collect();
    let mut cfg = zenpng::EncodeConfig::default();
    cfg.parallel = false;
    let applied = zenpng::encode_rgb8(
        imgref::ImgRef::new(&px, img.w as usize, img.h as usize),
        None,
        &cfg,
        &enough::Unstoppable,
        &enough::Unstoppable,
    )
    .expect("applied png encode");
    (jpg, applied)
}

/// Applied-rendition PNG for the ISO-21496-style gain-map fixtures
/// (AVIF tmap, JXL jhgm): apply the synthetic map to the authored SDR
/// base through ultrahdr_core's own `apply_gainmap` at full-
/// reconstruction boost, then the sRGB OETF — the same ground-truth
/// route jpeg-ultrahdr uses, so these hyps don't fall back to a zen
/// decode (L-9). `params` is the same `GainMapParams` the fixture
/// serializes into its ISO metadata.
fn iso_applied_png(
    sdr_img: &Rgb16,
    gm_px: &[u8],
    gm_w: u32,
    gm_h: u32,
    params: &zencodec::gainmap::GainMapParams,
) -> Vec<u8> {
    let mut sdr_px = Vec::with_capacity((sdr_img.w * sdr_img.h * 4) as usize);
    for y in 0..sdr_img.h {
        for x in 0..sdr_img.w {
            let [r, g, b] = sdr_img.get(x, y);
            sdr_px.extend_from_slice(&[(r >> 8) as u8, (g >> 8) as u8, (b >> 8) as u8, 255]);
        }
    }
    let sdr = ultrahdr_core::pixel_buffer_from_vec(
        sdr_px,
        sdr_img.w,
        sdr_img.h,
        zenpixels::PixelFormat::Rgba8,
        ultrahdr_core::ColorPrimaries::Bt709,
        ultrahdr_core::TransferFunction::Srgb,
    )
    .expect("sdr buffer");
    let gm = ultrahdr_core::GainMap {
        width: gm_w,
        height: gm_h,
        channels: 1,
        data: gm_px.to_vec(),
    };
    let boost = ultrahdr_core::full_reconstruction_boost(params);
    let hdr = ultrahdr_core::gainmap::apply_gainmap(
        &sdr,
        &gm,
        params,
        boost,
        ultrahdr_core::HdrOutputFormat::LinearFloat,
        enough::Unstoppable,
    )
    .expect("apply gainmap");
    let bytes = hdr.copy_to_contiguous_bytes(); // RgbaF32, little-endian
    let px: Vec<rgb::Rgb<u8>> = bytes
        .as_chunks::<16>()
        .0
        .iter()
        .map(|c| {
            let oetf = |v: f32| -> u8 {
                let v = v.clamp(0.0, 1.0);
                let e = if v <= 0.003_130_8 {
                    12.92 * v
                } else {
                    1.055 * v.powf(1.0 / 2.4) - 0.055
                };
                (e * 255.0).round() as u8
            };
            rgb::Rgb {
                r: oetf(f32::from_le_bytes(c[0..4].try_into().unwrap())),
                g: oetf(f32::from_le_bytes(c[4..8].try_into().unwrap())),
                b: oetf(f32::from_le_bytes(c[8..12].try_into().unwrap())),
            }
        })
        .collect();
    let mut cfg = zenpng::EncodeConfig::default();
    cfg.parallel = false;
    zenpng::encode_rgb8(
        imgref::ImgRef::new(&px, sdr_img.w as usize, sdr_img.h as usize),
        None,
        &cfg,
        &enough::Unstoppable,
        &enough::Unstoppable,
    )
    .expect("applied png encode")
}

mod avif_fixtures;
mod expect;
mod heic_fixtures;
mod jpeg_fixtures;
mod jxl_fixtures;
mod png_fixtures;
mod webp_fixtures;

/// Shared fixture-generation context: test patterns and the ICC profiles
/// every fixture family draws from.
struct Ctx {
    pat: pattern::Pattern,
    pat253: pattern::Pattern,
    srgb: Vec<u8>,
    p3: Vec<u8>,
    p3_v2: Vec<u8>,
    adobe: Vec<u8>,
}

/// Generate every synthetic fixture into `out_dir` (already created), and
/// return the manifest rows. `heic_base` is a path to a corpus HEIC used as
/// the remux donor.
pub fn generate_all(out_dir: &Path, heic_base: &Path) -> Result<Vec<FixtureRow>, String> {
    let mut s = Sink {
        dir: out_dir.to_path_buf(),
        rows: Vec::new(),
        donor_sha: String::new(),
    };
    let ctx = Ctx {
        pat: pattern::render(384, 256),
        pat253: pattern::render(381, 253),
        srgb: icc::srgb_icc_v4(),
        p3: icc::display_p3_icc_v4(),
        p3_v2: icc::display_p3_icc_v2(),
        adobe: icc::adobe_rgb_icc_v2(),
    };

    jpeg_fixtures::generate(&mut s, &ctx)?;
    png_fixtures::generate(&mut s, &ctx)?;
    webp_fixtures::generate(&mut s, &ctx)?;
    avif_fixtures::generate(&mut s, &ctx)?;
    jxl_fixtures::generate(&mut s, &ctx)?;
    heic_fixtures::generate(&mut s, &ctx, heic_base)?;

    // Post-generation gate: re-parse every emitted fixture against its
    // declared signalling tokens + sha256 uniqueness across the set.
    let rows = s.rows;
    crate::verify::verify_dir(out_dir, &rows)?;
    Ok(rows)
}
