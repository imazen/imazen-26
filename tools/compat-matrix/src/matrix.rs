//! Matrix aggregation: derive matrix.tsv / versions.tsv / separations.tsv
//! from a run dir's cell JSONs + PNGs, and the `--check` verifier that
//! re-derives them byte-for-byte. Split out of classify.rs (L-4).

use std::collections::{HashMap, HashSet};
use std::fmt::Write as _;
use std::path::{Path, PathBuf};

use crate::classify::{AdapterJson, MAX_SIDE, load_calibration, load_hypins, t_for};

/// Browser-adapter column names run under the browsers image; everything
/// else under the run's `$IMAGE`. Mirrors run_matrix.sh `is_browser`.
fn is_browser_adapter(a: &str) -> bool {
    a.starts_with("chromium")
        || a.starts_with("firefox")
        || a.starts_with("webkit")
        || a.ends_with("-canvas")
}

/// What the run's LAST platform.txt block records. Each run_matrix
/// invocation appends a block; cells must match the most recent block's
/// records, so a stale mid-file block (e.g. a contaminating pass under
/// the wrong image) cannot launder a cross-image cell.
#[derive(Default)]
struct PlatformRecord {
    /// `image=<name> id=sha256:..` — the docker-image producer id for
    /// non-browser adapters.
    image_id: Option<String>,
    /// `browsers_image=<name> id=sha256:..` — for browser adapters.
    browsers_id: Option<String>,
    /// `adapter=<name> sha256=<sha>` — per-adapter script hashes.
    adapter_sha: HashMap<String, String>,
    /// `container_adapter=<name>` — adapters that ran inside the run's
    /// docker/browser images. `image_id=host` is refused for these (r12
    /// L-2): a host cell is admissible only for adapters with no image
    /// class. Runs without such lines (host-only coordinator sweeps)
    /// have an empty set and admit all platform-listed host cells.
    container_adapters: HashSet<String>,
    /// `host_adapter=<name>` — the positive form (r13 L-2): when the
    /// block carries any host markers, `image_id=host` is admissible
    /// ONLY for listed adapters — an unlisted host cell is refused
    /// instead of passing by silence.
    host_adapters: HashSet<String>,
    /// Any `id=sha256:` tokens in the block — non-empty means a platform
    /// record exists at all (manual sweeps have none; gates relax).
    any_ids: HashSet<String>,
}

fn platform_record(out: &Path) -> PlatformRecord {
    let mut rec = PlatformRecord::default();
    let Ok(txt) = std::fs::read_to_string(out.join("platform.txt")) else {
        return rec;
    };
    // platform.txt is an append log: each `# <timestamp>` block records the
    // adapters that invocation actually swept, and partial re-sweeps append
    // blocks that only name their own adapters. Merge every block so each
    // adapter's LAST `adapter=<name>` line wins; host/container membership
    // and the image ids likewise reflect the most recent record for the
    // adapters they cover.
    for line in txt.lines() {
        let mut id = None;
        for f in line.split_whitespace() {
            if let Some(v) = f.strip_prefix("id=") {
                id = Some(v.to_string());
                rec.any_ids.insert(v.to_string());
            }
        }
        if line.starts_with("image=") {
            rec.image_id = id;
        } else if line.starts_with("browsers_image=") {
            rec.browsers_id = id;
        } else if let Some(rest) = line.strip_prefix("container_adapter=") {
            rec.container_adapters
                .insert(rest.split_whitespace().next().unwrap_or("").to_string());
        } else if let Some(rest) = line.strip_prefix("host_adapter=") {
            rec.host_adapters
                .insert(rest.split_whitespace().next().unwrap_or("").to_string());
        } else if let Some(rest) = line.strip_prefix("adapter=")
            && let Some((name, kv)) = rest.split_once(' ')
            && let Some(sha) = kv.strip_prefix("sha256=")
        {
            rec.adapter_sha.insert(name.to_string(), sha.to_string());
        }
    }
    rec
}

