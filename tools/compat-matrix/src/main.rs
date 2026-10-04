//! compat-matrix tool: `generate` writes fixtures + manifests, `probe` is the
//! zen-reader adapter (decode a file -> PNG + JSON stats), `demux` inspects a
//! HEIF container for debugging remuxes.

mod classify;
mod matrix;

use std::path::PathBuf;

pub(crate) fn usage() -> ! {
    eprintln!(
        "usage:\n  compat-matrix generate <out_dir> --heic-base <corpus.heic>\n  compat-matrix probe <input> <out.png> [--raw] [--json out.json]
  compat-matrix dump-icc <input> <out.icc>
  compat-matrix dump-profiles <dir>\n  compat-matrix demux <input.heic>\n  compat-matrix thumb <in.png> <out.png>   # <=1024px long-side 8-bit stored render\n  compat-matrix selftest <fixtures_dir> [--threshold N]\n  compat-matrix classify <out.png> <fixtures_dir> <fixture_id>
  compat-matrix calibrate <fixtures_dir> <matrix_out_dir>
  compat-matrix matrix <fixtures_dir> <matrix_out_dir> [--check]"
    );
    std::process::exit(2);
}

fn main() {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("generate") => cmd_generate(args.collect()),
        Some("probe") => cmd_probe(args.collect()),
        Some("demux") => cmd_demux(args.collect()),
        Some("thumb") => cmd_thumb(args.collect()),
        Some("selftest") => classify::cmd_selftest(args.collect()),
        Some("classify") => classify::cmd_classify(args.collect()),
        Some("calibrate") => classify::cmd_calibrate(args.collect()),
        Some("matrix") => matrix::cmd_matrix(args.collect()),
        Some("dump-icc") => cmd_dump_icc(args.collect()),
        Some("dump-profiles") => cmd_dump_profiles(args.collect()),
        _ => usage(),
    }
}

fn cmd_generate(args: Vec<String>) {
    let mut out_dir: Option<PathBuf> = None;
    let mut heic_base: Option<PathBuf> = None;
    let mut it = args.into_iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--heic-base" => heic_base = it.next().map(PathBuf::from),
            s if out_dir.is_none() => out_dir = Some(PathBuf::from(s)),
            _ => usage(),
        }
    }
    let out_dir = out_dir.unwrap_or_else(|| PathBuf::from("fixtures"));
    let heic_base = heic_base.unwrap_or_else(|| {
        // CM_HEIC_BASE / --heic-base: the corpus donor the HEIC remux
        // fixtures derive from (iPhone 8 Plus 48-tile grid). The canonical
        // copy is the one the census measures — corpus-relative under
        // CM_CORPUS_ROOT.
        std::env::var_os("CM_HEIC_BASE")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                eprintln!("heic donor: set --heic-base or CM_HEIC_BASE (corpus-relative path under CM_CORPUS_ROOT)");
                if let Some(root) = std::env::var_os("CM_CORPUS_ROOT") {
                    PathBuf::from(root).join("1000-lilith-photos-general/1071_general_illuminated-castle-night_flight-hippogriff-orlando_ip8plus_iso160-f1p8_img-9988_4032x3024.heic")
                } else {
                    usage();
                }
            })
    });
    // Donor pin (round-10 M-1): the HEIC remux fixtures are derived from one
    // recorded donor version — the canonical corpus copy the census
    // measures. Another copy of the same filename (June backup, variants
    // dir) carries different item payloads (XMP mime item, thumbnail prof
    // length) and silently produces different fixtures; fail loudly.
    {
        let bytes = std::fs::read(&heic_base)
            .unwrap_or_else(|e| panic!("heic donor {}: {e}", heic_base.display()));
        let sha = compat_matrix::generate::sha256_hex_pub(&bytes);
        assert_eq!(
            sha,
            compat_matrix::generate::HEIC_DONOR_SHA256,
            "heic donor {} sha256 {sha} != pinned {} — the HEIC fixtures \
             must derive from the canonical corpus copy the census measures",
            heic_base.display(),
            compat_matrix::generate::HEIC_DONOR_SHA256
        );
        eprintln!("heic donor: {} sha256 {sha}", heic_base.display());
    }
    std::fs::create_dir_all(&out_dir).expect("mkdir");
    let rows = compat_matrix::generate::generate_all(&out_dir, &heic_base).unwrap_or_else(|e| {
        eprintln!("generate failed: {e}");
        std::process::exit(1);
    });
    compat_matrix::manifest::write_fixtures_tsv(&rows, &out_dir.join("fixtures.tsv"))
        .expect("fixtures.tsv");
    compat_matrix::manifest::write_hypotheses_tsv(&rows, &out_dir.join("hypotheses.tsv"))
        .expect("hypotheses.tsv");
    eprintln!("{} fixtures -> {}", rows.len(), out_dir.display());
}

