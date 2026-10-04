use super::*;

pub(super) fn generate(s: &mut Sink, ctx: &Ctx) -> Result<(), String> {
    let srgb = ctx.srgb.clone();
    let (pat, p3) = (&ctx.pat, ctx.p3.as_slice());

    // ============================ PNG ==================================
    // Truecolour by default: disable all colour-type downcasts so every
    // colour/orientation/conflict fixture is ct2/ct6 (real photos are).
    // png-palette-trns is the deliberate palette case, written via
    // png::indexed_png directly, not through this config.
    let pngc = {
        let mut c = zenpng::EncodeConfig::default();
        c.downcast = zenpng::DowncastFlags::none();
        c
    };
    // EncodeConfig is #[non_exhaustive]: build via default + field writes.
    let png_cfg = |f: &dyn Fn(&mut zenpng::EncodeConfig)| -> zenpng::EncodeConfig {
        let mut c = pngc.clone();
        f(&mut c);
        c
    };
    let mkmeta =
        |icc_p: Option<&[u8]>, exif_spec: Option<ExifSpec>| -> Option<zencodec::Metadata> {
            let mut m = zencodec::Metadata::none();
            if let Some(p) = icc_p {
                m = m.with_icc(p.to_vec());
            }
            if let Some(e) = exif_spec {
                m = m.with_exif(exif::build_tiff(&e));
            }
            Some(m)
        };
    let cases: Vec<(
        &str,
        Colour,
        Option<zencodec::Metadata>,
        zenpng::EncodeConfig,
        &str,
    )> = vec![
        (
            "png-untagged",
            Colour::Untagged,
            mkmeta(None, None),
            pngc.clone(),
            "no colour chunks",
        ),
        (
            "png-srgb",
            Colour::Srgb,
            mkmeta(None, None),
            png_cfg(&|c| c.srgb_intent = Some(0)),
            "sRGB chunk",
        ),
        (
            "png-iccp-srgb",
            Colour::Srgb,
            mkmeta(Some(&srgb), None),
            pngc.clone(),
            "iCCP sRGB",
        ),
        (
            "png-iccp-p3",
            Colour::P3,
            mkmeta(Some(p3), None),
            pngc.clone(),
            "iCCP Display P3",
        ),
        (
            "png-cicp-srgb",
            Colour::Srgb,
            mkmeta(None, None),
            png_cfg(&|c| c.cicp = Some(zenpixels::Cicp::new(1, 13, 0, true))),
            "cICP 1/13/0/1",
        ),
        (
            "png-cicp-p3",
            Colour::P3,
            mkmeta(None, None),
            png_cfg(&|c| c.cicp = Some(zenpixels::Cicp::new(12, 13, 0, true))),
            "cICP 12/13/0/1 (Display P3)",
        ),
        (
            "png-exif-r03",
            Colour::AdobeRgb,
            mkmeta(
                None,
                Some(ExifSpec {
                    color_space: Some(0xFFFF),
                    interop_index: Some("R03"),
                    ..Default::default()
                }),
            ),
            pngc.clone(),
            "eXIf-only colour: 0xFFFF + interop R03",
        ),
        (
            "png-gama-only",
            Colour::Srgb,
            mkmeta(None, None),
            png_cfg(&|c| c.source_gamma = Some(45455)),
            "gAMA 1/2.2 only",
        ),
        (
            "png-exif-orient6",
            Colour::Untagged,
            mkmeta(
                None,
                Some(ExifSpec {
                    orientation: Some(6),
                    ..Default::default()
                }),
            ),
            pngc.clone(),
            "eXIf orientation=6",
        ),
    ];
    for (id, col, meta, cfg, desc) in cases {
        let bytes = png_encode(&pat.img, false, meta, cfg);
        let hyps = if id == "png-exif-orient6" {
            synth_orient_hyps(6)
        } else {
            synth_colour_hyps(col, None)
        };
        let eo = if id == "png-exif-orient6" { 6 } else { 1 };
        s.emit(
            row(
                id,
                if id == "png-exif-orient6" {
                    "orientation"
                } else {
                    "colour"
                },
                &format!("png/{id}.png"),
                pat.img.w,
                pat.img.h,
                eo,
                col,
                "none",
                desc,
                &bytes,
                hyps,
            ),
            &bytes,
        );
    }
    // Conflicts via chunk injection (zenpng suppresses one when both set).
    {
        let base = png_encode(&pat.img, false, mkmeta(Some(p3), None), pngc.clone());
        let b = png::insert_chunk(&base, b"cICP", &png::cicp_body(1, 13, 0, true), b"IHDR")
            .expect("cICP inject");
        s.emit(
            row(
                "png-conflict-iccp-p3-cicp-srgb",
                "colour",
                "png/conflict-iccp-p3-cicp-srgb.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Srgb,
                "none",
                "iCCP=P3 + cICP 1/13/0/1 conflict",
                &b,
                synth_colour_hyps(Colour::Srgb, None),
            ),
            &b,
        );
        let base2 = png_encode(&pat.img, false, mkmeta(Some(&srgb), None), pngc.clone());
        let b2 = png::insert_chunk(&base2, b"cICP", &png::cicp_body(12, 13, 0, true), b"IHDR")
            .expect("cICP inject");
        s.emit(
            row(
                "png-conflict-iccp-srgb-cicp-p3",
                "colour",
                "png/conflict-iccp-srgb-cicp-p3.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::P3,
                "none",
                "iCCP=sRGB + cICP 12/13/0/1 conflict",
                &b2,
                synth_colour_hyps(Colour::P3, None),
            ),
            &b2,
        );
        let base3 = png_encode(
            &pat.img,
            false,
            mkmeta(None, None),
            png_cfg(&|c| c.srgb_intent = Some(0)),
        );
        let b3 = png::insert_chunk(&base3, b"iCCP", &png::iccp_body("p3", p3), b"IHDR")
            .expect("iCCP inject");
        s.emit(
            row(
                "png-srgb-chunk-plus-iccp-p3",
                "colour",
                "png/srgb-chunk-plus-iccp-p3.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::P3,
                "none",
                "sRGB chunk + iCCP P3 (spec: iCCP wins)",
                &b3,
                synth_colour_hyps(Colour::P3, None),
            ),
            &b3,
        );
    }
    // gAMA + cHRM declaring P3 without iCCP.
    {
        let cfg = png_cfg(&|c| {
            c.source_gamma = Some(45455);
            c.chromaticities = Some(zenpng::PngChromaticities {
                white_x: 31270,
                white_y: 32900,
                red_x: 68000,
                red_y: 32000,
                green_x: 26500,
                green_y: 69000,
                blue_x: 15000,
                blue_y: 6000,
            });
        });
        let b = png_encode(&pat.img, false, mkmeta(None, None), cfg);
        s.emit(
            row(
                "png-gama-chrm-p3",
                "colour",
                "png/gama-chrm-p3.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::P3,
                "none",
                "gAMA 1/2.2 + cHRM P3 primaries, no iCCP",
                &b,
                // §1b: the declared read is a power-2.2 curve over P3
                // primaries — `gama-chrm-p3` renders the fixture's own
                // gAMA+cHRM, not Display P3's parametric TRC. The
                // Display-P3 reading stays a named near-miss.
                vec![
                    Hyp {
                        name: "gama-chrm-p3".into(),
                        spec: "synth:orient=1;tag=gama-chrm".into(),
                        correct: true,
                    },
                    Hyp {
                        name: "p3-as-displayp3".into(),
                        spec: "synth:orient=1;color=p3".into(),
                        correct: false,
                    },
                    Hyp {
                        name: "p3-as-srgb".into(),
                        spec: "synth:orient=1;color=srgb".into(),
                        correct: false,
                    },
                    Hyp {
                        name: "p3-as-adobe".into(),
                        spec: "synth:orient=1;color=adobe".into(),
                        correct: false,
                    },
                ],
            ),
            &b,
        );
    }
    // 16-bit + alpha.
    {
        let b = png_encode(&pat.img, true, mkmeta(None, None), pngc.clone());
        s.emit(
            row(
                "png16-untagged",
                "other",
                "png/png16-untagged.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Untagged,
                "none",
                "16-bit RGB PNG, untagged",
                &b,
                synth_colour_hyps(Colour::Untagged, None),
            ),
            &b,
        );
        let b2 = png_encode(&pat.img, true, mkmeta(Some(p3), None), pngc.clone());
        s.emit(
            row(
                "png16-p3",
                "other",
                "png/png16-p3.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::P3,
                "none",
                "16-bit RGB PNG with P3 ICC",
                &b2,
                synth_colour_hyps(Colour::P3, None),
            ),
            &b2,
        );
        // alpha: same pattern, alpha ramps 0->255 left to right in bottom band
        let mut rgba_px = Vec::with_capacity((pat.img.w * pat.img.h * 4) as usize);
        for y in 0..pat.img.h {
            for x in 0..pat.img.w {
                let [r, g, b] = pat.img.get(x, y);
                let a = if y > pat.img.h * 3 / 4 {
                    (x * 255 / pat.img.w) as u8
                } else {
                    255
                };
                rgba_px.extend_from_slice(&[(r / 257) as u8, (g / 257) as u8, (b / 257) as u8, a]);
            }
        }
        let px: Vec<rgb::Rgba<u8>> = rgba_px
            .as_chunks::<4>()
            .0
            .iter()
            .map(|c| rgb::Rgba {
                r: c[0],
                g: c[1],
                b: c[2],
                a: c[3],
            })
            .collect();
        let b3 = zenpng::encode_rgba8(
            imgref::ImgRef::new(&px, pat.img.w as usize, pat.img.h as usize),
            None,
            &pngc,
            &enough::Unstoppable,
            &enough::Unstoppable,
        )
        .expect("png rgba");
        s.emit(
            row(
                "png-alpha",
                "other",
                "png/png-alpha.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Untagged,
                "none",
                "RGBA8 with left-to-right alpha ramp in bottom band",
                &b3,
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
            &b3,
        );
        // 16-bit RGBA.
        let px16: Vec<rgb::Rgba<u16>> = (0..pat.img.w * pat.img.h)
            .map(|i| {
                let (x, y) = (i % pat.img.w, i / pat.img.w);
                let [r, g, b] = pat.img.get(x, y);
                // real alpha signal: left-to-right ramp in the bottom band
                let a = if y > pat.img.h * 3 / 4 {
                    ((x as u64 * 0xffff) / (pat.img.w as u64 - 1)) as u16
                } else {
                    0xffff
                };
                rgb::Rgba { r, g, b, a }
            })
            .collect();
        let b16 = zenpng::encode_rgba16(
            imgref::ImgRef::new(&px16, pat.img.w as usize, pat.img.h as usize),
            None,
            &pngc,
            &enough::Unstoppable,
            &enough::Unstoppable,
        )
        .expect("png rgba16");
        s.emit(
            row(
                "png16-alpha",
                "other",
                "png/png16-alpha.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Untagged,
                "none",
                "16-bit RGBA PNG with left-to-right alpha ramp in bottom band",
                &b16,
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
            &b16,
        );
        // APNG: two frames (full pattern, then bottom half shifted to black).
        let f0: Vec<u8> = px.iter().flat_map(|p| [p.r, p.g, p.b, p.a]).collect();
        let mut f1 = f0.clone();
        for y in (pat.img.h / 2) as usize..pat.img.h as usize {
            for x in 0..pat.img.w as usize {
                let i = (y * pat.img.w as usize + x) * 4;
                f1[i..i + 3].copy_from_slice(&[16, 16, 16]);
            }
        }
        let apng = zenpng::encode_apng(
            &[
                zenpng::ApngFrameInput::new(&f0, 1, 10),
                zenpng::ApngFrameInput::new(&f1, 1, 10),
            ],
            pat.img.w,
            pat.img.h,
            &zenpng::ApngEncodeConfig::default(),
            None,
            &enough::Unstoppable,
            &enough::Unstoppable,
        )
        .expect("apng");
        s.emit(
            row(
                "png-apng",
                "other",
                "png/apng.png",
                pat.img.w,
                pat.img.h,
                1,
                Colour::Untagged,
                "none",
                "2-frame APNG",
                &apng,
                vec![Hyp {
                    name: "frame0".into(),
                    spec: "synth:orient=1".into(),
                    correct: true,
                }],
            ),
            &apng,
        );
        // Indexed + tRNS: 16-entry palette, second half semi-transparent.
        {
            let palette: Vec<[u8; 3]> = [
                [255, 0, 0],
                [0, 200, 0],
                [0, 0, 255],
                [255, 255, 255],
                [0, 0, 0],
                [255, 255, 0],
                [0, 255, 255],
                [255, 0, 255],
                [32, 32, 32],
                [64, 64, 64],
                [96, 96, 96],
                [128, 128, 128],
                [160, 160, 160],
                [192, 192, 192],
                [224, 224, 224],
                [255, 128, 0],
            ]
            .to_vec();
            let alphas: Vec<u8> = (0..16u8).map(|i| if i < 8 { 255 } else { 96 }).collect();
            let mut idx = vec![0u8; (pat.img.w * pat.img.h) as usize];
            for y in 0..pat.img.h {
                for x in 0..pat.img.w {
                    idx[(y * pat.img.w + x) as usize] =
                        ((x * 16 / pat.img.w + y * 2 / pat.img.h) % 16) as u8;
                }
            }
            let b = png::indexed_png(pat.img.w, pat.img.h, &idx, &palette, Some(&alphas));
            s.emit(
                row(
                    "png-palette-trns",
                    "other",
                    "png/palette-trns.png",
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Untagged,
                    "none",
                    "colour type 3: PLTE 16 + tRNS (entries 8-15 alpha 96)",
                    &b,
                    vec![Hyp {
                        name: "decoded".into(),
                        spec: "synth:palette".into(),
                        correct: true,
                    }],
                ),
                &b,
            );
        }
    }

    Ok(())
}
