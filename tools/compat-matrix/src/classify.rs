//! Classification family: hypothesis loading, calibrated thresholds,
//! selftest/classify/calibrate/matrix subcommands.

use std::path::Path;
use std::path::PathBuf;

pub(crate) const MAX_SIDE: u32 = 512;

/// Orientation steps a hypothesis spec applies to the stored pattern
/// (synth) — corpus specs carry no pattern so they get no rects.
fn orient_steps(spec: &str) -> Vec<u8> {
    let kv = |k: &str| -> Option<u8> {
        spec.split([';', ':'])
            .find_map(|p| p.strip_prefix(&format!("{k}=")))
            .and_then(|v| v.parse().ok())
    };
    if let Some(rest) = spec.strip_prefix("synth-baked:") {
        let _ = rest;
        vec![kv("o").unwrap_or(1), kv("orient").unwrap_or(1)]
    } else if spec.starts_with("synth:") {
        vec![kv("orient").unwrap_or(1)]
    } else {
        Vec::new()
    }
}

/// The applied orientation a hypothesis renders — from its spec:
/// `synth:orient=N` / `corpus:orient=N` → N; `corpus:as-signalled` → the
/// manifest's expected orientation; `stored`/`color=` bases are the
/// unrotated raster (1). Specs without an orientation axis return 1.
pub(crate) fn hyp_orient(spec: &str, expect_orient: u8) -> u8 {
    let kv = |k: &str| -> Option<u8> {
        spec.split([';', ':'])
            .find_map(|p| p.strip_prefix(&format!("{k}=")))
            .and_then(|v| v.parse().ok())
    };
    if spec.starts_with("corpus:as-signalled") {
        expect_orient
    } else {
        kv("orient").unwrap_or(1)
    }
}

/// Whether the fixture carries an orientation axis at all — its hyp set
/// renders more than one distinct orientation state.
pub(crate) fn is_orientation_fixture(r: &compat_matrix::manifest::FixtureRow) -> bool {
    r.hyps
        .iter()
        .map(|h| hyp_orient(&h.spec, r.expect_orient))
        .collect::<std::collections::HashSet<_>>()
        .len()
        > 1
}

/// Level tolerance: +/-2 for lossless fixtures, +/-4 for lossy (q>=95).
fn tol_for(r: &compat_matrix::manifest::FixtureRow) -> f64 {
    let f = r.file.to_lowercase();
    if f.ends_with(".png")
        || (f.ends_with(".jxl") && !r.id.contains("lossy"))
        || (f.ends_with(".webp") && r.id.contains("lossless"))
    {
        2.0
    } else {
        4.0
    }
}

/// True when the fixture content is the synthetic pattern (so the patch
/// rects apply). Corpus-content fixtures (heic photo tile, palette
/// swatches) use the whole-image distance instead.
fn is_pattern_fixture(r: &compat_matrix::manifest::FixtureRow) -> bool {
    !r.hyps.is_empty()
        && r.hyps.iter().all(|h| h.spec.starts_with("synth"))
        && r.id != "png-palette-trns"
}