/// Build matrix.tsv + versions.tsv + separations.tsv + summary.tsv from a run dir.
/// Split out of `cmd_matrix` so `--check` can regenerate and byte-compare.
fn build_tables(dir: &Path, out: &Path) -> (String, String, String, String) {
    let rows = compat_matrix::manifest::load_fixtures(dir).expect("load fixtures");
    let cal = {
        // r13 §1b: calibration is an artifact of the hypothesis set —
        // `<fixtures>/calibration.tsv` is authoritative; the run-dir copy
        // is the archive `--check` byte-compares (mismatch = failure).
        let shared = load_calibration(dir);
        if shared.is_empty() {
            load_calibration(out)
        } else {
            shared
        }
    };
    let mut collapse_cache: HashMap<String, Vec<(String, String, f64, f64)>> = HashMap::new();
    // path().is_dir() follows symlinks (L-10): a run dir of symlinked
    // adapter dirs must aggregate, not silently produce an empty matrix.
    let mut adapters: Vec<String> = std::fs::read_dir(out)
        .expect("read out dir")
        .filter_map(|e| {
            let e = e.ok()?;
            let name = e.file_name().to_string_lossy().into_owned();
            (e.path().is_dir()
                && name != "hyps"
                && name != "census"
                && name != "probe"
                && rows
                    .iter()
                    .any(|r| e.path().join(format!("{}.json", r.id)).is_file()))
            .then_some(name)
        })
        .collect();
    adapters.sort();

    // r13 H-1: every cell is scored twice. The raw columns score the
    // reader-returned pixels as-is — what an application that ignores the
    // attached profile gets; the tagged columns score the same pixels
    // interpreted through the output PNG's own colour declaration — what a
    // colour-managed viewer gets. `out_profile` records that declaration;
    // `orientation_ok` grades the orientation axis alone on
    // orientation-bearing fixtures (r13 §2: a colour-matrix verdict must
    // not swallow orientation evidence).
    let mut matrix = String::from(
        "adapter\tfixture\tclass\tstatus\tverdict\tcorrect\td1\td2\tmx1\tmx2\tw\th\tms\terror\tnote\tout_profile\tverdict_tagged\tcorrect_tagged\td1_tagged\td2_tagged\torientation_ok\n",
    );
    let mut versions = String::from("adapter\tversion\n");
    let mut seen_versions: HashSet<String> = HashSet::new();
    // L-3: per-run status histogram — ok/error/crash/flaky/n/a per adapter,
    // emitted as summary.tsv so every count the doc quotes comes from a
    // file. `flaky` is a verdict label over status=error; bucket on it.
    let mut summary: std::collections::BTreeMap<String, std::collections::BTreeMap<String, u32>> =
        Default::default();
    let mut hyp_cache: HashMap<String, Vec<compat_matrix::score::HypIn>> = HashMap::new();
    let rec = platform_record(out);
    // output_sha bookkeeping (M-6): a reps run either stamps every
    // produced cell or none — mixed provenance is a gate failure.
    let mut output_sha_seen = false;
    let mut output_sha_missing: Vec<String> = Vec::new();

    for a in &adapters {
        let adir = out.join(a);
        for r in &rows {
            let jpath = adir.join(format!("{}.json", r.id));
            let (aj, crashed) = match std::fs::read_to_string(&jpath)
                .ok()
                .and_then(|s| serde_json::from_str::<AdapterJson>(&s).ok())
            {
                Some(j) => (j, false),
                None => (
                    AdapterJson {
                        status: "crash".into(),
                        error_head: "adapter produced no json".into(),
                        ..Default::default()
                    },
                    true,
                ),
            };
            if crashed {
                // r14 L-2: name the missing cell — `crash` is a legitimate
                // recorded outcome but an absent json must never be
                // silent (a deleted cell otherwise only surfaces as an
                // opaque table-diff failure under --check).
                eprintln!("matrix: missing expected cell {a}/{}", r.id);
            }
            // provenance gate: a cell must name the fixture sha the
            // manifest records — empty or mismatched means the cell
            // predates the manifest (M-3: empty values are refused).
            if !crashed && aj.fixture_sha != r.sha256 {
                eprintln!(
                    "{} {}: cell fixture_sha {:?} != manifest {} — stale or unprovenanced cell",
                    a, r.id, aj.fixture_sha, r.sha256
                );
                std::process::exit(2);
            }
            // producer gate (M-3): docker cells must carry the image id
            // platform.txt paired with their adapter class — browser
            // adapters the browsers image, the rest the run image — and
            // the adapter sha the block recorded. "host" marks
            // natively-produced cells (zen columns), exempt from the
            // image check but still required to be non-empty.
            if !crashed {
                if aj.image_id.is_empty() {
                    eprintln!("{} {}: cell has empty image_id", a, r.id);
                    std::process::exit(2);
                }
                if aj.adapter_sha.is_empty() {
                    eprintln!("{} {}: cell has empty adapter_sha", a, r.id);
                    std::process::exit(2);
                }
                if aj.image_id == "host" {
                    // r13 L-2 positive rule: a host cell is admissible only
                    // for an adapter the platform block positively names
                    // via `host_adapter=` — an unlisted name is refused,
                    // never silently admitted; never for a
                    // `container_adapter=` name. The `adapter=<name>
                    // sha256=<sha>` record then pins the producing binary.
                    if rec.container_adapters.contains(a.as_str()) {
                        eprintln!("{} {}: image_id=host on a container adapter", a, r.id);
                        std::process::exit(2);
                    }
                    if !rec.host_adapters.contains(a.as_str()) {
                        eprintln!(
                            "{} {}: image_id=host on an adapter not listed as host_adapter=",
                            a, r.id
                        );
                        std::process::exit(2);
                    }
                    if !rec.any_ids.is_empty() && !rec.adapter_sha.contains_key(a.as_str()) {
                        eprintln!(
                            "{} {}: image_id=host but adapter has no platform.txt record",
                            a, r.id
                        );
                        std::process::exit(2);
                    }
                } else {
                    let expected = if is_browser_adapter(a) {
                        rec.browsers_id.as_deref()
                    } else {
                        rec.image_id.as_deref()
                    };
                    match (expected, rec.any_ids.is_empty()) {
                        (Some(id), _) if aj.image_id != id => {
                            eprintln!(
                                "{} {}: cell image_id {} != run's {} — cross-image cell",
                                a, r.id, aj.image_id, id
                            );
                            std::process::exit(2);
                        }
                        (None, false) => {
                            eprintln!(
                                "{} {}: platform record has no image id for adapter class",
                                a, r.id
                            );
                            std::process::exit(2);
                        }
                        _ => {}
                    }
                }
                if let Some(want) = rec.adapter_sha.get(a.as_str())
                    && aj.adapter_sha != *want
                {
                    eprintln!(
                        "{} {}: cell adapter_sha {} != platform's {}",
                        a, r.id, aj.adapter_sha, want
                    );
                    std::process::exit(2);
                }
            }
            let vkey = format!("{a}\t{}", aj.version.trim());
            if !aj.version.is_empty() && seen_versions.insert(vkey) {
                let _ = writeln!(versions, "{a}\t{}", aj.version.trim().replace('\t', " "));
            }
            let has_alpha_hyps = r.hyps.iter().any(|h| h.spec.contains("alpha="));
            /// One scored row: raw columns stay the primary record;
            /// `*_tagged` carry the colour-managed reading.
            struct Cell {
                verdict: String,
                correct: bool,
                d1: f64,
                d2: f64,
                mx1: f64,
                mx2: f64,
                note: String,
                outp: String,
                verdict_t: String,
                correct_t: &'static str,
                d1_t: f64,
                d2_t: f64,
                orient_ok: &'static str,
            }
            let nonscored = |verdict: &str| Cell {
                verdict: verdict.to_string(),
                correct: false,
                d1: f64::INFINITY,
                d2: f64::INFINITY,
                mx1: f64::INFINITY,
                mx2: f64::INFINITY,
                note: String::new(),
                outp: String::new(),
                verdict_t: verdict.to_string(),
                correct_t: "false",
                d1_t: f64::INFINITY,
                d2_t: f64::INFINITY,
                orient_ok: "",
            };
            // `n/a` is reserved for "the adapter declares it cannot produce a
            // comparable reading": the driver wrote status=n/a for a format
            // the adapter does not support, or the adapter declared its
            // output alpha-unmeasurable. Every other non-ok status (error,
            // timeout, crash) is a counted failure and keeps its name.
            let cell = if crashed {
                nonscored("crash")
            } else if aj.status == "n/a" || (has_alpha_hyps && aj.alpha_measurable == Some(false)) {
                nonscored("n/a")
            } else if aj.status != "ok" {
                // r12 L-4: a canvas readback that returned all-zero pixels
                // is nondeterministic infrastructure noise (observed on
                // webkit-canvas under parallel load), not a decoder
                // verdict — flag it `flaky` so it stays out of error
                // counts and any lts-vs-latest comparison.
                let v = if aj.error_head.contains("all-zero pixels") {
                    "flaky".to_string()
                } else {
                    aj.status.clone()
                };
                nonscored(&v)
            } else {
                let ppath = adir.join(format!("{}.png", r.id));
                // M-6 render provenance: `output_sha` names the
                // full-resolution render the cell was classified from;
                // `thumb_sha` (M-2) names the PNG that remains on disk
                // after thumbnailing. The on-disk bytes must hash to one
                // or the other — output_sha when the render is still
                // full-res, thumb_sha once the thumb replaced it. A thumb
                // that matches neither is an unverifiable render.
                if let Some(os) = aj.output_sha.as_deref().filter(|s| !s.is_empty()) {
                    output_sha_seen = true;
                    if let Ok(bytes) = std::fs::read(&ppath) {
                        let disk = compat_matrix::generate::sha256_hex_pub(&bytes);
                        let ts = aj.thumb_sha.as_deref().unwrap_or("");
                        if disk != os && disk != ts {
                            eprintln!(
                                "{} {}: PNG sha matches neither output_sha nor thumb_sha — swapped render",
                                a, r.id
                            );
                            std::process::exit(2);
                        }
                    }
                } else {
                    output_sha_missing.push(format!("{a}/{}", r.id));
                }
                // r13 H-1: decode from the same bytes the sha gate checks,
                // keep the raw pixels as primary, and score a second,
                // tagged reading under the output's own colour declaration
                // (cICP > iCCP > sRGB > gAMA+cHRM precedence).
                let outpng = std::fs::read(&ppath).ok().and_then(|b| {
                    compat_matrix::score::decode_png(&b)
                        .ok()
                        .map(|img| (img, b))
                });
                let hyps = hyp_cache
                    .entry(r.id.clone())
                    .or_insert_with(|| load_hypins(dir, r));
                match outpng {
                    Some((img, bytes)) => {
                        let t = t_for(r, &cal);
                        // H-2: collapse is decided at the fine decode-noise
                        // bound — the wide corpus T only picks the nearest
                        // hypothesis and must not merge separable readings.
                        let collapsed = collapse_cache.entry(r.id.clone()).or_insert_with(|| {
                            compat_matrix::score::self_test_patched(
                                hyps,
                                compat_matrix::score::FINE_T,
                                1.0,
                                compat_matrix::score::FINE_T,
                                MAX_SIDE,
                            )
                        });
                        let (v, scored, note) = compat_matrix::score::classify_patched(
                            &img, hyps, t, MAX_SIDE, collapsed,
                        );
                        // `correct` follows the verdict, not mere proximity:
                        // a named verdict certifies only when the named hyp
                        // is correct-labelled — a correct hyp sitting inside
                        // the wide corpus T does not rescue a reading the
                        // fixture separates at the fine bound (H-2); a
                        // margin-failed `not-measurable` names nothing
                        // (H-3); a collapse clique including correct still
                        // certifies — indistinguishable by construction.
                        let correct = compat_matrix::score::verdict_correct(&v, &note, &scored);
                        let tagged = compat_matrix::score::classify_tagged(
                            &img,
                            &bytes,
                            &compat_matrix::score::RawScoring {
                                scored: &scored,
                                verdict: &v,
                                correct,
                                src_colour: r.colour,
                            },
                            hyps,
                            t,
                            MAX_SIDE,
                            collapsed,
                        );
                        // orientation_ok (r13 §2): on fixtures whose hyp set
                        // carries more than one orientation state, name
                        // whether the nearest hypothesis applies the
                        // signalled orientation — a colour-matrix reading
                        // (e.g. `orient8+mc-709-decode`) must not hide that
                        // the orientation axis was honoured. r14 L-7: empty
                        // when nothing is within T — a cell matching no
                        // hypothesis has no nearest reading to describe.
                        let orient_ok = if crate::classify::is_orientation_fixture(r)
                            && !scored.is_empty()
                            && scored[0].dist <= t
                        {
                            let ho = crate::classify::hyp_orient(
                                r.hyps
                                    .iter()
                                    .find(|h| h.name == scored[0].name)
                                    .map(|h| h.spec.as_str())
                                    .unwrap_or(""),
                                r.expect_orient,
                            );
                            if ho == r.expect_orient {
                                "true"
                            } else {
                                "false"
                            }
                        } else {
                            ""
                        };
                        let (d1, mx1) = scored
                            .first()
                            .map(|s| (s.dist, s.dmax))
                            .unwrap_or((f64::INFINITY, f64::INFINITY));
                        let (d2, mx2) = scored
                            .get(1)
                            .map(|s| (s.dist, s.dmax))
                            .unwrap_or((f64::INFINITY, f64::INFINITY));
                        Cell {
                            verdict: v,
                            correct,
                            d1,
                            d2,
                            mx1,
                            mx2,
                            note,
                            outp: tagged.profile.clone(),
                            verdict_t: tagged.verdict,
                            correct_t: tagged.correct,
                            d1_t: tagged.d1,
                            d2_t: tagged.d2,
                            orient_ok,
                        }
                    }
                    None => nonscored("other"),
                }
            };
            let _ = writeln!(
                matrix,
                "{a}\t{}\t{}\t{}\t{}\t{}\t{:.2}\t{:.2}\t{:.2}\t{:.2}\t{}\t{}\t{:.1}\t{}\t{}\t{}\t{}\t{}\t{:.2}\t{:.2}\t{}",
                r.id,
                r.class,
                aj.status,
                cell.verdict,
                cell.correct,
                cell.d1,
                cell.d2,
                cell.mx1,
                cell.mx2,
                aj.w,
                aj.h,
                aj.ms,
                aj.error_head.replace(['\t', '\n'], " "),
                cell.note.replace(['\t', '\n'], " "),
                cell.outp.replace(['\t', '\n'], " "),
                cell.verdict_t.replace(['\t', '\n'], " "),
                cell.correct_t,
                cell.d1_t,
                cell.d2_t,
                cell.orient_ok
            );
            let bucket = if cell.verdict == "flaky" {
                "flaky"
            } else {
                aj.status.as_str()
            };
            *summary
                .entry(a.clone())
                .or_default()
                .entry(bucket.to_string())
                .or_default() += 1;
        }
    }
    // output_sha uniformity: a run that stamps any cell must stamp every
    // produced cell — mixed render provenance is a gate failure.
    if output_sha_seen && !output_sha_missing.is_empty() {
        eprintln!(
            "matrix: {} ok cells lack output_sha while others carry it (first: {})",
            output_sha_missing.len(),
            output_sha_missing[0]
        );
        std::process::exit(2);
    }
    // Hypothesis-pair separations — the evidence behind indistinguishable /
    // not-measurable verdicts. `dist` is p99 on corpus fixtures, patch-max
    // on pattern ones; `max` is the corpus per-pixel max.
    let mut sep = String::from("fixture\thyp_a\thyp_b\tdist\tmax\n");
    for r in &rows {
        let pairs = collapse_cache.entry(r.id.clone()).or_insert_with(|| {
            let hyps = hyp_cache
                .entry(r.id.clone())
                .or_insert_with(|| load_hypins(dir, r));
            // collapse is decided at the fine bound — this list IS the
            // collapse evidence (H-2), not a same-T proximity report.
            compat_matrix::score::self_test_patched(
                hyps,
                compat_matrix::score::FINE_T,
                1.0,
                compat_matrix::score::FINE_T,
                MAX_SIDE,
            )
        });
        for (a, b, d, mx) in pairs.iter() {
            let _ = writeln!(sep, "{}\t{a}\t{b}\t{d:.2}\t{mx:.2}", r.id);
        }
    }
    let mut sm = String::from("adapter\tstatus\tcells\n");
    for (a, buckets) in &summary {
        for (b, n) in buckets {
            let _ = writeln!(sm, "{a}\t{b}\t{n}");
        }
    }
    (matrix, versions, sep, sm)
}

