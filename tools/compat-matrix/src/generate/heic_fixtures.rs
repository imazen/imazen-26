use super::*;

pub(super) fn generate(s: &mut Sink, ctx: &Ctx, heic_base: &Path) -> Result<(), String> {
    let p3 = ctx.p3.as_slice();

    // ============================ HEIC (remux of corpus base) ============
    {
        let src = std::fs::read(heic_base).map_err(|e| format!("heic base: {e}"))?;
        s.donor_sha = sha256_hex(&src);
        let dm = Demux::load(&src).map_err(|e| format!("heic demux: {e}"))?;
        let all_items: Vec<u32> = dm.items.iter().map(|i| i.item_id).collect();
        let corpus_hyp = |extra: &str| -> Vec<Hyp> {
            vec![
                Hyp {
                    name: "correct".into(),
                    spec: format!("corpus:{extra}"),
                    correct: true,
                },
                Hyp {
                    name: "stored".into(),
                    spec: "corpus:stored".into(),
                    correct: false,
                },
            ]
        };
        // Full-grid control: verbatim remux of the 48-tile corpus file
        // (slow to decode, but exercises real multi-item structure), plus an
        // injected XMP mime item. The pinned donor carries its own `mime`
        // item already; the injected one adds a *deterministic* packet
        // (name "xmp", compat-matrix payload) so the mime-item metadata
        // check never depends on donor bytes.
        let xmp_pkt = br#"<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="compat-matrix">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:tiff="http://ns.adobe.com/tiff/1.0/" tiff:Make="compat-matrix" tiff:Orientation="1"/></rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>"#
            .to_vec();
        {
            let (gw, gh) = dm
                .grid_dims()
                .or_else(|| dm.dims_of(dm.primary))
                .ok_or("heic base: no ispe/grid dims")?;
            let b = heif::remux(&dm, &RemuxSignalling::default().with_xmp_mime(xmp_pkt))?;
            s.emit(
                row(
                    "heic-remux-base",
                    "orientation",
                    "heic/remux-base.heic",
                    gw,
                    gh,
                    1,
                    Colour::P3,
                    "none",
                    "verbatim remux of corpus base (48-tile grid, donor's own Exif+mime items kept) + injected deterministic 'xmp' mime item (mime-item check is donor-independent)",
                    &b,
                    corpus_hyp("as-signalled"),
                ),
                &b,
            );
        }
        // Fast base: promote a single hvc1 tile to primary so each
        // signalling variant decodes in ~1s instead of assembling the
        // 48-tile grid. Same payload, same signalling machinery.
        // Prefer the thumbnail item (non-square, smallest standalone
        // hvc1 image) over a square grid tile so orientation changes
        // stay visible in output dimensions.
        let tile_id = dm
            .iref
            .get(b"thmb")
            .and_then(|pairs| pairs.first().map(|(f, _)| *f))
            .or_else(|| {
                dm.items
                    .iter()
                    .filter(|i| i.item_type == *b"hvc1")
                    .map(|i| i.item_id)
                    .next_back()
            })
            .ok_or("heic base: no hvc1 item")?;
        let single = heif::remux(
            &dm,
            &RemuxSignalling::default().keep_only(&[tile_id], &all_items),
        )?;
        // The promoted item keeps whatever `colr` the donor carries —
        // under the pinned donor the thumbnail's is a malformed `colr
        // 'prof'` with a zero-length ICC payload, kept as a robustness
        // fixture (vips' heif loader refuses it with "bad seek"). The
        // colour label + description are derived from the emitted bytes,
        // not assumed (M-1): a donor change must change the label.
        let single_clean = heif::remux(
            &dm,
            &RemuxSignalling::default()
                .keep_only(&[tile_id], &all_items)
                .dropping(b"colr"),
        )?;
        let sdm = Demux::load(&single_clean).map_err(|e| format!("tile demux: {e}"))?;
        let (bw, bh) = sdm.dims_of(sdm.primary).ok_or("heic tile: no ispe dims")?;
        let base_dims = (bw, bh);
        let (tile_colour, colr_desc) = {
            let tdm = Demux::load(&single).map_err(|e| format!("tile demux: {e}"))?;
            colr_label(&tdm, ctx)
        };
        s.emit(
            row(
                "heic-tile-base",
                "other",
                "heic/tile-base.heic",
                bw,
                bh,
                1,
                tile_colour,
                "none",
                &format!("single hvc1 tile (donor item {tile_id}) as primary; {colr_desc}"),
                &single,
                corpus_hyp("as-signalled"),
            ),
            &single,
        );
        for a in 0..4u8 {
            let b = heif::remux(&sdm, &RemuxSignalling::irot(a))?;
            let eo = [1u8, 8, 3, 6][a as usize]; // irot is CCW: 1->8, 2->3, 3->6
            // manifest w,h = stored dims everywhere (display dims live in
            // expect_orient, not in w/h).
            let dims = base_dims;
            s.emit(
                row(
                    &format!("heic-irot{a}"),
                    "orientation",
                    &format!("heic/irot{a}.heic"),
                    dims.0,
                    dims.1,
                    eo,
                    Colour::Untagged,
                    "none",
                    &format!("irot={a} on primary item"),
                    &b,
                    corpus_hyp(&format!("orient={eo}")),
                ),
                &b,
            );
        }
        for ax in 0..2u8 {
            let b = heif::remux(&sdm, &RemuxSignalling::imir(ax))?;
            let eo = [4u8, 2][ax as usize]; // imir axis 0 = top-bottom (EXIF 4), axis 1 = left-right (EXIF 2)
            s.emit(
                row(
                    &format!("heic-imir{ax}"),
                    "orientation",
                    &format!("heic/imir{ax}.heic"),
                    bw,
                    bh,
                    eo,
                    Colour::Untagged,
                    "none",
                    &format!("imir axis={ax} on primary item"),
                    &b,
                    corpus_hyp(&format!("orient={eo}")),
                ),
                &b,
            );
        }
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::no_orientation().with_exif(exif::build_tiff(&ExifSpec {
                    orientation: Some(6),
                    ..Default::default()
                })),
            )?;
            s.emit(
                row(
                    "heic-exif-orient6",
                    "orientation",
                    "heic/exif-orient6.heic",
                    bw,
                    bh,
                    1,
                    Colour::Untagged,
                    "none",
                    "Exif item orientation=6 (informative), no irot/imir",
                    &b,
                    // MIAF: irot/imir are normative, an Exif item's
                    // orientation is informative-only — a spec-following
                    // reader shows the stored pixels.
                    vec![
                        Hyp {
                            name: "correct".into(),
                            spec: "corpus:stored".into(),
                            correct: true,
                        },
                        Hyp {
                            name: "exif-applied".into(),
                            spec: "corpus:orient=6".into(),
                            correct: false,
                        },
                    ],
                ),
                &b,
            );
        }
        // nclx range/matrix must equal the donor's de-facto decode so that
        // declaring nclx changes only primaries+transfer, never the decode:
        // the donor (iPhone 8 Plus tile) carries NO nclx anywhere — tiles
        // hold `colr 'prof'` (548B Display P3), the thumbnail a malformed
        // empty 'prof', and the HEVC VUI is unspecified. Measured de-facto
        // decode = BT.601 FULL range (zen --raw and libheif heif-convert
        // are bit-identical between `nocolr` and a 601/full injection).
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::default().with_colr(Some(heif::colr_nclx(1, 13, 6, true))),
            )?;
            s.emit(
                row(
                    "heic-colr-srgb",
                    "colour",
                    "heic/colr-srgb.heic",
                    bw,
                    bh,
                    1,
                    Colour::Srgb,
                    "none",
                    "nclx colr 1/13/6 full (donor has no nclx; range/matrix = de-facto unspecified decode BT.601/full)",
                    &b,
                    corpus_hyp("color=srgb"),
                ),
                &b,
            );
        }
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::default().with_colr(Some(heif::colr_nclx(12, 13, 6, true))),
            )?;
            s.emit(
                row(
                    "heic-colr-p3",
                    "colour",
                    "heic/colr-p3.heic",
                    bw,
                    bh,
                    1,
                    Colour::P3,
                    "none",
                    "nclx colr 12/13/6 full (donor has no nclx; range/matrix = de-facto unspecified decode BT.601/full)",
                    &b,
                    corpus_hyp("color=p3"),
                ),
                &b,
            );
        }
        {
            let b = heif::remux(&sdm, &RemuxSignalling::default().dropping(b"colr"))?;
            s.emit(
                row(
                    "heic-nocolr",
                    "colour",
                    "heic/nocolr.heic",
                    bw,
                    bh,
                    1,
                    Colour::Untagged,
                    "none",
                    "all colr properties stripped (untagged)",
                    &b,
                    corpus_hyp("color=untagged"),
                ),
                &b,
            );
        }
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::default()
                    .dropping(b"colr")
                    .with_exif(exif::build_tiff(&ExifSpec {
                        color_space: Some(0xFFFF),
                        interop_index: Some("R03"),
                        ..Default::default()
                    })),
            )?;
            s.emit(
                row(
                    "heic-exif-r03",
                    "colour",
                    "heic/exif-r03.heic",
                    bw,
                    bh,
                    1,
                    Colour::AdobeRgb,
                    "none",
                    "colr stripped; Exif item cs=0xFFFF+R03 only",
                    &b,
                    corpus_hyp("color=adobe"),
                ),
                &b,
            );
        }
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::default().with_colr(Some(heif::colr_prof(p3))),
            )?;
            s.emit(
                row(
                    "heic-icc-p3",
                    "colour",
                    "heic/icc-p3.heic",
                    bw,
                    bh,
                    1,
                    Colour::P3,
                    "none",
                    "colr prof (full ICC P3)",
                    &b,
                    corpus_hyp("color=p3-icc"),
                ),
                &b,
            );
        }
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::default()
                    .with_colr(Some(heif::colr_nclx(1, 13, 6, true)))
                    .with_extra_prop(heif::colr_prof(p3)),
            )?;
            s.emit(
                row(
                    "heic-colr-conflict",
                    "colour",
                    "heic/colr-conflict.heic",
                    bw,
                    bh,
                    1,
                    Colour::P3,
                    "none",
                    "two colr props: nclx sRGB + prof P3 (reader precedence)",
                    &b,
                    vec![
                        Hyp {
                            name: "icc-wins".into(),
                            spec: "corpus:color=conflict-nclx-srgb-vs-icc-p3".into(),
                            correct: true,
                        },
                        // nclx decl is sRGB full-range = the de-facto decode:
                        // honouring it is a no-op here (documented: libheif's
                        // nclx-wins equals "no conversion" on this fixture —
                        // the spec is silent on colr precedence, the matrix
                        // declares icc-wins correct for this pairing).
                        Hyp {
                            name: "nclx-wins".into(),
                            spec: "corpus:color=srgb".into(),
                            correct: false,
                        },
                    ],
                ),
                &b,
            );
        }
        // The spec-silent colr conflict PLUS a range decl the codestream
        // doesn't use: nclx 1/13/6/limited on a full-range HEVC stream. The
        // `nclx-wins` hypothesis is rendered by libheif honoring the decl —
        // the range flag actually moves pixels here (~9.6 levels MAD vs the
        // full-range base, per the round-7 measurement).
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::default()
                    .with_colr(Some(heif::colr_nclx(1, 13, 6, false)))
                    .with_extra_prop(heif::colr_prof(p3)),
            )?;
            s.emit(
                row(
                    "heic-colr-conflict-range",
                    "colour",
                    "heic/colr-conflict-range.heic",
                    bw,
                    bh,
                    1,
                    Colour::P3,
                    "none",
                    "two colr props: prof P3 + nclx sRGB LIMITED (declares a range the codestream doesn't use)",
                    &b,
                    vec![
                        // correct = nclx steers the decode (incl. the
                        // limited->full expansion) AND the prof steers the
                        // display transform — the composed reading.
                        Hyp {
                            name: "icc-wins".into(),
                            spec: "corpus:color=conflict-nclx-srgb-vs-icc-p3".into(),
                            correct: true,
                        },
                        // fully-unmanaged stored pixels — zen-raw's honest
                        // reading. Without it zen-raw lands on nclx-wins by
                        // proximity under the wide corpus T (H-2).
                        Hyp {
                            name: "stored".into(),
                            spec: "corpus:stored".into(),
                            correct: false,
                        },
                        // zen's measured reading (H-3/M-4): the embedded
                        // prof is honoured but the nclx *range flag* is
                        // dropped — the profile applies over the unexpanded
                        // base. Incorrect: it skips the declared expansion.
                        Hyp {
                            name: "icc-range-ignored".into(),
                            spec: "corpus:icc-range-ignored".into(),
                            correct: false,
                        },
                        Hyp {
                            name: "nclx-wins".into(),
                            spec: "corpus:libheif-nclx".into(),
                            correct: false,
                        },
                    ],
                ),
                &b,
            );
        }
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::irot(3).with_exif(exif::build_tiff(&ExifSpec {
                    orientation: Some(1),
                    ..Default::default()
                })),
            )?;
            s.emit(
                row(
                    "heic-irot3-exif1",
                    "orientation",
                    "heic/irot3-exif1.heic",
                    bw,
                    bh,
                    6,
                    Colour::Untagged,
                    "none",
                    "irot=3 (90 CW) + Exif item orient=1 (no conflict)",
                    &b,
                    corpus_hyp("orient=6"),
                ),
                &b,
            );
        }
        // The GM trap fixture: irot=3 with a *conflicting* Exif orient=6.
        // Normative irot lands on orient=6-display; a reader applying both
        // (GM -auto-orient) lands on orient=4; Exif-only lands on orient=6
        // pixels-wise identical to irot — so the informative-vs-normative
        // question is only separable for the double-applier and stored.
        {
            let b = heif::remux(
                &sdm,
                &RemuxSignalling::irot(3).with_exif(exif::build_tiff(&ExifSpec {
                    orientation: Some(6),
                    ..Default::default()
                })),
            )?;
            s.emit(
                row(
                    "heic-irot3-exif6",
                    "orientation",
                    "heic/irot3-exif6.heic",
                    bw,
                    bh,
                    6,
                    Colour::Untagged,
                    "none",
                    "irot=3 (90 CW) + conflicting Exif orient=6 (double-apply trap)",
                    &b,
                    vec![
                        Hyp {
                            name: "single-rot".into(),
                            spec: "corpus:orient=6".into(),
                            correct: true,
                        },
                        Hyp {
                            // irot3 = exif-6 equivalent (90 CW); +exif6
                            // again = 180 total = exif-3.
                            name: "double-applied".into(),
                            spec: "corpus:orient=3".into(),
                            correct: false,
                        },
                        Hyp {
                            name: "stored".into(),
                            spec: "corpus:stored".into(),
                            correct: false,
                        },
                    ],
                ),
                &b,
            );
        }
    }

    Ok(())
}

