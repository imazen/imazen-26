//! Index each corpus source's orientation, colour signalling and HDR metadata.
//!
//! For each `id<TAB>path` line of the input list, probe the file with
//! `zencodecs::from_bytes` (the full probe every zen codec implements) and write one TSV
//! row: format and dimensions, EXIF/container orientation, bit depth and channels, the
//! ICC profile (size, hash, `desc` text, and what zenpixels identifies it as), CICP (from
//! the container, and from an ICC v4.4 `cicp` tag), HDR metadata (cLLI, mDCV, diffuse
//! white), gain-map presence and geometry, and embedded EXIF/XMP sizes.
//!
//! The zencodecs probe reports *effective* colour: an untagged PNG or JPEG comes back
//! with CICP 1/13/0/1, and HEIC colour isn't carried through. So each format is also
//! probed by its own crate for what the file *signals*: zenpng (`iCCP`, `sRGB`, `gAMA`,
//! `cHRM`, `cICP`, `cLLi`, `mDCV`), zenjpeg's container probe (ICC, MPF, ISO 21496-1,
//! XMP `hdrgm`, image count) and heic (`colr` nclx or ICC, gain-map and depth
//! auxiliaries). Those land in the `sig_*`, `png_*`, `jpeg_*` and `heic_*` columns.
//!
//! Usage: corpus-signal-probe <list.tsv> <out.tsv>
//! Failures go into the `error` column; no input is skipped.

#![forbid(unsafe_code)]

use std::fs;
use std::io::Write;

use sha2::{Digest, Sha256};
use zencodec::GainMapPresence;

const COLS: &[&str] = &[
    "id",
    "format",
    "width",
    "height",
    "display_w",
    "display_h",
    "orientation",
    "bit_depth",
    "channels",
    "has_alpha",
    "progressive",
    "sequence",
    "icc_source",
    "icc_bytes",
    "icc_sha256_16",
    "icc_desc",
    "icc_identified",
    "icc_cicp",
    "cicp",
    "color_authority",
    "clli",
    "mdcv",
    "diffuse_white",
    "gain_map",
    "gain_map_geometry",
    "gain_map_alt_cicp",
    "depth_map",
    "exif_bytes",
    "xmp_bytes",
    "sig_icc_bytes",
    "sig_cicp",
    "sig_clli",
    "sig_mdcv",
    "png_color_type",
    "png_srgb",
    "png_gama",
    "png_chrm",
    "png_palette",
    "jpeg_images",
    "jpeg_gain_map_signal",
    "jpeg_mpf",
    "jpeg_sofn",
    "heic_chroma",
    "heif_colr",
    "heif_clli",
    "heif_tmap",
    "heic_gain_map",
    "gain_map_headroom",
    "heic_full_icc",
    "heic_full_cicp",
    "heic_depth",
    "heic_aux",
    "warnings",
    "sig_error",
    "error",
];

fn cicp_str(c: &zenpixels::Cicp) -> String {
    format!(
        "{}/{}/{}/{}",
        c.color_primaries, c.transfer_characteristics, c.matrix_coefficients, c.full_range as u8
    )
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
                return String::from_utf8_lossy(s)
                    .trim_end_matches('\0')
                    .to_string();
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
                return String::from_utf16_lossy(&u)
                    .trim_end_matches('\0')
                    .to_string();
            }
        }
    }
    "?".into()
}

