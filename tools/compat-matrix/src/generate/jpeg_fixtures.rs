use super::*;

pub(super) fn generate(s: &mut Sink, ctx: &Ctx) -> Result<(), String> {
    let srgb = ctx.srgb.clone();
    let (pat, pat253, p3, adobe) = (
        &ctx.pat,
        &ctx.pat253,
        ctx.p3.as_slice(),
        ctx.adobe.as_slice(),
    );

    // ============================ JPEG =================================
    // Orientation: stored canonical + EXIF tag N (381x253, non-MCU-aligned).
    for o in 1..=8u8 {
        let spec = ExifSpec {
            orientation: Some(o as u16),
            ..Default::default()
        };
        let bytes = jpeg_encode(&pat253.img, None, Some(spec), None);
        s.emit(
            row(
                &format!("jpeg-exif-o{o}"),
                "orientation",
                &format!("jpeg/exif-o{o}.jpg"),
                pat253.img.w,
                pat253.img.h,
                o,
                Colour::Untagged,
                "none",
                &format!("JPEG stored-canonical, EXIF orientation={o}"),
                &bytes,
                synth_orient_hyps(o),
            ),
            &bytes,
        );
    }
    // No-EXIF twin (indistinguishable from exif-o1 by design — the scorer
    // must mark the pair collapsed).
    let bytes = jpeg_encode(&pat253.img, None, None, None);
    s.emit(
        row(
            "jpeg-noexif",
            "orientation",
            "jpeg/noexif.jpg",
            pat253.img.w,
            pat253.img.h,
            1,
            Colour::Untagged,
            "none",
            "JPEG with no EXIF at all",
            &bytes,
            synth_orient_hyps(1),
        ),
        &bytes,
    );
    // EXIF vs XMP orientation conflict: EXIF=6, XMP tiff:Orientation=1.
    {
        let xmp = br#"<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:tiff="http://ns.adobe.com/tiff/1.0/" tiff:Orientation="1"/></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>"#.to_vec();
        let bytes = jpeg_encode(
            &pat253.img,
            None,
            Some(ExifSpec {
                orientation: Some(6),
                ..Default::default()
            }),
            Some(&xmp),
        );
        s.emit(
            row(
                "jpeg-exif6-xmp-o1",
                "orientation",
                "jpeg/exif6-xmp-o1.jpg",
                pat253.img.w,
                pat253.img.h,
                6,
                Colour::Untagged,
                "none",
                "EXIF orientation=6 + XMP tiff:Orientation=1 conflict",
                &bytes,
                synth_orient_hyps(6),
            ),
            &bytes,
        );
    }
    // Same conflict with XMP=3: distinguishes "XMP wins" (orient3) from
    // "ignores orientation" (orient1) — the o1 variant can't separate them.
    {
        let xmp = br#"<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:tiff="http://ns.adobe.com/tiff/1.0/" tiff:Orientation="3"/></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>"#.to_vec();
        let bytes = jpeg_encode(
            &pat253.img,
            None,
            Some(ExifSpec {
                orientation: Some(6),
                ..Default::default()
            }),
            Some(&xmp),
        );
        s.emit(row("jpeg-exif6-xmp-o3", "orientation", "jpeg/exif6-xmp-o3.jpg",
            pat253.img.w, pat253.img.h, 6, Colour::Untagged, "none",
            "EXIF orientation=6 + XMP tiff:Orientation=3 conflict (XMP-wins vs ignore distinguishable)", &bytes,
            synth_orient_hyps(6)), &bytes);
    }
    // Baked twins: pixels already transformed, tag=1.
    for o in 2..=8u8 {
        let baked = orient_display(&pat253.img, o);
        let spec = ExifSpec {
            orientation: Some(1),
            ..Default::default()
        };
        let bytes = jpeg_encode(&baked, None, Some(spec), None);
        s.emit(
            row(
                &format!("jpeg-baked-o{o}"),
                "orientation",
                &format!("jpeg/baked-o{o}.jpg"),
                baked.w,
                baked.h,
                1,
                Colour::Untagged,
                "none",
                &format!("JPEG pixels baked at orient {o}, tag=1"),
                &bytes,
                // tag=1: correct = stored, untransformed. Any applied
                // orientation re-transforms already-baked pixels.
                vec![Hyp {
                    name: "stored".into(),
                    spec: format!("synth-baked:o={o};orient=1"),
                    correct: true,
                }]
                .into_iter()
                .chain((2..=8u8).map(|x| Hyp {
                    name: format!("orient{x}"),
                    spec: format!("synth-baked:o={o};orient={x}"),
                    correct: false,
                }))
                .collect(),
            ),
            &bytes,
        );
    }

    // JPEG colour carriers.
    let jcolor: &[ColorCase] = &[
        (
            "jpeg-untagged",
            Colour::Untagged,
            None,
            None,
            "JFIF only, no ICC/EXIF",
        ),
        (
            "jpeg-icc-srgb",
            Colour::Srgb,
            Some(&srgb),
            None,
            "embedded sRGB v4 ICC",
        ),
        (
            "jpeg-icc-p3",
            Colour::P3,
            Some(p3),
            None,
            "embedded Display P3 v4 ICC",
        ),
        (
            "jpeg-icc-adobe",
            Colour::AdobeRgb,
            Some(adobe),
            None,
            "embedded Adobe RGB ICC",
        ),
        (
            "jpeg-exif-cs1",
            Colour::Srgb,
            None,
            Some(ExifSpec {
                color_space: Some(1),
                ..Default::default()
            }),
            "EXIF ColorSpace=1 only",
        ),
        (
            "jpeg-exif-cs0",
            Colour::Srgb,
            None,
            Some(ExifSpec {
                color_space: Some(0),
                ..Default::default()
            }),
            "EXIF ColorSpace=0 (nonstandard, in corpus)",
        ),
        (
            "jpeg-exif-uncal",
            Colour::Uncalibrated,
            None,
            Some(ExifSpec {
                color_space: Some(0xFFFF),
                ..Default::default()
            }),
            "EXIF ColorSpace=0xFFFF, no interop hint",
        ),
        (
            "jpeg-exif-interop-r98",
            Colour::Srgb,
            None,
            Some(ExifSpec {
                color_space: Some(0xFFFF),
                interop_index: Some("R98"),
                ..Default::default()
            }),
            "EXIF 0xFFFF + interop R98 (sRGB)",
        ),
        (
            "jpeg-exif-interop-r03",
            Colour::AdobeRgb,
            None,
            Some(ExifSpec {
                color_space: Some(0xFFFF),
                interop_index: Some("R03"),
                ..Default::default()
            }),
            "EXIF 0xFFFF + interop R03 (Adobe RGB), pixels are Adobe",
        ),
        (
            "jpeg-conflict-cs1-r03",
            Colour::Srgb,
            None,
            Some(ExifSpec {
                color_space: Some(1),
                interop_index: Some("R03"),
                ..Default::default()
            }),
            "EXIF cs=1 + interop R03 (contradictory), pixels are sRGB",
        ),
        (
            "jpeg-conflict-icc-srgb-exif-r03",
            Colour::Srgb,
            Some(&srgb),
            Some(ExifSpec {
                color_space: Some(0xFFFF),
                interop_index: Some("R03"),
                ..Default::default()
            }),
            "ICC=sRGB + EXIF R03 (conflict), pixels are sRGB",
        ),
        (
            "jpeg-conflict-icc-p3-exif-cs1",
            Colour::P3,
            Some(p3),
            Some(ExifSpec {
                color_space: Some(1),
                ..Default::default()
            }),
            "ICC=P3 + EXIF cs=1 (conflict), pixels are P3",
        ),
    ];
    for (id, col, icc_p, exif_spec, desc) in jcolor {
        let mut bytes = jpeg_encode(&pat.img, *icc_p, exif_spec.clone(), None);
        if *id == "jpeg-untagged" {
            // "JFIF only" means what it says: a JFIF APP0 segment and
            // nothing else.
            let jfif = jpeg::appn(0xE0, b"JFIF\0\x01\x02\x00\x00\x01\x00\x01\x00\x00");
            bytes = jpeg::insert_head_segment(&bytes, &jfif).expect("insert jfif");
        }
        s.emit(
            row(
                id,
                "colour",
                &format!("jpeg/{id}.jpg"),
                pat.img.w,
                pat.img.h,
                1,
                *col,
                "none",
                desc,
                &bytes,
                synth_colour_hyps(*col, None),
            ),
            &bytes,
        );
    }
    // APP14 Adobe marker variant.
    {
        let mut bytes = jpeg_encode(&pat.img, None, None, None);
        let app14 = jpeg::appn(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01");
        bytes = jpeg::insert_head_segment(&bytes, &app14).expect("insert app14");
        s.emit(
            row(
                "jpeg-app14-adobe",
                "colour",
                "jpeg/app14-adobe.jpg",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Untagged,
                "none",
                "Adobe APP14 transform=1, no ICC/EXIF",
                &bytes,
                synth_colour_hyps(Colour::Untagged, None),
            ),
            &bytes,
        );
    }
    // P3 via a v2 ICC (many readers treat v2 differently from v4).
    {
        let bytes = jpeg_encode(&pat.img, Some(&ctx.p3_v2), None, None);
        s.emit(
            row(
                "jpeg-icc-p3-v2",
                "colour",
                "jpeg/icc-p3-v2.jpg",
                pat.img.w,
                pat.img.h,
                1,
                Colour::P3,
                "none",
                "embedded Display P3 v2 ICC",
                &bytes,
                synth_colour_hyps(Colour::P3, None),
            ),
            &bytes,
        );
    }
    // Progressive + RGB-APP14 (Adobe transform=0 quirk).
    {
        use zenjpeg::encoder::{ChromaSubsampling, EncoderConfig};
        // 4:4:4 like the rest of the JPEG set — the only difference vs
        // jpeg-untagged must be progressive scans, not subsampling.
        let cfg = EncoderConfig::ycbcr(95.0, ChromaSubsampling::None).progressive(true);
        let px8 = pat.img.to_rgb8();
        let bytes = cfg
            .request()
            .encode(px8.as_rgb(), pat.img.w, pat.img.h)
            .expect("prog jpg");
        s.emit(
            row(
                "jpeg-progressive",
                "other",
                "jpeg/progressive.jpg",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Untagged,
                "none",
                "progressive JPEG, untagged",
                &bytes,
                synth_colour_hyps(Colour::Untagged, None),
            ),
            &bytes,
        );
        let cfg2 = EncoderConfig::rgb(95.0).progressive(false);
        let bytes2 = cfg2
            .request()
            .encode(px8.as_rgb(), pat.img.w, pat.img.h)
            .expect("rgb jpg");
        s.emit(
            row(
                "jpeg-rgb-app14",
                "other",
                "jpeg/rgb-app14.jpg",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Untagged,
                "none",
                "RGB JPEG + Adobe APP14 transform=0",
                &bytes2,
                synth_colour_hyps(Colour::Untagged, None),
            ),
            &bytes2,
        );
    }
    // UltraHDR in all three metadata signallings + corrupt MPF twin.
    {
        let gm_hyp = || -> Vec<Hyp> {
            vec![
                // The SDR-base render IS the stored image — the two collapse
                // by construction (documented): you cannot distinguish
                // "showed SDR base" from "ignored the map" in SDR output.
                Hyp {
                    name: "sdr-base".into(),
                    spec: "synth:orient=1;color=srgb;tonemap=ultrahdr-sdr".into(),
                    correct: true,
                },
                Hyp {
                    name: "stored".into(),
                    spec: "synth:stored".into(),
                    correct: false,
                },
                // A reader that APPLIED the gain map lights the mid-tone
                // boost band to clip — named verdict, wrong in SDR context.
                Hyp {
                    name: "gainmap-applied".into(),
                    spec: "synth:orient=1;color=srgb;tonemap=ultrahdr-hdr".into(),
                    correct: false,
                },
            ]
        };
        for (fmt, id, desc) in [
            (
                zenjpeg::ultrahdr::GainMapEncodingFormat::Xmp,
                "jpeg-ultrahdr-xmp",
                "UltraHDR 1.0: hdrgm XMP + MPF (no ISO APP2)",
            ),
            (
                zenjpeg::ultrahdr::GainMapEncodingFormat::Iso21496,
                "jpeg-ultrahdr-iso",
                "ISO 21496-1 APP2 + MPF only; hdrgm XMP stripped (zenjpeg writes it even under Iso21496)",
            ),
            (
                zenjpeg::ultrahdr::GainMapEncodingFormat::Both,
                "jpeg-ultrahdr",
                "XMP + ISO 21496-1 + MPF (Android 15 style)",
            ),
        ] {
            let (b, applied_png) = ultrahdr_encode_fmt(&pat.img, fmt);
            let b = if fmt == zenjpeg::ultrahdr::GainMapEncodingFormat::Iso21496 {
                // zenjpeg writes an hdrgm XMP APP1 even for the ISO-only
                // format — strip it byte-level so this fixture is genuinely
                // ISO 21496-1 signalled only (verify: `noxmp` token).
                jpeg::drop_segments(&b, 0xE1, jpeg::XMP_NS).expect("strip hdrgm XMP")
            } else {
                b
            };
            // the generator's true applied rendition — replaces the hyp
            // render managed_hyps would otherwise produce via probe --hdr
            s.emit_hyp_asset(id, "gainmap-applied", &applied_png);
            s.emit(
                row(
                    id,
                    "gainmap",
                    &format!("jpeg/{id}.jpg"),
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Srgb,
                    "ultrahdr",
                    desc,
                    &b,
                    gm_hyp(),
                ),
                &b,
            );
        }
        let (uhdr, _applied) =
            ultrahdr_encode_fmt(&pat.img, zenjpeg::ultrahdr::GainMapEncodingFormat::Both);
        let corrupt = jpeg::mpf_offsets_past_eof(&uhdr).expect("mpf corrupt");
        // No gainmap-applied hyp here: the corrupted MPF has no recoverable
        // map, so "applied" can't honestly render — the fixture measures
        // graceful-degradation vs hard-fail, not map application.
        let corrupt_hyps: Vec<Hyp> = gm_hyp()
            .into_iter()
            .filter(|h| h.name != "gainmap-applied")
            .collect();
        s.emit(
            row(
                "jpeg-ultrahdr-mpf-corrupt",
                "gainmap",
                "jpeg/ultrahdr-mpf-corrupt.jpg",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Srgb,
                "ultrahdr-corrupt-mpf",
                "UltraHDR with MPF secondary offsets past EOF",
                &corrupt,
                corrupt_hyps,
            ),
            &corrupt,
        );
    }

    Ok(())
}