/// Load a fixture's hypotheses as scorer inputs with orientation-mapped
/// patch rects.
pub(crate) fn load_hypins(
    fixtures_dir: &Path,
    r: &compat_matrix::manifest::FixtureRow,
) -> Vec<compat_matrix::score::HypIn> {
    use compat_matrix::score::{HypIn, Rect, map_rect_orient};
    // For synth-baked rows the manifest stores POST-bake dims; the patch
    // layout is defined on the PRE-bake pattern, so base rects need the
    // pattern dims (transposes swap them back out).
    let (bw, bh) = if r.hyps.iter().all(|h| h.spec.starts_with("synth-baked:")) {
        let o: u8 = r
            .hyps
            .first()
            .and_then(|h| {
                h.spec
                    .split(';')
                    .find_map(|p| p.strip_prefix("synth-baked:o="))
                    .and_then(|v| v.split(';').next()?.parse().ok())
            })
            .unwrap_or(1);
        if o >= 5 { (r.h, r.w) } else { (r.w, r.h) }
    } else {
        (r.w, r.h)
    };
    let mut base: Vec<Rect> = if is_pattern_fixture(r) {
        compat_matrix::pattern::patch_layout(bw, bh)
            .iter()
            .map(|p| Rect {
                x: p.x,
                y: p.y,
                w: p.w,
                h: p.h,
            })
            .collect()
    } else {
        Vec::new()
    };
    // Alpha fixtures get an extra rect on the alpha ramp band — without it
    // the RGB patches are identical across alpha hyps and they collapse.
    if r.hyps.iter().any(|h| h.spec.contains("alpha=")) && !base.is_empty() {
        base.push(Rect {
            x: 0,
            y: bh * 3 / 4 + 2,
            w: bw,
            h: (bh / 4).saturating_sub(4).max(1),
        });
    }
    // Gain-map fixtures need a rect inside the top-third boost wedge —
    // the standard patch strip (y .60-.71h) sits outside it, so an output
    // that applied the map was indistinguishable from the SDR base.
    if r.hyps.iter().any(|h| h.spec.contains("tonemap=")) && !base.is_empty() {
        base.push(Rect {
            x: bw / 4,
            y: bh / 12,
            w: bw / 2,
            h: (bh / 6).max(1),
        });
    }
    let hyp_dir = fixtures_dir.join("hyps").join(&r.id);
    r.hyps
        .iter()
        .map(|h| {
            let p = hyp_dir.join(format!("{}.png", h.name));
            let img = compat_matrix::score::load_png(&p)
                .unwrap_or_else(|e| panic!("hypothesis render {} for {}: {e}", p.display(), r.id));
            let mut rects = base.clone();
            let (mut pw, mut ph) = (bw, bh);
            for o in orient_steps(&h.spec) {
                let (mut nw, mut nh) = (pw, ph);
                for rr in rects.iter_mut() {
                    let (nr, dw, dh) = map_rect_orient(*rr, pw, ph, o);
                    nw = dw;
                    nh = dh;
                    *rr = nr;
                }
                pw = nw;
                ph = nh;
            }
            HypIn {
                name: h.name.clone(),
                img,
                correct: h.correct,
                rects,
            }
        })
        .collect()
}

pub(crate) fn cmd_selftest(args: Vec<String>) {
    let mut dir: Option<PathBuf> = None;
    let mut thr_override: Option<f64> = None;
    let mut it = args.into_iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--threshold" => thr_override = it.next().and_then(|v| v.parse().ok()),
            s if dir.is_none() => dir = Some(PathBuf::from(s)),
            _ => crate::usage(),
        }
    }
    let dir = dir.unwrap_or_else(|| crate::usage());
    let rows = compat_matrix::manifest::load_fixtures(&dir).expect("load fixtures");
    let mut collapsed_total = 0;
    for r in &rows {
        let hypins = load_hypins(&dir, r);
        // Separation gate: pattern pairs must differ >=4 levels at a patch
        // centre; corpus pairs are separable iff their pair distance reaches
        // the fine decode-noise bound (round-12 L-1: one collapse rule for
        // matrix, classify and selftest — the calibrated corpus T selects the
        // nearest hypothesis only). --threshold overrides the corpus gate only.
        let thr = thr_override.unwrap_or(compat_matrix::score::FINE_T);
        let collapsed = compat_matrix::score::self_test_patched(
            &hypins,
            compat_matrix::score::FINE_T,
            1.0,
            thr,
            MAX_SIDE,
        );
        for (a, b, d, mx) in &collapsed {
            collapsed_total += 1;
            println!("{}	{a}	{b}	{d:.2}	{mx:.2}	indistinguishable", r.id);
        }
    }
    eprintln!("{collapsed_total} indistinguishable hypothesis pairs");
}

