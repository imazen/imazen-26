use super::*;

pub(super) fn generate(s: &mut Sink, ctx: &Ctx) -> Result<(), String> {
    let srgb = ctx.srgb.clone();
    let (pat, p3) = (&ctx.pat, ctx.p3.as_slice());

    // ============================ WebP =================================
    {
        let cases: Vec<ColorCase> = vec![
            (
                "webp-untagged",
                Colour::Untagged,
                None,
                None,
                "lossless VP8L, no chunks",
            ),
            ("webp-icc-srgb", Colour::Srgb, Some(&srgb), None, "ICC sRGB"),
            ("webp-icc-p3", Colour::P3, Some(p3), None, "ICC Display P3"),
            (
                "webp-exif-orient6",
                Colour::Untagged,
                None,
                Some(ExifSpec {
                    orientation: Some(6),
                    ..Default::default()
                }),
                "EXIF chunk, orientation=6",
            ),
            (
                "webp-exif-cs1",
                Colour::Srgb,
                None,
                Some(ExifSpec {
                    color_space: Some(1),
                    ..Default::default()
                }),
                "EXIF-only colour cs=1",
            ),
        ];
        // lossy + alpha via the request API
        {
            let cfg = zenwebp::LossyConfig::new().with_quality(90.0);
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
            let b = zenwebp::EncodeRequest::lossy(
                &cfg,
                &rgba_px,
                zenwebp::PixelLayout::Rgba8,
                pat.img.w,
                pat.img.h,
            )
            .encode()
            .expect("webp lossy alpha");
            s.emit(
                row(
                    "webp-alpha-lossy",
                    "other",
                    "webp/alpha-lossy.webp",
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Untagged,
                    "none",
                    "lossy VP8+alpha, ramp in bottom band",
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
        }
        for (id, col, icc_p, exif_spec, desc) in cases {
            let tiff = exif_spec.map(|e| exif::build_tiff(&e));
            let b = webp_encode(&pat.img, icc_p, tiff);
            let (class, eo, hyps) = if id == "webp-exif-orient6" {
                ("orientation", 6u8, synth_orient_hyps(6))
            } else {
                ("colour", 1u8, synth_colour_hyps(col, None))
            };
            s.emit(
                row(
                    id,
                    class,
                    &format!("webp/{id}.webp"),
                    pat.img.w,
                    pat.img.h,
                    eo,
                    col,
                    "none",
                    desc,
                    &b,
                    hyps,
                ),
                &b,
            );
        }
    }

    Ok(())
}