fn cmd_probe(args: Vec<String>) {
    let mut input: Option<PathBuf> = None;
    let mut png_out: Option<PathBuf> = None;
    let mut json_out: Option<PathBuf> = None;
    let mut pfm_out: Option<PathBuf> = None;
    let mut raw = false;
    let mut meta = false;
    let mut unmanaged = false;
    let mut no_icc = false;
    let mut drop_depth = false;
    let mut drop_transform = false;
    let mut remux_out: Option<PathBuf> = None;
    let mut it = args.into_iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--raw" => raw = true,
            "--meta" => meta = true,
            "--unmanaged" => unmanaged = true,
            "--no-icc" => no_icc = true,
            "--drop-depth" => drop_depth = true,
            "--drop-transform" => drop_transform = true,
            "--json" => json_out = it.next().map(PathBuf::from),
            "--hdr" => pfm_out = it.next().map(PathBuf::from),
            "--remux" => remux_out = it.next().map(PathBuf::from),
            s if input.is_none() => input = Some(PathBuf::from(s)),
            s if png_out.is_none() => png_out = Some(PathBuf::from(s)),
            _ => usage(),
        }
    }
    // --remux needs only the input: it writes the stripped HEIF bytes and
    // exits before decode (managed_hyps feeds them to a reference decoder).
    let (input, png_out) = match (input, png_out, &remux_out) {
        (Some(i), _, Some(_)) => (i, PathBuf::new()),
        (Some(i), Some(o), None) => (i, o),
        _ => usage(),
    };
    let mut data = std::fs::read(&input).unwrap_or_else(|e| {
        eprintln!("read {}: {e}", input.display());
        std::process::exit(1);
    });
    if unmanaged || no_icc || drop_depth || drop_transform {
        // Hypothesis-render decode bases for HEIF corpus fixtures:
        //   --unmanaged: strip every `colr` on every item  = "reader honours
        //     no colour signalling" (`corpus:stored`).
        //   --no-icc:    strip only `prof`/`rICC` colr     = "reader honours
        //     the nclx matrix, ignores ICC" (base for `corpus:color=` hyps).
        //   --drop-transform: drop `irot`/`imir`/`clap` on every item — the
        //     stored-pixel base must be the coded raster; heif-convert
        //     applies the display transform and has no flag to skip it, so
        //     leaving the properties in makes every orientation hypothesis
        //     double-apply the rotation (round-12 H-1).
        //   --drop-depth: drop items whose auxC is `auxid:2` — real iPhone
        //     HEICs aux-link their depth map to both the photo and the tmap
        //     gainmap, a web libheif 1.17 refuses outright; the reference
        //     render of the primary needs the container repaired, its pixel
        //     payload untouched.
        // zencodecs applies a primary-item `prof` even in the raw path, which
        // would leak zen's ICC-over-nclx precedence into the baseline.
        let dm = compat_matrix::heif::Demux::load(&data)
            .unwrap_or_else(|e| panic!("strip-colr: demux {}: {e}", input.display()));
        let all: Vec<u32> = dm.items.iter().map(|i| i.item_id).collect();
        let mut sig = compat_matrix::heif::RemuxSignalling::default().rotate_items(all);
        if drop_depth {
            sig.drop_items = compat_matrix::heif::items_with_aux(&dm, b"auxid:2");
        }
        if drop_transform {
            sig.irot = Some(None);
            sig.imir = Some(None);
            sig = sig.dropping(b"clap");
        }
        if unmanaged {
            sig = sig.with_colr(None);
        } else if no_icc {
            sig.drop_icc_colr = true;
        }
        data = compat_matrix::heif::remux(&dm, &sig)
            .unwrap_or_else(|e| panic!("strip-colr: remux {}: {e}", input.display()));
    }
    if let Some(p) = remux_out {
        std::fs::write(&p, &data).expect("write remux");
        return;
    }
    if let Some(pfm) = pfm_out {
        match compat_matrix::probe::probe_hdr(&data, &pfm) {
            Ok(info) => eprintln!("hdr: {info}"),
            Err(e) => eprintln!("hdr: {e}"),
        }
    }
    let out = if meta {
        compat_matrix::probe::probe_meta(&data)
    } else if raw {
        compat_matrix::probe::probe_raw(&data)
    } else {
        compat_matrix::probe::probe(&data)
    };
    if out.status == "ok" && !out.png.is_empty() {
        std::fs::write(&png_out, &out.png).expect("write png");
    }
    let json = format!(
        "{{\"status\":\"{}\",\"w\":{},\"h\":{},\"ms\":{:.2},\"version\":\"{}\",\"format\":\"{}\",\"orientation_reported\":{},\"orient_applied\":{},\"source_color\":\"{}\",\"colour_path\":\"{}\",\"gainmap\":\"{}\",\"gainmap_w\":{},\"gainmap_h\":{},\"mean\":[{:.2},{:.2},{:.2}],\"std\":[{:.2},{:.2},{:.2}],\"error_head\":\"{}\"}}",
        out.status,
        out.w,
        out.h,
        out.ms,
        out.version,
        out.format.replace('"', "'"),
        out.orientation_reported,
        out.orient_applied,
        out.source_color.replace('"', "'"),
        out.colour_path,
        out.gainmap,
        out.gainmap_w,
        out.gainmap_h,
        out.mean[0],
        out.mean[1],
        out.mean[2],
        out.std[0],
        out.std[1],
        out.std[2],
        out.error_head.replace('"', "'")
    );
    match json_out {
        Some(p) => std::fs::write(p, json).expect("write json"),
        None => println!("{json}"),
    }
    if out.status != "ok" {
        std::process::exit(3);
    }
}