pub(crate) fn cmd_classify(args: Vec<String>) {
    let mut it = args.into_iter();
    let (png, dir, id) = match (it.next(), it.next(), it.next()) {
        (Some(p), Some(d), Some(i)) => (PathBuf::from(p), PathBuf::from(d), i),
        _ => crate::usage(),
    };
    let rows = compat_matrix::manifest::load_fixtures(&dir).expect("load fixtures");
    let r = rows.iter().find(|r| r.id == id).unwrap_or_else(|| {
        eprintln!("unknown fixture {id}");
        std::process::exit(2);
    });
    let hypins = load_hypins(&dir, r);
    // r13 H-1: raw pixels score as returned; a second, tagged scoring
    // interprets them through the output PNG's own colour declaration
    // (reported on stderr).
    let (out, bytes) = std::fs::read(&png)
        .ok()
        .and_then(|b| {
            compat_matrix::score::decode_png(&b)
                .ok()
                .map(|img| (img, b))
        })
        .expect("load output");
    let cal = load_calibration(&dir);
    let t = t_for(r, &cal);
    // Same single collapse rule as `matrix`/`selftest`: FINE_T decides
    // distinguishability; the calibrated `t` still scores nearest/margin.
    let collapsed = compat_matrix::score::self_test_patched(
        &hypins,
        compat_matrix::score::FINE_T,
        1.0,
        compat_matrix::score::FINE_T,
        MAX_SIDE,
    );
    let (verdict, scored, note) =
        compat_matrix::score::classify_patched(&out, &hypins, t, MAX_SIDE, &collapsed);
    // `correct` flag for the sweep's baseline gate: 1 iff the verdict names
    // a correct-labelled hypothesis (margin/collapse not-measurable = 0).
    let correct = r.hyps.iter().any(|h| h.name == verdict && h.correct) as u8;
    let tagged = compat_matrix::score::classify_tagged(
        &out,
        &bytes,
        &compat_matrix::score::RawScoring {
            scored: &scored,
            verdict: &verdict,
            correct: correct == 1,
            src_colour: r.colour,
        },
        &hypins,
        t,
        MAX_SIDE,
        &collapsed,
    );
    if !tagged.profile.is_empty() || tagged.verdict != verdict {
        eprintln!(
            "out_profile: {} | verdict_tagged: {} ({})",
            if tagged.profile.is_empty() {
                "untagged"
            } else {
                &tagged.profile
            },
            tagged.verdict,
            tagged.correct
        );
    }
    let dists: Vec<String> = scored
        .iter()
        .map(|s| format!("{}:{:.2}/{:.2}", s.name, s.dist, s.dmax))
        .collect();
    println!("{verdict}\t{correct}\t{note}\t{}", dists.join("\t"));
}

#[derive(serde::Deserialize, Default)]
#[serde(default)]
pub(crate) struct AdapterJson {
    pub(crate) status: String,
    pub(crate) w: u32,
    pub(crate) h: u32,
    pub(crate) ms: f64,
    pub(crate) version: String,
    pub(crate) error_head: String,
    /// false when the output is a composited screenshot that cannot prove
    /// alpha handling (browser adapters emit this).
    pub(crate) alpha_measurable: Option<bool>,
    /// sha256 of the fixture file the cell ran against (provenance).
    pub(crate) fixture_sha: String,
    /// sha256 of the adapter script that produced the cell — matched
    /// against the run's platform.txt `adapter=` lines by the producer gate.
    pub(crate) adapter_sha: String,
    /// docker image id the cell was produced under — matched against
    /// platform.txt's image records, paired by adapter class ("host" for
    /// natively-produced cells like the zen columns).
    pub(crate) image_id: String,
    /// sha256 of the full-resolution render a reps cell was classified
    /// from, recorded before the run-dir PNG was thumbnailed (M-6).
    pub(crate) output_sha: Option<String>,
    /// sha256 of the PNG that remains on disk after thumbnailing — the
    /// binding for the <=1024px bytes `--check` can still verify once the
    /// full-res render is gone (M-2).
    pub(crate) thumb_sha: Option<String>,
}