pub(crate) fn cmd_matrix(args: Vec<String>) {
    let mut check = false;
    let mut pos: Vec<String> = Vec::new();
    for a in args {
        match a.as_str() {
            "--check" => check = true,
            s => pos.push(s.to_string()),
        }
    }
    let mut it = pos.into_iter();
    let (dir, out) = match (it.next(), it.next()) {
        (Some(d), Some(o)) => (PathBuf::from(d), PathBuf::from(o)),
        _ => crate::usage(),
    };
    let (matrix, versions, sep, summary_tsv) = build_tables(&dir, &out);
    if check {
        // --check: the run's archived tables must be byte-identical to what
        // the current cells + calibration produce — catches aggregation run
        // before the final cell landed, or stale calibration.
        let mut bad = false;
        for (name, want) in [
            ("matrix.tsv", &matrix),
            ("versions.tsv", &versions),
            ("separations.tsv", &sep),
            ("summary.tsv", &summary_tsv),
        ] {
            let got = std::fs::read_to_string(out.join(name)).unwrap_or_default();
            if got != *want {
                eprintln!("matrix --check: {name} disagrees with the cell JSONs");
                bad = true;
            }
        }
        // r13 §1b: the fixtures-dir calibration.tsv is authoritative; the
        // run archive must byte-match it — a mismatch means the run was
        // scored against different thresholds than the hypothesis set.
        let arch = std::fs::read_to_string(out.join("calibration.tsv")).unwrap_or_default();
        let shared = std::fs::read_to_string(dir.join("calibration.tsv")).unwrap_or_default();
        if shared != arch {
            eprintln!("matrix --check: fixtures-dir calibration.tsv differs from the run archive");
            bad = true;
        }
        // r13 L-4a: census sidecars are outside the table regeneration, so
        // verify their stamps here — every `thumb_sha`/`output_sha` must
        // match the sibling PNG on disk, and an `ok` census cell with no
        // PNG is a missing cell (r12 shipped one).
        let census = out.join("census");
        if census.is_dir() {
            for rd in std::fs::read_dir(&census)
                .expect("read census dir")
                .flatten()
            {
                if !rd.path().is_dir() {
                    continue;
                }
                for e in std::fs::read_dir(rd.path())
                    .expect("read census reader")
                    .flatten()
                {
                    let p = e.path();
                    if p.extension().and_then(|s| s.to_str()) != Some("json") {
                        continue;
                    }
                    let Ok(txt) = std::fs::read_to_string(&p) else {
                        continue;
                    };
                    let Ok(cj) = serde_json::from_str::<serde_json::Value>(&txt) else {
                        continue;
                    };
                    let png = p.with_extension(""); // <file>.jpg.json -> <file>.jpg
                    let png = png.with_extension(format!(
                        "{}.png",
                        png.extension().and_then(|s| s.to_str()).unwrap_or("")
                    ));
                    let png_ok = png.is_file();
                    // census.sh retains renders for zen-reader only — every
                    // other reader's PNG is deleted after its stats land, so
                    // the missing-cell rule applies where a render is
                    // *expected* to exist (r14 L-2).
                    let retains_renders = rd.file_name() == "zen-reader";
                    if retains_renders
                        && cj.get("status").and_then(|s| s.as_str()) == Some("ok")
                        && !png_ok
                    {
                        eprintln!(
                            "matrix --check: missing expected cell {}/{}",
                            rd.file_name().to_string_lossy(),
                            p.file_name().unwrap().to_string_lossy()
                        );
                        bad = true;
                    }
                    for k in ["thumb_sha", "output_sha"] {
                        if let Some(want) = cj.get(k).and_then(|s| s.as_str()) {
                            if !png_ok {
                                eprintln!(
                                    "matrix --check: census {} carries {k} but no PNG",
                                    p.display()
                                );
                                bad = true;
                            } else {
                                let got = std::fs::read(&png)
                                    .map(|b| compat_matrix::generate::sha256_hex_pub(&b))
                                    .unwrap_or_default();
                                if got != want {
                                    eprintln!(
                                        "matrix --check: census {} {k} stale ({want} != {got})",
                                        p.display()
                                    );
                                    bad = true;
                                }
                            }
                        }
                    }
                }
            }
        }
        // r13 L-4b / M-1: probe sidecars — adapter must name a platform record,
        // image/adapter sha must match the block, gate=fail refuses the run.
        let probe_dir = out.join("probe");
        if probe_dir.is_dir() {
            let rec = platform_record(&out);
            for e in std::fs::read_dir(&probe_dir)
                .expect("read probe dir")
                .flatten()
            {
                let p = e.path();
                if p.extension().and_then(|s| s.to_str()) != Some("json") {
                    continue;
                }
                let name = p.file_stem().unwrap().to_string_lossy().into_owned();
                let Ok(pj) = serde_json::from_str::<serde_json::Value>(
                    &std::fs::read_to_string(&p).unwrap_or_default(),
                ) else {
                    eprintln!("matrix --check: probe {} is not JSON", p.display());
                    bad = true;
                    continue;
                };
                if pj.get("gate").and_then(|s| s.as_str()) == Some("fail") {
                    eprintln!("matrix --check: probe {name} records gate=fail");
                    bad = true;
                }
                if let Some(sha) = pj.get("adapter_sha").and_then(|s| s.as_str()) {
                    match rec.adapter_sha.get(name.as_str()) {
                        Some(want) if want == sha => {}
                        _ => {
                            eprintln!(
                                "matrix --check: probe {name} adapter_sha does not match platform.txt"
                            );
                            bad = true;
                        }
                    }
                }
                if let Some(img) = pj.get("image_id").and_then(|s| s.as_str()) {
                    let expected = if is_browser_adapter(&name) {
                        rec.browsers_id.as_deref()
                    } else {
                        rec.image_id.as_deref()
                    };
                    if rec.any_ids.is_empty() || Some(img) != expected {
                        eprintln!("matrix --check: probe {name} image_id stale vs platform.txt");
                        bad = true;
                    }
                }
            }
        }
        if bad {
            std::process::exit(1);
        }
        eprintln!(
            "matrix --check: matrix/versions/separations/summary + calibration + census/probe stamps consistent"
        );
        return;
    }
    std::fs::write(out.join("separations.tsv"), sep).expect("write separations.tsv");
    std::fs::write(out.join("matrix.tsv"), &matrix).expect("write matrix.tsv");
    std::fs::write(out.join("summary.tsv"), summary_tsv).expect("write summary.tsv");
    std::fs::write(out.join("versions.tsv"), versions).expect("write versions.tsv");
    // calibration.tsv is already per-run (calibrate wrote it here); matrix
    // does not re-copy it so `matrix --check` reflects the scoring input.
    eprintln!("wrote matrix.tsv + versions.tsv for run {}", out.display());
    let _ = matrix;
}
