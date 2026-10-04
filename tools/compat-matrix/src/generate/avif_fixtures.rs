use super::*;

pub(super) fn generate(s: &mut Sink, ctx: &Ctx) -> Result<(), String> {
    let srgb = ctx.srgb.clone();
    let (pat, p3) = (&ctx.pat, ctx.p3.as_slice());

    // ============================ AVIF =================================
    {
        use zenavif::EncoderConfig as AC;
        let base = || AC::new().quality(90.0);
        // r13 §2: named YCbCr-matrix hypotheses on every AVIF colour
        // fixture. The signalled matrix (nclx mc field where present, else
        // the AV1 seq header — zenravif pins 6/BT.601 for YCbCr) is the
        // correct reading; the other names the decode a matrix-substituting
        // reader produces (WIC's primaries/bit-depth-dependent selection).
        // Renders are ffmpeg YUV-plane dumps + explicit matrix math, so the
        // pair differs only in the matrix.
        // `signalled` is the matrix name the fixture declares: the nclx mc
        // field where the emitted bytes carry colr nclx (AVIF precedence:
        // colr over the seq header), else the seq-header matrix — zenravif
        // encodes YCbCr content with BT.601 and signals 6, and its
        // `matrix_coefficients()` builder field is dead config at 11033c9
        // (no backend consults it), so the mc-1 fixtures below inject the
        // nclx decl at container level — seq says 6, colr says 1.
        // A matrix hypothesis certifies only when the fixture's declared
        // primaries are sRGB: on a P3/Adobe decl `mc-601-decode` is the
        // matrix-right/primaries-dropped reading — named, but not correct.
        let mc_hyps = |signalled: u32, srgb_declared: bool| -> Vec<Hyp> {
            [709u32, 601]
                .iter()
                .map(|&mc| Hyp {
                    name: format!("mc-{mc}-decode"),
                    spec: format!("synth:orient=1;mc={mc}"),
                    correct: mc == signalled && srgb_declared,
                })
                .collect()
        };
        let avif_colour_hyps = |c: Colour, signalled: u32| -> Vec<Hyp> {
            let mut v = synth_colour_hyps(c, None);
            let srgb_declared = matches!(c, Colour::Srgb | Colour::Untagged | Colour::Uncalibrated);
            v.extend(mc_hyps(signalled, srgb_declared));
            v
        };
        // Wrong-matrix variants of every orientation reading (r13
        // addendum): WIC decodes every 8-bit sRGB-signalled AVIF through
        // the BT.709 matrix, so its orientation cells must name
        // `orient{N}-mc-709` instead of falling to `other` — orientation
        // evidence lives in `orientation_ok`, not in the colour verdict.
        let avif_orient_hyps = |correct: u8| -> Vec<Hyp> {
            let mut v = synth_orient_hyps(correct);
            for o in 1..=8u8 {
                v.push(Hyp {
                    name: format!("orient{o}-mc-709"),
                    spec: format!("synth:orient={o};mc=709"),
                    correct: false,
                });
            }
            v
        };
        let cases: Vec<AvifCase> = vec![
            (
                "avif-untagged",
                "colour",
                Colour::Untagged,
                base(),
                "no ICC/CICP",
                1,
                avif_colour_hyps(Colour::Untagged, 601),
            ),
            (
                "avif-icc-srgb",
                "colour",
                Colour::Srgb,
                base().icc_profile(srgb.clone()),
                "ICC sRGB",
                1,
                avif_colour_hyps(Colour::Srgb, 601),
            ),
            (
                "avif-icc-p3",
                "colour",
                Colour::P3,
                base().icc_profile(p3.to_vec()),
                "ICC P3",
                1,
                avif_colour_hyps(Colour::P3, 601),
            ),
            (
                "avif-cicp-srgb",
                "colour",
                Colour::Srgb,
                base()
                    .color_primaries(1)
                    .transfer_characteristics(13)
                    .pixel_range(zenavif::EncodePixelRange::Full),
                "nclx colr 1/13/6 full (encoder BT.601 YCbCr matrix)",
                1,
                avif_colour_hyps(Colour::Srgb, 601),
            ),
            (
                "avif-cicp-p3",
                "colour",
                Colour::P3,
                base()
                    .color_primaries(12)
                    .transfer_characteristics(13)
                    .pixel_range(zenavif::EncodePixelRange::Full),
                "nclx colr 12/13/6 (encoder BT.601 YCbCr matrix)",
                1,
                avif_colour_hyps(Colour::P3, 601),
            ),
            (
                "avif-exif-orient6",
                "orientation",
                Colour::Untagged,
                base().exif(exif::build_tiff(&ExifSpec {
                    orientation: Some(6),
                    ..Default::default()
                })),
                "Exif item orientation=6, no irot (informative only)",
                1,
                avif_orient_hyps(1),
            ),
            (
                "avif-exif-r03",
                "colour",
                Colour::AdobeRgb,
                base().exif(exif::build_tiff(&ExifSpec {
                    color_space: Some(0xFFFF),
                    interop_index: Some("R03"),
                    ..Default::default()
                })),
                "Exif-only colour: 0xFFFF + R03, no ICC/CICP",
                1,
                avif_colour_hyps(Colour::AdobeRgb, 601),
            ),
            (
                "avif-conflict-icc-p3-cicp-srgb",
                "colour",
                Colour::P3,
                base()
                    .icc_profile(p3.to_vec())
                    .color_primaries(1)
                    .transfer_characteristics(13)
                    .pixel_range(zenavif::EncodePixelRange::Full),
                "colr prof ICC=P3 + nclx 1/13/6 (conflict)",
                1,
                avif_colour_hyps(Colour::P3, 601),
            ),
        ];
        for (id, class, col, cfg, desc, eo, hyps) in cases {
            let mut b = avif_encode(&pat.img, &cfg);
            // Repack multi-extent iloc items (zenavif splits the Exif item's
            // offset prefix from its body): ffmpeg's mov demuxer rejects
            // extent_count>1 outright, so normalize to single extents.
            {
                let dm = Demux::load(&b).map_err(|e| format!("avif demux: {e}"))?;
                if dm.iloc.iter().any(|e| e.extents.len() > 1) {
                    b = heif::remux(&dm, &RemuxSignalling::default())?;
                }
            }
            // zenavif drops the nclx box when an ICC is set, and omits it for
            // 1/13 — inject at container level so each fixture actually
            // carries its claimed signalling.
            if id == "avif-cicp-srgb" {
                let dm = Demux::load(&b).map_err(|e| format!("avif demux: {e}"))?;
                b = heif::remux(
                    &dm,
                    &RemuxSignalling::default().with_colr(Some(heif::colr_nclx(1, 13, 6, true))),
                )?;
            }
            if id == "avif-conflict-icc-p3-cicp-srgb" {
                let dm = Demux::load(&b).map_err(|e| format!("avif demux: {e}"))?;
                b = heif::remux(
                    &dm,
                    &RemuxSignalling::default().with_extra_prop(heif::colr_nclx(1, 13, 6, true)),
                )?;
            }
            s.emit(
                row(
                    id,
                    class,
                    &format!("avif/{id}.avif"),
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
        // r13 §2: matrix-coefficient / subsampling / bit-depth / range
        // fixtures. zenavif at 11033c9 always encodes YCbCr with BT.601
        // (its `matrix_coefficients()` knob is dead config), so every
        // stream here is 601-encoded; the mc1 fixtures patch the seq-header
        // colour_description to mc=1 AND inject nclx 1/13/1 — a genuinely
        // mislabelled file: both signal levels say BT.709 matrix while the
        // content is BT.601. mc-709-decode = signalled reading,
        // mc-601-decode = content-true reading.
        for (id, cfg, nclx, desc, sig_mc) in [
            (
                "avif-cicp-srgb-mc1",
                base(),
                heif::colr_nclx(1, 13, 1, true),
                "seq-header AND nclx colr 1/13/1 full over a 601-encoded stream — both signal levels declare the BT.709 matrix; content is BT.601",
                709u32,
            ),
            (
                "avif-420-srgb-mc6",
                base().chroma_subsampling(zenavif::EncodeChromaSubsampling::Yuv420),
                heif::colr_nclx(1, 13, 6, true),
                "4:2:0 + nclx colr 1/13/6 full — signalled BT.601 matrix matches the encode",
                601,
            ),
            (
                "avif-420-srgb-mc1",
                base().chroma_subsampling(zenavif::EncodeChromaSubsampling::Yuv420),
                heif::colr_nclx(1, 13, 1, true),
                "4:2:0 + seq-header AND nclx colr 1/13/1 full over a 601-encoded stream — both signal levels declare 709; content is 601",
                709,
            ),
            (
                "avif-10bit-cicp-srgb",
                base().bit_depth(zenavif::EncodeBitDepth::Ten),
                heif::colr_nclx(1, 13, 6, true),
                "10-bit + nclx colr 1/13/6 full",
                601,
            ),
            (
                "avif-cicp-srgb-limited",
                base().pixel_range(zenavif::EncodePixelRange::Limited),
                heif::colr_nclx(1, 13, 6, false),
                "limited-range + nclx colr 1/13/6 limited — reader must expand studio levels",
                601,
            ),
        ] {
            let enc = avif_encode(&pat.img, &cfg);
            let mut dm = Demux::load(&enc).map_err(|e| format!("avif demux: {e}"))?;
            // mc1 fixtures: patch the seq-header mc (6->1) inside the av01
            // payload so both signal levels declare 709 over 601 content.
            if sig_mc == 709 {
                let p = dm
                    .payload
                    .get_mut(&dm.primary)
                    .ok_or("av01 primary payload")?;
                heif::av1_seq_mc_patch(p, 1, 13, 1).map_err(|e| format!("{id}: {e}"))?;
            }
            let b = heif::remux(&dm, &RemuxSignalling::default().with_colr(Some(nclx)))?;
            s.emit(
                row(
                    id,
                    "colour",
                    &format!("avif/{id}.avif"),
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Srgb,
                    "none",
                    desc,
                    &b,
                    avif_colour_hyps(Colour::Srgb, sig_mc),
                ),
                &b,
            );
        }
        // zenavif's encoder writes no irot/imir — inject at the container
        // level with the same HEIF remux machinery (AVIF is a HEIF family).
        let base_avif = avif_encode(&pat.img, &base());
        let adm = Demux::load(&base_avif).map_err(|e| format!("avif demux: {e}"))?;
        let ids: Vec<u32> = adm.items.iter().map(|i| i.item_id).collect();
        for (a, eo, desc) in [
            (1u8, 8u8, "irot=1 (90 CCW)"),
            (2, 3, "irot=2 (180)"),
            (3, 6, "irot=3 (90 CW)"),
        ] {
            let b = heif::remux(&adm, &RemuxSignalling::irot(a).rotate_items(ids.clone()))?;
            s.emit(
                row(
                    &format!("avif-irot{a}"),
                    "orientation",
                    &format!("avif/irot{a}.avif"),
                    pat.img.w,
                    pat.img.h,
                    eo,
                    Colour::Untagged,
                    "none",
                    desc,
                    &b,
                    avif_orient_hyps(eo),
                ),
                &b,
            );
        }
        for (ax, eo, desc) in [
            (0u8, 4u8, "imir axis=0 (top-bottom = EXIF 4)"),
            (1, 2, "imir axis=1 (left-right = EXIF 2)"),
        ] {
            let b = heif::remux(&adm, &RemuxSignalling::imir(ax).rotate_items(ids.clone()))?;
            s.emit(
                row(
                    &format!("avif-imir{ax}"),
                    "orientation",
                    &format!("avif/imir{ax}.avif"),
                    pat.img.w,
                    pat.img.h,
                    eo,
                    Colour::Untagged,
                    "none",
                    desc,
                    &b,
                    avif_orient_hyps(eo),
                ),
                &b,
            );
        }
        // Double-rotation trap: irot=3 (CW 90) PLUS Exif item orientation=6 —
        // a reader honouring both rotates twice.
        {
            let b = heif::remux(
                &adm,
                &RemuxSignalling::irot(3)
                    .with_exif(exif::build_tiff(&ExifSpec {
                        orientation: Some(6),
                        ..Default::default()
                    }))
                    .rotate_items(ids.clone()),
            )?;
            s.emit(
                row(
                    "avif-irot3-exif6",
                    "orientation",
                    "avif/irot3-exif6.avif",
                    pat.img.w,
                    pat.img.h,
                    6,
                    Colour::Untagged,
                    "none",
                    "irot=3 (90 CW) + Exif item orient=6 (informative) trap",
                    &b,
                    vec![
                        Hyp {
                            // irot and Exif happen to agree here, so
                            // "applied exactly one" is a single hypothesis.
                            name: "single-rot".into(),
                            spec: "synth:orient=6".into(),
                            correct: true,
                        },
                        Hyp {
                            // irot then Exif: 90 CW + 90 CW = 180.
                            name: "both".into(),
                            spec: "synth:orient=3".into(),
                            correct: false,
                        },
                        Hyp {
                            name: "none".into(),
                            spec: "synth:orient=1".into(),
                            correct: false,
                        },
                    ]
                    .into_iter()
                    .chain((1..=8u8).map(|o| Hyp {
                        name: format!("orient{o}-mc-709"),
                        spec: format!("synth:orient={o};mc=709"),
                        correct: false,
                    }))
                    .collect(),
                ),
                &b,
            );
        }
        // AVIF tmap gain map: gray AV1 item + tmap aux.
        {
            let gcfg = AC::new().quality(80.0);
            let (gw, gh) = (48u32, 32u32);
            let mut gpx = Vec::with_capacity((gw * gh) as usize);
            for y in 0..gh {
                for _x in 0..gw {
                    gpx.push(if y < gh / 2 { 200u8 } else { 120u8 });
                }
            }
            let gavif = zenavif::encode_gray8(
                imgref::ImgRef::new(&gpx, gw as usize, gh as usize),
                &gcfg,
                almost_enough::StopToken::new(almost_enough::Unstoppable),
            )
            .expect("gainmap avif")
            .avif_file;
            let gdm = Demux::load(&gavif).map_err(|e| format!("gm demux: {e}"))?;
            let av1 = gdm.payload.get(&gdm.primary).ok_or("gm payload")?.clone();
            let mut params = zencodec::gainmap::GainMapParams::default();
            params.alternate_hdr_headroom = 2.0;
            for ch in &mut params.channels {
                ch.max = 2.0;
            }
            let tmap_meta = zencodec::gainmap::serialize_iso21496_fmt(
                &params,
                zencodec::gainmap::Iso21496Format::AvifTmap,
            );
            let b = avif_encode(&pat.img, &base().with_gain_map(av1, gw, gh, 8, tmap_meta));
            // L-9: generator-computed applied rendition (ultrahdr_core
            // apply on the authored map+params) — not a zen decode.
            let applied = iso_applied_png(&pat.img, &gpx, gw, gh, &params);
            s.emit_hyp_asset("avif-tmap", "gainmap-applied", &applied);
            s.emit(
                row(
                    "avif-tmap",
                    "gainmap",
                    "avif/tmap.avif",
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Srgb,
                    "tmap",
                    "AVIF tmap aux gain-map item",
                    &b,
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
                &b,
            );
            // What published zenavif 0.1.6 writes: zenravif's archived
            // zenavif-serialize (rev 990bd6d) muxes the same tmap item
            // structure but with compatible brands `mif1,miaf` only — no
            // `tmap` brand, no `grpl`/`altr` group — so libavif ignores the
            // gain map. Kept as a robustness/signalling case; regenerated
            // `avif-tmap` above uses the workspace-member serializer (tmap
            // brand + grpl/altr). Bytes are vendored on block storage
            // because the folded serializer can no longer produce this
            // form; see assets/tmap-archived-serializer.pointer.md.
            let archived = archived_tmap_bytes();
            // Same map+params muxed differently — the applied rendition
            // is identical to avif-tmap's generator asset.
            s.emit_hyp_asset("avif-tmap-archived-serializer", "gainmap-applied", &applied);
            s.emit(
                row(
                    "avif-tmap-archived-serializer",
                    "gainmap",
                    "avif/tmap-archived-serializer.avif",
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Srgb,
                    "tmap",
                    "AVIF tmap gain-map muxed by archived zenavif-serialize (no tmap brand/grpl)",
                    &archived,
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
                &archived,
            );
        }
        // Alpha + 10-bit.
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
            let b = zenavif::encode_rgba8(
                imgref::ImgRef::new(&px, pat.img.w as usize, pat.img.h as usize),
                &base().alpha_quality(80.0),
                almost_enough::StopToken::new(almost_enough::Unstoppable),
            )
            .expect("avif rgba")
            .avif_file;
            s.emit(
                row(
                    "avif-alpha",
                    "other",
                    "avif/alpha.avif",
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Untagged,
                    "none",
                    "AVIF with aux alpha, ramp band",
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
            let b10 = avif_encode(&pat.img, &base().bit_depth(zenavif::EncodeBitDepth::Ten));
            s.emit(
                row(
                    "avif-10bit",
                    "other",
                    "avif/10bit.avif",
                    pat.img.w,
                    pat.img.h,
                    1,
                    Colour::Untagged,
                    "none",
                    "10-bit AVIF",
                    &b10,
                    synth_colour_hyps(Colour::Untagged, None),
                ),
                &b10,
            );
        }
    }

    Ok(())
}