/// Per-bucket match thresholds from <fixtures>/calibration.tsv, written by
/// `calibrate`. Falls back to the fixed per-codec tolerance when absent.
pub(crate) fn load_calibration(dir: &Path) -> std::collections::HashMap<String, f64> {
    let mut m = std::collections::HashMap::new();
    if let Ok(txt) = std::fs::read_to_string(dir.join("calibration.tsv")) {
        for line in txt.lines().skip(1) {
            let mut f = line.split('\t');
            if let (Some(k), Some(v)) = (f.next(), f.next())
                && let Ok(t) = v.parse::<f64>()
            {
                m.insert(k.to_string(), t);
            }
        }
    }
    m
}

/// Load a reader-output PNG for calibration: returns (raw pixels,
/// tag-interpreted pixels, interpretation kind). `matrix`'s tagged column
/// applies the same interpretation — the fold must measure the same
/// pixels (r13).
fn load_out_png(
    p: &std::path::Path,
) -> Result<
    (
        compat_matrix::score::Img,
        compat_matrix::score::Img,
        compat_matrix::score::OutInterp,
    ),
    String,
> {
    let b = std::fs::read(p).map_err(|e| format!("read: {e}"))?;
    let img = compat_matrix::score::decode_png(&b)?;
    let (tagged, _name, kind) = compat_matrix::score::out_tagged_pixels(&img, &b);
    Ok((img, tagged, kind))
}

/// True when the fixture's hypotheses are corpus specs (no pattern rects —
/// scored by the p99 per-pixel tail metric, not patch means).
fn is_corpus(r: &compat_matrix::manifest::FixtureRow) -> bool {
    !r.hyps.is_empty() && r.hyps.iter().all(|h| h.spec.starts_with("corpus:"))
}

/// The fixture's match threshold: calibrated bucket value if present, else
/// the lossy/lossless default.
pub(crate) fn t_for(
    r: &compat_matrix::manifest::FixtureRow,
    cal: &std::collections::HashMap<String, f64>,
) -> f64 {
    if is_corpus(r) {
        // corpus bucket = calibrated p99 spread; 8 levels pre-calibration.
        return cal.get("corpus").copied().unwrap_or(8.0);
    }
    let bucket = if tol_for(r) <= 2.0 {
        "lossless"
    } else {
        "lossy"
    };
    cal.get(bucket).copied().unwrap_or_else(|| tol_for(r))
}

/// One adapter subdir inside a calibration input dir.
struct CellDir {
    /// display name — `<dir-basename>/<adapter>` for extra dirs so the
    /// detail sheet names the decoder (e.g. `platforms-r8/imageio-raw`).
    adapter: String,
    path: PathBuf,
}