struct Row {
    cols: Vec<(&'static str, String)>,
}
impl Row {
    fn set(&mut self, k: &'static str, v: impl ToString) {
        self.cols.push((k, v.to_string()));
    }
}

/// Where a HEIF file's colour sits. A grid's own `colr` wins; when the grid has none,
/// the first tile's applies (S23 Ultra and iPhone 8 Plus files put it only on tiles).
struct HeifColour {
    /// "grid" / "tile" when an ICC profile was found there, else "-".
    source: &'static str,
    icc: Option<Vec<u8>>,
    /// `<where>:icc` / `<where>:nclx p/t/m/r` / "none".
    colr: String,
    clli: String,
    tmap: bool,
}

fn heif_colour(data: &[u8]) -> Option<HeifColour> {
    use heic::heif::{ColorInfo, FourCC, ItemType, parse};
    let c = parse(data, &enough::Unstoppable).ok()?;
    let primary = c.primary_item()?;
    let mut place = "grid";
    let mut colour = primary.color_info.clone();
    if colour.is_none() && primary.item_type == ItemType::Grid {
        let first = c
            .get_item_references(primary.id, FourCC::DIMG)
            .first()
            .copied();
        colour = first
            .and_then(|id| c.get_item(id))
            .and_then(|t| t.color_info);
        place = "tile";
    }
    let (source, icc, colr) = match colour {
        Some(ColorInfo::IccProfile(v)) => (place, Some(v), format!("{place}:icc")),
        Some(ColorInfo::Nclx {
            color_primaries,
            transfer_characteristics,
            matrix_coefficients,
            full_range,
        }) => (
            "-",
            None,
            format!(
                "{place}:nclx {color_primaries}/{transfer_characteristics}/{matrix_coefficients}/{}",
                full_range as u8
            ),
        ),
        None => ("-", None, "none".into()),
    };
    let clli = primary
        .content_light_level
        .as_ref()
        .map_or("-".into(), |l| {
            format!(
                "{}/{}",
                l.max_content_light_level, l.max_frame_average_light_level
            )
        });
    let tmap = c.items().any(|i| i.item_type == ItemType::Tmap);
    Some(HeifColour {
        source,
        icc,
        colr,
        clli,
        tmap,
    })
}

fn probe(id: &str, path: &str) -> Row {
    let mut r = Row {
        cols: vec![("id", id.to_string())],
    };
    let data = match fs::read(path) {
        Ok(d) => d,
        Err(e) => {
            r.set("error", format!("read: {e}"));
            return r;
        }
    };
    let info = match zencodecs::from_bytes(&data) {
        Ok(i) => i,
        Err(e) => {
            r.set("error", format!("probe: {e}"));
            return r;
        }
    };
    r.set(
        "format",
        info.format.definition().map_or("unknown", |d| d.name),
    );
    r.set("width", info.width);
    r.set("height", info.height);
    r.set("display_w", info.display_width());
    r.set("display_h", info.display_height());
    r.set("orientation", info.orientation.to_exif());
    r.set("has_alpha", info.has_alpha as u8);
    r.set("progressive", info.is_progressive as u8);
    r.set("sequence", format!("{:?}", info.sequence));
    r.set("depth_map", info.supplements.depth_map as u8);

    let sc = &info.source_color;
    r.set(
        "bit_depth",
        sc.bit_depth.map_or("-".into(), |b| b.to_string()),
    );
    r.set(
        "channels",
        sc.channel_count.map_or("-".into(), |c| c.to_string()),
    );
    r.set("cicp", sc.cicp.as_ref().map_or("-".into(), cicp_str));
    r.set("color_authority", format!("{:?}", sc.color_authority));
    r.set(
        "clli",
        sc.content_light_level.as_ref().map_or("-".into(), |c| {
            format!(
                "{}/{}",
                c.max_content_light_level, c.max_frame_average_light_level
            )
        }),
    );
    r.set(
        "mdcv",
        sc.mastering_display.as_ref().map_or("-".into(), |m| {
            format!("{}/{}", m.max_luminance, m.min_luminance)
        }),
    );
    r.set(
        "diffuse_white",
        sc.diffuse_white
            .as_ref()
            .map_or("-".into(), |d| format!("{d:?}")),
    );
    // HEIC: zencodecs doesn't carry colour through, so take it from heic: its probe for
    // the summary fields, its HEIF container for where the colour actually sits.
    let is_heic = info.format.definition().map(|d| d.name) == Some("heic");
    let heic_info = is_heic.then(|| heic::ImageInfo::from_bytes(&data));
    let heif = if is_heic { heif_colour(&data) } else { None };
    let mut icc_source = "file";
    let heic_icc = match &heif {
        Some(h) => {
            icc_source = h.source;
            h.icc.clone()
        }
        None => None,
    };
    let file_icc = sc.icc_profile.as_deref();
    if file_icc.is_none() && heic_icc.is_none() {
        icc_source = "-";
    }
    r.set("icc_source", icc_source);
    if let Some(h) = &heif {
        r.set("heif_colr", &h.colr);
        r.set("heif_clli", &h.clli);
        r.set("heif_tmap", h.tmap as u8);
    }
    match file_icc.or(heic_icc.as_deref()) {
        Some(icc) => {
            r.set("icc_bytes", icc.len());
            r.set(
                "icc_sha256_16",
                &Sha256::digest(icc)
                    .iter()
                    .map(|x| format!("{x:02x}"))
                    .collect::<String>()[..16],
            );
            r.set("icc_desc", icc_desc(icc));
            r.set(
                "icc_identified",
                zenpixels::icc::identify_common(icc).map_or("-".into(), |i| {
                    format!("{:?}/{:?}/{:?}", i.primaries, i.transfer, i.valid_use)
                }),
            );
            r.set(
                "icc_cicp",
                zenpixels::icc::extract_cicp(icc)
                    .as_ref()
                    .map_or("-".into(), cicp_str),
            );
        }
        None => {
            r.set("icc_bytes", 0);
            for k in ["icc_sha256_16", "icc_desc", "icc_identified", "icc_cicp"] {
                r.set(k, "-");
            }
        }
    }
    match &info.gain_map {
        GainMapPresence::Unknown => r.set(
            "gain_map",
            if info.supplements.gain_map {
                "flagged"
            } else {
                "unknown"
            },
        ),
        GainMapPresence::Absent => r.set("gain_map", "absent"),
        GainMapPresence::Available(g) => {
            r.set("gain_map", "present");
            r.set(
                "gain_map_geometry",
                format!("{}x{}x{}@{}", g.width, g.height, g.channels, g.bit_depth),
            );
            r.set(
                "gain_map_alt_cicp",
                g.alternate_cicp.as_ref().map_or("-".into(), cicp_str),
            );
        }
        other => r.set("gain_map", format!("{other:?}")),
    }
    let md = &info.embedded_metadata;
    r.set("exif_bytes", md.exif.as_ref().map_or(0, |e| e.len()));
    r.set("xmp_bytes", md.xmp.as_ref().map_or(0, |x| x.len()));
    r.set("warnings", info.warnings.join(" | "));

    match info.format.definition().map(|d| d.name) {
        Some("png") => match zenpng::probe(&data) {
            Ok(p) => {
                r.set(
                    "sig_icc_bytes",
                    p.icc_profile.as_ref().map_or(0, |v| v.len()),
                );
                r.set("sig_cicp", p.cicp.as_ref().map_or("-".into(), cicp_str));
                r.set(
                    "sig_clli",
                    p.content_light_level.as_ref().map_or("-".into(), |c| {
                        format!(
                            "{}/{}",
                            c.max_content_light_level, c.max_frame_average_light_level
                        )
                    }),
                );
                r.set("sig_mdcv", p.mastering_display.is_some() as u8);
                r.set("png_color_type", p.color_type);
                r.set(
                    "png_srgb",
                    p.srgb_intent.map_or("-".into(), |i| i.to_string()),
                );
                r.set(
                    "png_gama",
                    p.source_gamma.map_or("-".into(), |g| g.to_string()),
                );
                r.set("png_chrm", p.chromaticities.is_some() as u8);
                r.set(
                    "png_palette",
                    p.palette_size.map_or("-".into(), |n| n.to_string()),
                );
            }
            Err(e) => r.set("sig_error", format!("zenpng: {e}")),
        },
        Some("jpeg") => {
            use zenjpeg::container::{Wants, probe};
            let p = probe(&data, Wants::ALL);
            r.set(
                "sig_icc_bytes",
                sc.icc_profile.as_ref().map_or(0, |v| v.len()),
            );
            r.set("sig_cicp", "-");
            r.set("jpeg_images", p.image_ranges().len());
            r.set(
                "jpeg_gain_map_signal",
                format!("{:?}", p.gainmap_presence()),
            );
            r.set("jpeg_mpf", p.mpf().is_some() as u8);
            r.set(
                "jpeg_sofn",
                p.sof().map_or("-".into(), |f| f.sofn.to_string()),
            );
        }
        Some("heic") => {
            match heic_info {
                Some(Ok(h)) => {
                    r.set(
                        "sig_icc_bytes",
                        h.icc_profile.as_ref().map_or(0, |v| v.len()),
                    );
                    let c = (
                        h.color_primaries,
                        h.transfer_characteristics,
                        h.matrix_coefficients,
                    );
                    r.set(
                        "sig_cicp",
                        if c == (2, 2, 2) {
                            "-".to_string()
                        } else {
                            format!("{}/{}/{}/{}", c.0, c.1, c.2, h.video_full_range as u8)
                        },
                    );
                    r.set("bit_depth", h.bit_depth);
                    r.set("heic_chroma", h.chroma_format);
                    r.set("heic_gain_map", h.has_gain_map as u8);
                    r.set("heic_depth", h.has_depth as u8);
                }
                Some(Err(e)) => r.set("sig_error", format!("heic: {e:?}")),
                None => {}
            }
            // heic's full probe (zencodecs calls the light one): gain-map parameters,
            // and whether it carries colour.
            {
                use zencodec::decode::{DecodeJob as _, DecoderConfig as _};
                match heic::HeicDecoderConfig::new().job().probe_full(&data) {
                    Ok(fi) => {
                        r.set(
                            "heic_full_icc",
                            fi.source_color.icc_profile.as_ref().map_or(0, |v| v.len()),
                        );
                        r.set(
                            "heic_full_cicp",
                            fi.source_color.cicp.as_ref().map_or("-".into(), cicp_str),
                        );
                        match &fi.gain_map {
                            GainMapPresence::Available(g) => r.set(
                                "gain_map_headroom",
                                format!(
                                    "base {:.3} alt {:.3}",
                                    g.params.base_hdr_headroom, g.params.alternate_hdr_headroom
                                ),
                            ),
                            other => r.set("gain_map_headroom", format!("{other:?}")),
                        }
                    }
                    Err(e) => r.set("sig_error", format!("heic probe_full: {e}")),
                }
            }
            match heic::DecoderConfig::new().auxiliary_types(&data) {
                Ok(v) => r.set(
                    "heic_aux",
                    v.iter()
                        .map(|t| format!("{t:?}"))
                        .collect::<Vec<_>>()
                        .join(","),
                ),
                Err(e) => r.set("sig_error", format!("heic aux: {e:?}")),
            }
        }
        _ => {}
    }
    r
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 3 {
        eprintln!("usage: corpus-signal-probe <list.tsv: id<TAB>path> <out.tsv>");
        std::process::exit(2);
    }
    let list = fs::read_to_string(&args[1]).expect("read list");
    let mut out = fs::File::create(&args[2]).expect("create out");
    writeln!(out, "{}", COLS.join("\t")).unwrap();
    let lines: Vec<&str> = list.lines().filter(|l| !l.trim().is_empty()).collect();
    for (n, line) in lines.iter().enumerate() {
        let mut it = line.splitn(2, '\t');
        let (id, path) = (it.next().unwrap_or(""), it.next().unwrap_or(""));
        let row = probe(id, path);
        // Last write wins per column; tabs and newlines in values become spaces.
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
