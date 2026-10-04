use super::*;

pub(super) fn generate(s: &mut Sink, ctx: &Ctx) -> Result<(), String> {
    let srgb = ctx.srgb.clone();
    let (pat, p3) = (&ctx.pat, ctx.p3.as_slice());

    // ============================ JXL ==================================
    {
        use jxl_encoder::ColorEncoding as CE;
        use jxl_encoder::api::ImageMetadata as JM;
        let cases: Vec<(&str, Colour, JM<'_>, CE, &str)> = vec![
            (
                "jxl-icc-srgb",
                Colour::Srgb,
                JM::new().with_icc_profile(&srgb),
                CE::srgb(),
                "ICC sRGB (enum srgb fallback)",
            ),
            (
                "jxl-icc-p3",
                Colour::P3,
                JM::new().with_icc_profile(p3),
                CE::srgb(),
                "ICC Display P3 (enum srgb fallback)",
            ),
            (
                "jxl-enum-srgb",
                Colour::Srgb,
                JM::new(),
                CE::srgb(),
                "enum sRGB, no ICC",
            ),
            (
                "jxl-enum-p3",
                Colour::P3,
                JM::new(),
                CE::display_p3(),
                "enum Display P3, no ICC",
            ),
        ];
        for (id, col, meta, ce, desc) in cases {
            let b = jxl_encode(&pat.img, &meta, ce, false, false);
            s.emit(
                row(
                    id,
                    "colour",
                    &format!("jxl/{id}.jxl"),
                    pat.img.w,
                    pat.img.h,
                    1,
                    col,
                    "none",
                    desc,
                    &b,
                    synth_colour_hyps(col, None),
                ),
                &b,
            );
        }
        // Orientation bit-patches: force extra_fields via a benign
        // tone-mapping flag (see jxl_encode), then flip the 3 bits.
        let jm_plain = JM::new();
        for o in 1..=8u8 {
            let mut b = jxl_encode(&pat.img, &jm_plain, CE::srgb(), true, true);
            let prev = jxl::set_orientation(&mut b, o).expect("jxl orient patch");
            debug_assert_eq!(prev, 1);
            s.emit(
                row(
                    &format!("jxl-orient{o}"),
                    "orientation",
                    &format!("jxl/orient{o}.jxl"),
                    pat.img.w,
                    pat.img.h,
                    o,
                    Colour::Untagged,
                    "none",
                    &format!("JXL codestream orientation bits patched to {o}"),
                    &b,
                    synth_orient_hyps(o),
                ),
                &b,
            );
        }
        // EXIF-vs-codestream: Exif box orientation 6 + codestream orient 1.
        let jm_exif = exif::build_tiff(&ExifSpec {
            orientation: Some(6),
            ..Default::default()
        });
        let jm = JM::new().with_exif(&jm_exif);
        let b = jxl_encode(&pat.img, &jm, CE::srgb(), false, false);
        s.emit(
            row(
                "jxl-exif-orient6",
                "orientation",
                "jxl/exif-orient6.jxl",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Untagged,
                "none",
                "Exif box orient=6 (informative) + codestream orient=1",
                &b,
                synth_orient_hyps(1),
            ),
            &b,
        );
        // Alpha (lossless RGBA) + lossy variants.
        {
            let mut rgba_px = Vec::with_capacity((pat.img.w * pat.img.h * 4) as usize);
            for y in 0..pat.img.h {
                for x in 0..pat.img.w {
                    let [r, g, b] = pat.img.get(x, y);
                    let a = if y > pat.img.h * 3 / 4 {
                        (x * 255 / pat.img.w) as u8
                    } else {
                        255
                    };
                    rgba_px.extend_from_slice(&[
                        (r / 257) as u8,
                        (g / 257) as u8,
                        (b / 257) as u8,
                        a,
                    ]);
                }
            }
            let b = jxl_container_wrap(
                jxl_encoder::LosslessConfig::new()
                    .encode(
                        &rgba_px,
                        pat.img.w,
                        pat.img.h,
                        jxl_encoder::PixelLayout::Rgba8,
                    )
                    .expect("jxl rgba"),
            );
            s.emit(
                row(
                    "jxl-alpha",
                    "other",
                    "jxl/alpha.jxl",
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Untagged,
                    "none",
                    "lossless JXL RGBA, alpha ramp band",
                    &b,
                    vec![
                        Hyp {
                            name: "alpha-honored".into(),
                            spec: "synth:orient=1;alpha=ramp".into(),
                            correct: true,
                        },
                        Hyp {
                            name: "alpha-dropped".into(),
                            spec: "synth:orient=1;alpha=flatten".into(),
                            correct: false,
                        },
                    ],
                ),
                &b,
            );
            let lb = jxl_container_wrap(
                jxl_encoder::LossyConfig::new(1.0)
                    .encode(
                        &pat.img.to_rgb8(),
                        pat.img.w,
                        pat.img.h,
                        jxl_encoder::PixelLayout::Rgb8,
                    )
                    .expect("jxl lossy"),
            );
            s.emit(
                row(
                    "jxl-lossy",
                    "other",
                    "jxl/lossy.jxl",
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Untagged,
                    "none",
                    "lossy JXL (VarDCT) q90",
                    &lb,
                    synth_colour_hyps(Colour::Untagged, None),
                ),
                &lb,
            );
        }
        // jhgm gain map: ISO 21496-1 bundle (version u8 + u16BE meta
        // size + JXL jhgm-format ISO metadata + u8 colr size + u32BE
        // alt-ICC size + bare gain-map JXL codestream).
        let base = jxl_encode(&pat.img, &jm_plain, CE::srgb(), false, false);
        let (gw, gh) = (48u32, 32u32);
        let mut gm_px = Vec::with_capacity((gw * gh) as usize);
        for y in 0..gh {
            for _x in 0..gw {
                gm_px.push(if y < gh / 2 { 200u8 } else { 120u8 });
            }
        }
        let gm = jxl_encoder::LosslessConfig::new()
            .encode(&gm_px, gw, gh, jxl_encoder::PixelLayout::Gray8)
            .expect("gainmap jxl");
        let mut params = zencodec::gainmap::GainMapParams::default();
        params.alternate_hdr_headroom = 2.0;
        for ch in &mut params.channels {
            ch.max = 2.0;
        }
        let iso_meta = zencodec::gainmap::serialize_iso21496_fmt(
            &params,
            zencodec::gainmap::Iso21496Format::JxlJhgm,
        );
        let mut bundle = Vec::with_capacity(1 + 2 + iso_meta.len() + 1 + 4 + gm.len());
        bundle.push(0u8); // jhgm_version
        bundle.extend_from_slice(&(iso_meta.len() as u16).to_be_bytes());
        bundle.extend_from_slice(&iso_meta);
        bundle.push(0u8); // no color_encoding
        bundle.extend_from_slice(&0u32.to_be_bytes()); // no alt_icc
        bundle.extend_from_slice(&gm);
        let jhg = zenjxl::append_gain_map_box(&base, &bundle);
        // L-9: generator-computed applied rendition (ultrahdr_core apply
        // on the authored map+params) — not a zen decode.
        let applied = iso_applied_png(&pat.img, &gm_px, gw, gh, &params);
        s.emit_hyp_asset("jxl-jhgm", "gainmap-applied", &applied);
        s.emit(
            row(
                "jxl-jhgm",
                "gainmap",
                "jxl/jhgm.jxl",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Srgb,
                "jhgm",
                "JXL with jhgm gain-map box (grayscale JXL payload)",
                &jhg,
                vec![
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
                    Hyp {
                        name: "gainmap-applied".into(),
                        spec: "synth:orient=1;color=srgb;tonemap=ultrahdr-hdr".into(),
                        correct: false,
                    },
                ],
            ),
            &jhg,
        );
    }

    Ok(())
}
