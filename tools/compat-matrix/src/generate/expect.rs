//! Machine-checkable signalling expectations per fixture id, asserted
//! against the emitted bytes by `verify::verify_dir`. The token language is
//! documented in `verify.rs` (`check`). Unknown ids panic — a fixture whose
//! signalling cannot be expressed here is a fixture we cannot verify.

/// Expected signalling tokens for a fixture id (parsed out of loop-built
/// ids like `jpeg-exif-o6`).
pub(super) fn expect_tokens(id: &str, _file: &str) -> Vec<String> {
    let t = |s: &str| s.to_string();
    let v: Vec<String> = match id {
        // ---------------- jpeg ----------------
        "jpeg-noexif" => vec![t("noexif"), t("baseline"), t("noicc"), t("jpeg-clean")],
        "jpeg-exif6-xmp-o1" => vec![
            t("exif=6"),
            t("xmp"),
            t("xmp-orient=1"),
            t("baseline"),
            t("jpeg-clean"),
        ],
        "jpeg-exif6-xmp-o3" => vec![
            t("exif=6"),
            t("xmp"),
            t("xmp-orient=3"),
            t("baseline"),
            t("jpeg-clean"),
        ],
        "jpeg-untagged" => vec![
            t("jfif"),
            t("baseline"),
            t("noexif"),
            t("noicc"),
            t("jpeg-clean"),
        ],
        "jpeg-icc-srgb" => vec![t("icc=srgbv4"), t("baseline"), t("jpeg-clean")],
        "jpeg-icc-p3" => vec![t("icc=p3v4"), t("baseline"), t("jpeg-clean")],
        "jpeg-icc-p3-v2" => vec![t("icc=p3v2"), t("baseline"), t("jpeg-clean")],
        "jpeg-icc-adobe" => vec![t("icc=adobe"), t("baseline"), t("jpeg-clean")],
        "jpeg-exif-cs0" => vec![t("exif-cs=0"), t("noorient"), t("jpeg-clean")],
        "jpeg-exif-cs1" => vec![t("exif-cs=1"), t("noorient"), t("jpeg-clean")],
        "jpeg-exif-uncal" => vec![t("exif-cs=65535"), t("noorient"), t("jpeg-clean")],
        "jpeg-exif-interop-r03" => vec![
            t("interop=R03"),
            t("exif-cs=65535"),
            t("noorient"),
            t("jpeg-clean"),
        ],
        "jpeg-exif-interop-r98" => vec![
            t("interop=R98"),
            t("exif-cs=65535"),
            t("noorient"),
            t("jpeg-clean"),
        ],
        "jpeg-conflict-icc-p3-exif-cs1" => vec![
            t("icc=p3v4"),
            t("exif-cs=1"),
            t("baseline"),
            t("jpeg-clean"),
        ],
        "jpeg-conflict-icc-srgb-exif-r03" => vec![
            t("icc=srgbv4"),
            t("interop=R03"),
            t("exif-cs=65535"),
            t("baseline"),
            t("jpeg-clean"),
        ],
        "jpeg-conflict-cs1-r03" => vec![
            t("exif-cs=1"),
            t("interop=R03"),
            t("baseline"),
            t("jpeg-clean"),
        ],
        "jpeg-progressive" => vec![t("progressive"), t("jpeg-clean")],
        "jpeg-app14-adobe" => vec![t("app14=1"), t("baseline"), t("noicc"), t("jpeg-clean")],
        "jpeg-rgb-app14" => vec![t("app14=0"), t("baseline"), t("jpeg-clean")],
        "jpeg-ultrahdr-xmp" => vec![
            t("mpf"),
            t("xmp"),
            t("xmp-hdrgm"),
            t("noiso21496"),
            t("jpeg-clean"),
        ],
        "jpeg-ultrahdr-iso" => vec![
            t("mpf"),
            t("iso21496"),
            t("noxmp"),
            t("gainmap"),
            t("jpeg-clean"),
        ],
        "jpeg-ultrahdr" => vec![
            t("mpf"),
            t("xmp"),
            t("iso21496"),
            t("gainmap"),
            t("jpeg-clean"),
        ],
        "jpeg-ultrahdr-mpf-corrupt" => {
            vec![
                t("mpf"),
                t("mpf-corrupt"),
                t("xmp"),
                t("iso21496"),
                t("gainmap"),
                t("jpeg-clean"),
            ]
        }

        // ---------------- png ----------------
        "png-untagged" => vec![
            t("ct=2"),
            t("bd=8"),
            t("nochunk=iCCP"),
            t("nochunk=cICP"),
            t("nochunk=sRGB"),
            t("nochunk=eXIf"),
            t("nochunk=gAMA"),
            t("nochunk=cHRM"),
        ],
        "png-srgb" => vec![
            t("ct=2"),
            t("bd=8"),
            t("chunk=sRGB"),
            t("nochunk=iCCP"),
            t("nochunk=cICP"),
        ],
        "png-iccp-srgb" => vec![
            t("ct=2"),
            t("bd=8"),
            t("chunk=iCCP"),
            t("icc=srgbv4"),
            t("nochunk=cICP"),
            t("nochunk=sRGB"),
        ],
        "png-iccp-p3" => vec![
            t("ct=2"),
            t("bd=8"),
            t("chunk=iCCP"),
            t("icc=p3v4"),
            t("nochunk=cICP"),
        ],
        "png-cicp-srgb" => vec![t("ct=2"), t("bd=8"), t("cicp=1/13/0/1"), t("nochunk=iCCP")],
        "png-cicp-p3" => vec![t("ct=2"), t("bd=8"), t("cicp=12/13/0/1"), t("nochunk=iCCP")],
        "png-exif-r03" => vec![
            t("ct=2"),
            t("chunk=eXIf"),
            t("interop=R03"),
            t("exif-cs=65535"),
        ],
        "png-gama-only" => vec![
            t("ct=2"),
            t("bd=8"),
            t("chunk=gAMA"),
            t("nochunk=iCCP"),
            t("nochunk=cICP"),
            t("nochunk=sRGB"),
            t("nochunk=cHRM"),
        ],
        "png-exif-orient6" => vec![t("ct=2"), t("chunk=eXIf"), t("exif=6")],
        "png-conflict-iccp-p3-cicp-srgb" => vec![t("ct=2"), t("icc=p3v4"), t("cicp=1/13/0/1")],
        "png-conflict-iccp-srgb-cicp-p3" => vec![t("ct=2"), t("icc=srgbv4"), t("cicp=12/13/0/1")],
        "png-srgb-chunk-plus-iccp-p3" => vec![t("ct=2"), t("chunk=sRGB"), t("icc=p3v4")],
        "png-gama-chrm-p3" => vec![t("ct=2"), t("chunk=gAMA"), t("chunk=cHRM")],
        "png-alpha" => vec![t("ct=6"), t("alpha"), t("bd=8")],
        "png16-untagged" => vec![
            t("bd=16"),
            t("ct=2"),
            t("nochunk=iCCP"),
            t("nochunk=cICP"),
            t("nochunk=sRGB"),
        ],
        "png16-p3" => vec![t("bd=16"), t("ct=2"), t("icc=p3v4")],
        "png16-alpha" => vec![t("ct=6"), t("alpha"), t("bd=16")],
        "png-apng" => vec![t("chunk=acTL"), t("chunk=fcTL")],
        "png-palette-trns" => vec![t("ct=3"), t("chunk=PLTE"), t("chunk=tRNS"), t("bd=8")],

        // ---------------- webp ----------------
        "webp-untagged" => vec![t("nochunk=ICCP"), t("nochunk=EXIF")],
        "webp-icc-srgb" => vec![t("chunk=ICCP"), t("icc=srgbv4")],
        "webp-icc-p3" => vec![t("chunk=ICCP"), t("icc=p3v4")],
        "webp-exif-orient6" => vec![t("chunk=EXIF"), t("exif=6")],
        "webp-exif-cs1" => vec![t("chunk=EXIF"), t("exif-cs=1")],
        "webp-alpha-lossy" => vec![t("chunk=ALPH")],

        // ---------------- avif ----------------
        "avif-untagged" => vec![t("nocolr"), t("item=av01")],
        "avif-icc-srgb" => vec![t("colr=prof"), t("icc=srgbv4"), t("item=av01")],
        "avif-icc-p3" => vec![t("colr=prof"), t("icc=p3v4"), t("item=av01")],
        "avif-cicp-srgb" => vec![t("nclx=1/13/6/1"), t("noicc"), t("item=av01")],
        "avif-cicp-p3" => vec![t("nclx=12/13/6/1"), t("item=av01")],
        "avif-exif-orient6" => vec![t("item=Exif"), t("exif=6"), t("item=av01")],
        "avif-exif-r03" => vec![
            t("item=Exif"),
            t("interop=R03"),
            t("exif-cs=65535"),
            t("item=av01"),
        ],
        "avif-conflict-icc-p3-cicp-srgb" => vec![
            t("colr=prof"),
            t("colr=nclx"),
            t("icc=p3v4"),
            t("nclx=1/13/6/1"),
        ],
        "avif-irot3-exif6" => vec![t("irot=3"), t("item=Exif"), t("exif=6"), t("item=av01")],
        "avif-alpha" => vec![t("alpha"), t("item=av01")],
        "avif-10bit" => vec![t("item=av01"), t("prop=av1C")],
        // r13 §2: matrix/subsampling/depth/range fixtures — the nclx decl
        // is container-injected (zenavif 11033c9 can't write mc=1), the
        // av1sub/av1depth tokens assert the coded stream format.
        "avif-cicp-srgb-mc1" => vec![
            t("nclx=1/13/1/1"),
            t("noicc"),
            t("av1sub=444"),
            t("item=av01"),
        ],
        "avif-420-srgb-mc6" => vec![
            t("nclx=1/13/6/1"),
            t("noicc"),
            t("av1sub=420"),
            t("item=av01"),
        ],
        "avif-420-srgb-mc1" => vec![
            t("nclx=1/13/1/1"),
            t("noicc"),
            t("av1sub=420"),
            t("item=av01"),
        ],
        "avif-10bit-cicp-srgb" => vec![
            t("nclx=1/13/6/1"),
            t("noicc"),
            t("av1depth=10"),
            t("item=av01"),
        ],
        "avif-cicp-srgb-limited" => vec![
            t("nclx=1/13/6/0"),
            t("noicc"),
            t("av1sub=444"),
            t("item=av01"),
        ],
        "avif-tmap" => vec![t("item=tmap"), t("gainmap"), t("item=av01")],
        "avif-tmap-archived-serializer" => {
            vec![t("item=tmap"), t("gainmap"), t("item=av01")]
        }

        // ---------------- jxl ----------------
        "jxl-icc-srgb" => vec![t("jbox=jxlc"), t("jorient=1")],
        "jxl-icc-p3" => vec![t("jbox=jxlc"), t("jorient=1")],
        "jxl-enum-srgb" => vec![t("jbox=jxlc"), t("jorient=1")],
        "jxl-enum-p3" => vec![t("jbox=jxlc"), t("jorient=1")],
        "jxl-exif-orient6" => vec![t("jbox=Exif"), t("exif=6"), t("jorient=1")],
        "jxl-alpha" => vec![t("jbox=jxlc"), t("jorient=1")],
        "jxl-lossy" => vec![t("jbox=jxlc"), t("jorient=1")],
        "jxl-jhgm" => vec![t("jbox=jhgm"), t("gainmap"), t("jorient=1")],

        // ---------------- heic ----------------
        "heic-remux-base" => vec![
            t("item=grid"),
            t("item=mime"),
            t("mime=application/rdf+xml"),
            t("item=Exif"),
            t("dinf"),
            // grid primary carries no colr; prof lives on the 48 tiles
            t("colrany=prof"),
        ],
        // The pinned donor's thumbnail carries a malformed `colr 'prof'`
        // with zero ICC payload — verify it byte-exactly, so a donor or
        // remux change that alters the malformed signal fails loudly.
        "heic-tile-base" => vec![
            t("item=hvc1"),
            t("prop=ispe"),
            t("prop=hvcC"),
            t("colr=prof"),
            t("proflen=0"),
            t("irot=0"),
        ],
        "heic-exif-orient6" => vec![t("item=Exif"), t("exif=6"), t("item=hvc1")],
        "heic-colr-srgb" => vec![t("nclx=1/13/6/1"), t("item=hvc1")],
        "heic-colr-p3" => vec![t("nclx=12/13/6/1"), t("item=hvc1")],
        "heic-nocolr" => vec![t("nocolr"), t("item=hvc1")],
        "heic-exif-r03" => vec![
            t("item=Exif"),
            t("interop=R03"),
            t("exif-cs=65535"),
            t("item=hvc1"),
        ],
        "heic-icc-p3" => vec![t("colr=prof"), t("icc=p3v4"), t("item=hvc1")],
        "heic-colr-conflict" => vec![
            t("colr=prof"),
            t("colr=nclx"),
            t("icc=p3v4"),
            t("nclx=1/13/6/1"),
        ],
        // nclx 1/13/6/limited + ICC prof — declares a range the codestream
        // doesn't use (the donor is full-range).
        "heic-colr-conflict-range" => vec![
            t("colr=prof"),
            t("colr=nclx"),
            t("icc=p3v4"),
            t("nclx=1/13/6/0"),
        ],
        "heic-irot3-exif1" => vec![t("irot=3"), t("item=Exif"), t("exif=1")],
        "heic-irot3-exif6" => vec![t("irot=3"), t("item=Exif"), t("exif=6")],

        // dynamic ids from loops handled below
        _ => dynamic(id),
    };
    if v.is_empty() {
        panic!("no signalling expectations defined for fixture {id}");
    }
    v
}