fn cell_dirs(out: &Path, prefix: &str) -> Vec<CellDir> {
    std::fs::read_dir(out)
        .map(|rd| {
            rd.flatten()
                .filter(|e| e.path().is_dir())
                .map(|e| CellDir {
                    adapter: format!("{}{}", prefix, e.file_name().to_string_lossy()),
                    path: e.path(),
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Extra cell dirs for calibration — `CM_CALIBRATE_EXTRA` carries
/// colon-separated `<dir>=<adapter>,<adapter>,…` entries (e.g. the
/// read-only platform-decode outputs); their cells feed the spread under
/// `<basename>/<adapter>` names. r14 M-3: every entry must name the
/// columns it folds — a bare dir is refused, because folding every column
/// of a host run swept rendered-thumbnail paths (qlmanage/nsimage) into
/// the decode-noise bound once.
fn calibrate_dirs(out: &Path) -> Vec<CellDir> {
    // Every contributing cell dir is named `<dir-basename>/<adapter>` —
    // the run's own cells included — so sibling runs pooled into one
    // canonical artifact name the same sources byte-for-byte.
    let base = out
        .file_name()
        .map(|b| b.to_string_lossy().into_owned())
        .unwrap_or_else(|| "run".to_string());
    let mut v = cell_dirs(out, &format!("{base}/"));
    // `CM_CALIBRATE_POOL`: colon-separated sibling run dirs sharing this
    // fixture set (lts+latest share the synthetic set; reps+reps-latest
    // share the corpus set). Their cells pool into every bucket — one
    // canonical fixtures-dir artifact covers every cell it grades.
    for pool in std::env::var("CM_CALIBRATE_POOL")
        .unwrap_or_default()
        .split(':')
        .filter(|s| !s.is_empty())
    {
        let pb = Path::new(pool)
            .file_name()
            .map(|b| b.to_string_lossy().into_owned())
            .unwrap_or_else(|| "pool".to_string());
        v.extend(cell_dirs(Path::new(pool), &format!("{pb}/")));
    }
    for extra in std::env::var("CM_CALIBRATE_EXTRA")
        .unwrap_or_default()
        .split(':')
        .filter(|s| !s.is_empty())
    {
        let Some((dir, allow)) = extra.split_once('=') else {
            eprintln!(
                "calibrate: CM_CALIBRATE_EXTRA entry {extra:?} names no adapters — \
                 write <dir>=<adapter>[,<adapter>,…] so the fold is explicit"
            );
            std::process::exit(2);
        };
        let base = Path::new(dir)
            .file_name()
            .map(|b| b.to_string_lossy().into_owned())
            .unwrap_or_else(|| "extra".to_string());
        for cd in cell_dirs(Path::new(dir), &format!("{base}/")) {
            let leaf = cd.adapter.rsplit('/').next().unwrap_or("");
            if allow.split(',').any(|a| a == leaf) {
                v.push(cd);
            }
        }
    }
    v
}

/// Derive the match threshold from the cross-reader baseline spread: for
/// baseline fixtures (correct rendition = the stored image), the maximum
/// distance ANY adapter's output sits from the correct hypothesis is the
/// noise floor a real correct output exhibits. T = ceil(that max) + 1,
/// per lossy/lossless bucket. The corpus bucket takes p99+1 over the same
/// idea on untagged sRGB reps — cross-decoder render noise (libde265 vs
/// ImageIO vs WIC is measured ~p99 14–16, max ~60–70 on HEIC alone) plus a
/// 2x-runner-up margin rule in classification covers the rest. Every input
/// cell is recorded in calibration-detail.tsv with the decoder named.
pub(crate) fn cmd_calibrate(args: Vec<String>) {
    let mut it = args.into_iter();
    let (dir, out) = match (it.next(), it.next()) {
        (Some(d), Some(o)) => (PathBuf::from(d), PathBuf::from(o)),
        _ => crate::usage(),
    };
    let rows = compat_matrix::manifest::load_fixtures(&dir).expect("load fixtures");
    let dirs = calibrate_dirs(&out);
    // baseline rows: every working reader should emit the stored rendition
    const BASELINE: &[&str] = &[
        "jpeg-exif-o1",
        "jpeg-noexif",
        "jpeg-untagged",
        "png-untagged",
        "webp-untagged",
        "avif-untagged",
    ];
    let base: Vec<&compat_matrix::manifest::FixtureRow> = rows
        .iter()
        .filter(|r| BASELINE.contains(&r.id.as_str()))
        .collect();
    // M-3: calibration extras must carry fixture_sha — an empty value is
    // refused; a value that names different bytes than this manifest is
    // warned+recorded (same-content cells from a prior fixture generation
    // still measure cross-decoder noise).
    let own_base = out
        .file_name()
        .map(|b| b.to_string_lossy().into_owned())
        .unwrap_or_else(|| "run".to_string());
    let pool_bases: Vec<String> = std::env::var("CM_CALIBRATE_POOL")
        .unwrap_or_default()
        .split(':')
        .filter(|s| !s.is_empty())
        .map(|p| {
            Path::new(p)
                .file_name()
                .map(|b| b.to_string_lossy().into_owned())
                .unwrap_or_else(|| "pool".to_string())
        })
        .collect();
    let is_extra = |cd: &CellDir| {
        !cd.adapter.starts_with(&format!("{own_base}/"))
            && !pool_bases
                .iter()
                .any(|b| cd.adapter.starts_with(&format!("{b}/")))
    };
    let extra_sha_gate = |cd: &CellDir, aj: Option<&AdapterJson>, want: &str| {
        if is_extra(cd) {
            match aj.map(|a| a.fixture_sha.as_str()) {
                Some(s) if s == want => {}
                Some("") | None => {
                    eprintln!("calibrate: {}: extra cell has no fixture_sha", cd.adapter);
                    std::process::exit(2);
                }
                Some(s) => {
                    eprintln!(
                        "calibrate: {}: extra fixture_sha {} != manifest {} (recorded)",
                        cd.adapter, s, want
                    );
                }
            }
        }
    };
    let mut worst: std::collections::HashMap<String, f64> = std::collections::HashMap::new();
    let mut detail = String::from("bucket\tfixture\tadapter\tdist\n");
    for r in &base {
        let bucket = if tol_for(r) <= 2.0 {
            "lossless"
        } else {
            "lossy"
        };
        let hyps = load_hypins(&dir, r);
        let Some(ci) = hyps.iter().position(|h| h.correct) else {
            continue;
        };
        for cd in &dirs {
            // baseline buckets calibrate same-file decode noise across the
            // matrix's own columns — platform extras are cross-decoder
            // evidence for the corpus bucket only (a real platform
            // deviation, e.g. WIC's AVIF pipeline at p99 39, must not
            // inflate the synthetic-fixture thresholds).
            if is_extra(cd) {
                continue;
            }
            let p = cd.path.join(format!("{}.png", r.id));
            let j = cd.path.join(format!("{}.json", r.id));
            // only outputs that decoded OK count toward the spread
            let aj = std::fs::read_to_string(&j)
                .ok()
                .and_then(|s| serde_json::from_str::<AdapterJson>(&s).ok());
            let ok = aj.as_ref().map(|a| a.status == "ok").unwrap_or(false);
            if !ok {
                continue;
            }
            extra_sha_gate(cd, aj.as_ref(), &r.sha256);
            if let Ok((raw, tagged, kind)) = load_out_png(&p) {
                // HDR-declared output isn't an sRGB-comparable reading —
                // exclude rather than let an artificial distance through.
                if kind == compat_matrix::score::OutInterp::Hdr {
                    continue;
                }
                // r13: measure the nearest consistent reading of the cell —
                // a converted output tagged with its source profile
                // (djxl-best 0.12) scores under its raw pixels, a true
                // wide-gamut-tagged output under the conversion.
                let dist_to_correct = |img: &compat_matrix::score::Img| -> f64 {
                    let (_, scored, _) =
                        compat_matrix::score::classify_patched(img, &hyps, f64::MAX, MAX_SIDE, &[]);
                    scored
                        .iter()
                        .find(|s| s.name == hyps[ci].name)
                        .map(|s| s.dist)
                        .unwrap_or(f64::INFINITY)
                };
                let d = if kind == compat_matrix::score::OutInterp::Converted {
                    dist_to_correct(&raw).min(dist_to_correct(&tagged))
                } else {
                    dist_to_correct(&raw)
                };
                if d.is_finite() {
                    let w = worst.entry(bucket.to_string()).or_insert(0.0);
                    if d > *w {
                        *w = d;
                    }
                    use std::fmt::Write as _;
                    let _ = writeln!(detail, "{bucket}\t{}\t{}\t{d:.2}", r.id, cd.adapter);
                }
            }
        }
    }
    // Corpus bucket (r14 M-3): the bound is measured only on fixtures whose
    // `correct` reading carries no colour or orientation signal to
    // interpret — orient-1 sRGB/untagged reps (incl. `heic-colr-srgb` and
    // `heic-nocolr`) and the like. ICC/nclx-bearing HEICs leave the bucket:
    // their ImageIO-class cells are the very readings T would grade. The
    // distance is to `correct` on the cell's raw pixels — not the nearest
    // hypothesis, not the better of raw/tagged.
    use std::fmt::Write as _;
    for r in rows.iter().filter(|r| is_corpus(r)) {
        let heic =
            r.file.to_lowercase().ends_with(".heic") || r.file.to_lowercase().ends_with(".heif");
        let eligible = r.expect_orient == 1
            && matches!(
                r.colour,
                compat_matrix::manifest::Colour::Srgb | compat_matrix::manifest::Colour::Untagged
            )
            && (r.gainmap == "none" || r.gainmap.is_empty())
            && r.hyps.iter().any(|h| h.correct);
        let has_stored = r.hyps.iter().any(|h| h.name == "stored");
        if !eligible && !(heic && has_stored) {
            continue;
        }
        let hyps = load_hypins(&dir, r);
        let cds = hyps
            .iter()
            .position(|h| h.correct)
            .map(|i| compat_matrix::score::corpus_space(&hyps[i].img, MAX_SIDE));
        let sds = hyps
            .iter()
            .position(|h| h.name == "stored")
            .map(|i| compat_matrix::score::corpus_space(&hyps[i].img, MAX_SIDE));
        if eligible {
            let cds = cds.as_ref().expect("eligible implies a correct hyp");
            for cd in &dirs {
                let p = cd.path.join(format!("{}.png", r.id));
                let j = cd.path.join(format!("{}.json", r.id));
                let aj = std::fs::read_to_string(&j)
                    .ok()
                    .and_then(|s| serde_json::from_str::<AdapterJson>(&s).ok());
                if !aj.as_ref().map(|a| a.status == "ok").unwrap_or(false) {
                    continue;
                }
                extra_sha_gate(cd, aj.as_ref(), &r.sha256);
                if let Ok((raw, _tagged, kind)) = load_out_png(&p) {
                    if kind == compat_matrix::score::OutInterp::Hdr {
                        continue;
                    }
                    let rds = compat_matrix::score::corpus_space(&raw, MAX_SIDE);
                    let (d, _) = compat_matrix::score::corpus_dist(&rds, cds);
                    if d.is_finite() {
                        let _ = writeln!(detail, "corpus\t{}\t{}\t{d:.2}", r.id, cd.adapter);
                    }
                }
            }
        }
        // `.unm` rows (r13 M-2, r14 M-3): decodes of the drop-transform
        // remux (`probe --remux --drop-transform --unmanaged`, the same
        // file the `stored` base renders from) by the run's own HEIC
        // readers — ffmpeg's native HEVC path and zen/zen-raw — plus any
        // folded extra columns, each measured against the `stored`
        // (libde265) render. The remux carries no irot/imir/clap/colr, so
        // orientation-bearing and gain-map HEIC reps qualify on this path
        // and the distance is pure cross-decoder HEIC render noise. Cells
        // land as `<adapter>/<rep-id>.unm.png`.
        if heic && let Some(sds) = sds.as_ref() {
            for cd in &dirs {
                let p = cd.path.join(format!("{}.unm.png", r.id));
                if !p.is_file() {
                    continue;
                }
                let j = cd.path.join(format!("{}.unm.json", r.id));
                let aj = std::fs::read_to_string(&j)
                    .ok()
                    .and_then(|s| serde_json::from_str::<AdapterJson>(&s).ok());
                if !aj.as_ref().map(|a| a.status == "ok").unwrap_or(false) {
                    continue;
                }
                extra_sha_gate(cd, aj.as_ref(), &r.sha256);
                if let Ok((raw, _tagged, kind)) = load_out_png(&p) {
                    if kind == compat_matrix::score::OutInterp::Hdr {
                        continue;
                    }
                    let rds = compat_matrix::score::corpus_space(&raw, MAX_SIDE);
                    let (d, _) = compat_matrix::score::corpus_dist(&rds, sds);
                    if d.is_finite() {
                        let _ = writeln!(detail, "corpus\t{}.unm\t{}\t{d:.2}", r.id, cd.adapter);
                    }
                }
            }
        }
    }

    // r14: the `decoders` column names the *fold* — the columns the bucket
    // was allowed to measure — not the measured contributors. Sibling runs
    // share one canonical fixtures-dir artifact (`--check` byte-compares),
    // and contributor lists differ legitimately when a decoder exists in
    // one image only; the fold is identical by construction. Baseline
    // buckets fold the run plus its `CM_CALIBRATE_POOL` siblings; the
    // corpus bucket additionally folds the named extras. Per-cell sources
    // stay in calibration-detail.tsv.
    let mut base_fold: std::collections::BTreeSet<String> =
        pool_bases.iter().map(|b| format!("{b}/*")).collect();
    base_fold.insert(format!("{own_base}/*"));
    let mut corpus_fold = base_fold.clone();
    for extra in std::env::var("CM_CALIBRATE_EXTRA")
        .unwrap_or_default()
        .split(':')
        .filter(|s| !s.is_empty())
    {
        if let Some((dir, allow)) = extra.split_once('=') {
            let eb = Path::new(dir)
                .file_name()
                .map(|b| b.to_string_lossy().into_owned())
                .unwrap_or_else(|| "extra".to_string());
            for a in allow.split(',').filter(|s| !s.is_empty()) {
                corpus_fold.insert(format!("{eb}/{a}"));
            }
        }
    }
    let mut cal = String::from("bucket\tt\tdecoders\n");
    for b in ["lossy", "lossless", "corpus"] {
        let t = if b == "corpus" {
            let mut ds: Vec<f64> = detail
                .lines()
                .skip(1)
                .filter(|l| l.starts_with("corpus\t"))
                .filter_map(|l| l.rsplit('\t').next()?.parse::<f64>().ok())
                .collect();
            if ds.is_empty() {
                8.0
            } else {
                ds.sort_by(|a, b| a.total_cmp(b));
                (ds[((ds.len() - 1) as f64 * 0.99) as usize]).ceil() + 1.0
            }
        } else {
            worst
                .get(b)
                .copied()
                .map(|m| m.ceil() + 1.0)
                .unwrap_or(if b == "lossless" { 3.0 } else { 5.0 })
        };
        use std::fmt::Write as _;
        let fold = if b == "corpus" {
            &corpus_fold
        } else {
            &base_fold
        };
        let decs = fold.iter().cloned().collect::<Vec<_>>().join(",");
        let _ = writeln!(cal, "{b}\t{t:.0}\t{decs}");
    }
    // r13 §1b/M-2: the thresholds are an artifact of the hypothesis set,
    // written once beside hypotheses.tsv from the recorded decoder fold
    // (the run's cells plus the CM_CALIBRATE_EXTRA host columns), and every
    // matrix run on this fixture set reads the fixtures-dir copy. The
    // run-dir copy is the archive `--check` byte-compares.
    std::fs::write(dir.join("calibration.tsv"), &cal).expect("write fixtures calibration.tsv");
    std::fs::write(dir.join("calibration-detail.tsv"), &detail).expect("write fixtures detail");
    std::fs::write(out.join("calibration.tsv"), &cal).expect("write calibration.tsv");
    std::fs::write(out.join("calibration-detail.tsv"), detail).expect("write detail");
    eprintln!(
        "calibration: {}",
        worst
            .iter()
            .map(|(k, v)| format!("{k} worst={v:.2}"))
            .collect::<Vec<_>>()
            .join(" ")
    );
}