/// `thumb <in.png> <out.png>` — the stored matrix-cell render: zenpng
/// decode, zenresize Lanczos downscale to <=1024 long side (no upscale),
/// zenpng 8-bit encode. Run dirs store this, not full-resolution outputs;
/// classification always ran on the full render before it reaches here.
fn cmd_thumb(args: Vec<String>) {
    let (inp, outp) = match (args.first(), args.get(1)) {
        (Some(i), Some(o)) => (PathBuf::from(i), PathBuf::from(o)),
        _ => usage(),
    };
    let img = compat_matrix::score::load_png(&inp).expect("decode png");
    // M-6: thumbs must be the classifier's own box-downscale so a stored
    // run-dir thumb classifies identically to the full-res render it
    // records (corpus_space's stage-1) — a Lanczos thumb diverges from
    // the box chain by ~17 p99 on photo detail and flips cells to other.
    let ds = compat_matrix::score::downscale(&img, compat_matrix::score::THUMB_SIDE);
    let (tw, th, px) = (ds.w, ds.h, ds.px);
    let px4: Vec<rgb::Rgba<u8>> = px
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
    let mut png = zenpng::encode_rgba8(
        imgref::ImgRef::new(&px4, tw as usize, th as usize),
        None,
        &zenpng::EncodeConfig::default(),
        &enough::Unstoppable,
        &enough::Unstoppable,
    )
    .expect("png encode");
    // r13: the thumb must carry the source render's colour declaration —
    // run-dir cells store thumbs, and the tagged column scores what they
    // declare (cICP > iCCP > sRGB > gAMA+cHRM).
    if let Ok(src) = std::fs::read(&inp) {
        compat_matrix::score::png_copy_colour_chunks(&mut png, &src);
    }
    std::fs::write(&outp, png).expect("write thumb");
}