fn dynamic(id: &str) -> Vec<String> {
    let t = |s: String| s;
    if let Some(n) = id.strip_prefix("jpeg-exif-o")
        && let Ok(o) = n.parse::<u8>()
    {
        return vec![
            t(format!("exif={o}")),
            t("baseline".into()),
            t("jpeg-clean".into()),
        ];
    }
    if let Some(n) = id.strip_prefix("jpeg-baked-o")
        && let Ok(_o) = n.parse::<u8>()
    {
        return vec![
            t("exif=1".into()),
            t("baseline".into()),
            t("jpeg-clean".into()),
        ];
    }
    if let Some(n) = id.strip_prefix("avif-irot")
        && id != "avif-irot3-exif6"
        && let Ok(a) = n.parse::<u8>()
    {
        return vec![t(format!("irot={a}")), t("item=av01".into())];
    }
    if let Some(n) = id.strip_prefix("avif-imir")
        && let Ok(a) = n.parse::<u8>()
    {
        return vec![t(format!("imir={a}")), t("item=av01".into())];
    }
    if let Some(n) = id.strip_prefix("heic-irot")
        && !id.contains("-exif")
        && let Ok(a) = n.parse::<u8>()
    {
        return vec![t(format!("irot={a}")), t("item=hvc1".into())];
    }
    if let Some(n) = id.strip_prefix("heic-imir")
        && let Ok(a) = n.parse::<u8>()
    {
        return vec![t(format!("imir={a}")), t("item=hvc1".into())];
    }
    if let Some(n) = id.strip_prefix("jxl-orient")
        && let Ok(o) = n.parse::<u8>()
    {
        return vec![t(format!("jorient={o}"))];
    }
    Vec::new()
}