/// Byte-derived colour label + description for the promoted-item `colr`
/// property (round-10 M-1): the fixture declares only what its own bytes
/// carry — never a hardcoded claim that can go stale under a donor change.
/// `nclx` maps (primaries, transfer); `prof`/`rICC` payloads match the
/// canonical generated profiles by hash, else report payload size + sha.
fn colr_label(dm: &Demux, ctx: &Ctx) -> (Colour, String) {
    let colr = dm
        .props_for(dm.primary)
        .iter()
        .filter_map(|&(idx, _)| dm.ipco.get(idx as usize - 1))
        .find(|p| p.ty == *b"colr");
    let Some(c) = colr else {
        return (Colour::Untagged, "no colr property".into());
    };
    let d = &c.data;
    if d.starts_with(b"nclx") && d.len() >= 11 {
        let cp = u16::from_be_bytes([d[4], d[5]]);
        let tc = u16::from_be_bytes([d[6], d[7]]);
        let mc = u16::from_be_bytes([d[8], d[9]]);
        let range = if d[10] & 0x80 != 0 { "full" } else { "limited" };
        let colour = match (cp, tc) {
            (9 | 12, 16 | 17) => Colour::P3,
            (1, 13) => Colour::Srgb,
            _ => Colour::Uncalibrated,
        };
        return (colour, format!("colr 'nclx' {cp}/{tc}/{mc} {range}"));
    }
    if d.starts_with(b"prof") || d.starts_with(b"rICC") {
        let icc = &d[4..];
        if icc.is_empty() {
            return (
                Colour::Untagged,
                "malformed empty 'prof' colr — declares a profile, carries \
                 zero ICC payload (robustness)"
                    .into(),
            );
        }
        if icc.len() < 128 {
            return (
                Colour::Untagged,
                format!(
                    "colr 'prof' with truncated {}B ICC payload (robustness)",
                    icc.len()
                ),
            );
        }
        let sha = sha256_hex(icc);
        for (bytes, colour, name) in [
            (ctx.srgb.as_slice(), Colour::Srgb, "sRGB v4"),
            (ctx.p3.as_slice(), Colour::P3, "Display P3 v4"),
            (ctx.p3_v2.as_slice(), Colour::P3, "Display P3 v2"),
            (ctx.adobe.as_slice(), Colour::AdobeRgb, "Adobe RGB v2"),
        ] {
            if sha256_hex(bytes) == sha {
                return (colour, format!("colr 'prof' = canonical {name} ICC"));
            }
        }
        return (
            Colour::Uncalibrated,
            format!(
                "colr 'prof' carries unrecognized {}B ICC (sha {})",
                icc.len(),
                &sha[..12]
            ),
        );
    }
    (
        Colour::Uncalibrated,
        format!(
            "colr subtype {:?} ({}B payload)",
            String::from_utf8_lossy(&d[..4.min(d.len())]),
            d.len()
        ),
    )
}