fn cmd_demux(args: Vec<String>) {
    let path = match args.first() {
        Some(p) => PathBuf::from(p),
        None => usage(),
    };
    let data = std::fs::read(&path).expect("read");
    let top = compat_matrix::heif::parse_boxes(&data).expect("boxes");
    for b in &top {
        println!(
            "top: {:?} {} bytes",
            std::str::from_utf8(&b.ty).unwrap_or("?"),
            b.data.len()
        );
        if &b.ty == b"meta" {
            let meta_children =
                compat_matrix::heif::parse_boxes(&b.data[4..]).expect("meta children");
            for c in &meta_children {
                println!(
                    "  meta: {:?} {} bytes",
                    std::str::from_utf8(&c.ty).unwrap_or("?"),
                    c.data.len()
                );
            }
            let dm = compat_matrix::heif::Demux::load(&data).expect("demux");
            println!("primary: {}", dm.primary);
            for e in &dm.items {
                println!(
                    "  item {} type {:?} hidden={} name={} props={:?}",
                    e.item_id,
                    std::str::from_utf8(&e.item_type).unwrap_or("?"),
                    e.hidden,
                    e.name,
                    dm.props_for(e.item_id)
                );
            }
            for (i, p) in dm.ipco.iter().enumerate() {
                println!(
                    "  ipco[{}] {:?} {} bytes",
                    i + 1,
                    std::str::from_utf8(&p.ty).unwrap_or("?"),
                    p.data.len()
                );
            }
            for (rt, refs) in &dm.iref {
                println!(
                    "  iref {:?}: {:?}",
                    std::str::from_utf8(rt).unwrap_or("?"),
                    refs
                );
            }
            println!("  primary dims: {:?}", dm.dims_of(dm.primary));
            println!("  grid dims: {:?}", dm.grid_dims());
        }
    }
}

/// `dump-icc <input> <out.icc>` — write the embedded ICC profile (or empty).
fn cmd_dump_icc(args: Vec<String>) {
    if args.len() != 2 {
        eprintln!("usage: compat-matrix dump-icc <input> <out.icc>");
        std::process::exit(2);
    }
    let data = std::fs::read(&args[0]).expect("read input");
    let icc = compat_matrix::icc::extract_icc(&data).unwrap_or_default();
    std::fs::write(&args[1], &icc).expect("write icc");
    println!("{} bytes", icc.len());
}

/// `dump-profiles <dir>` — write the equivalent-ICC set (p3 v4/v2, adobe, srgb).
fn cmd_dump_profiles(args: Vec<String>) {
    if args.len() != 1 {
        eprintln!("usage: compat-matrix dump-profiles <dir>");
        std::process::exit(2);
    }
    let dir = std::path::Path::new(&args[0]);
    std::fs::create_dir_all(dir).expect("mkdir");
    for (name, bytes) in [
        ("display-p3-v4.icc", compat_matrix::icc::display_p3_icc_v4()),
        ("display-p3-v2.icc", compat_matrix::icc::display_p3_icc_v2()),
        ("adobe-rgb.icc", compat_matrix::icc::adobe_rgb_icc_v2()),
    ] {
        std::fs::write(dir.join(name), bytes).expect("write icc");
    }
    std::fs::write(dir.join("srgb.icc"), compat_matrix::icc::srgb_icc_v4()).expect("write icc");
}
