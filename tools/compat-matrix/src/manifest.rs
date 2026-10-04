//! Manifest + hypothesis model shared by the generator and the scorer.
//!
//! `fixtures.tsv` identifies each file and what it claims. `hypotheses.tsv`
//! lists, per fixture, the candidate display outcomes the scorer will render
//! and score against — `synth:` entries are pure transforms of the pattern,
//! `corpus:` entries are computed from a reference decode of the file itself.

use std::fmt::Write as _;
use std::path::Path;

/// Declared/expected colour meaning of a fixture's pixels.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Colour {
    /// Nothing declares a colour space; readers should assume sRGB.
    Untagged,
    /// Explicitly declared sRGB (ICC, CICP, EXIF cs=1, sRGB chunk, or interop R98).
    Srgb,
    /// Display P3 by ICC or CICP 12/13/0 (9/16/0/1 would be BT.2020 PQ).
    P3,
    /// Adobe RGB by ICC or EXIF interop R03.
    AdobeRgb,
    /// EXIF ColorSpace=0xFFFF with no interop hint — ambiguous trap.
    Uncalibrated,
}

impl Colour {
    pub fn name(self) -> &'static str {
        match self {
            Colour::Untagged => "untagged",
            Colour::Srgb => "srgb",
            Colour::P3 => "p3",
            Colour::AdobeRgb => "adobe",
            Colour::Uncalibrated => "uncalibrated",
        }
    }
}

/// One hypothesis: a candidate display outcome for a fixture.
#[derive(Clone, Debug)]
pub struct Hyp {
    /// Stable name used in matrix.tsv columns.
    pub name: String,
    /// What the scorer renders for this hypothesis.
    pub spec: String,
    /// Whether this outcome is the semantically-correct one.
    pub correct: bool,
}

/// A fixture manifest row.
#[derive(Clone, Debug)]
pub struct FixtureRow {
    pub id: String,
    pub class: String,
    pub file: String,
    pub w: u32,
    pub h: u32,
    /// EXIF-equivalent display orientation of the *correct* output (1–8).
    pub expect_orient: u8,
    pub colour: Colour,
    pub gainmap: String,
    /// Free-text signalling description for the report.
    pub signal_desc: String,
    pub sha256: String,
    /// sha256 of the corpus donor this fixture was remuxed from (HEIC
    /// family only — pinned in generate::HEIC_DONOR_SHA256). Empty for
    /// synthetic fixtures.
    pub donor_sha: String,
    pub hyps: Vec<Hyp>,
    /// Signalling expectations re-verified against the emitted bytes at
    /// generate time (`verify::verify_dir`). Token language in verify.rs.
    pub expect: Vec<String>,
}

impl FixtureRow {
    /// Attach the machine-checkable signalling expectations for this row.
    pub fn with_expect(mut self, tokens: &[&'static str]) -> Self {
        self.expect = tokens.iter().map(|t| t.to_string()).collect();
        self
    }
}

pub fn write_fixtures_tsv(rows: &[FixtureRow], path: &Path) -> std::io::Result<()> {
    let mut s = String::from(
        "fixture\tclass\tfile\tw\th\texpect_orient\tcolour\tgainmap\tsha256\tsignal_desc\tdonor_sha\n",
    );
    for r in rows {
        let _ = writeln!(
            s,
            "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
            r.id,
            r.class,
            r.file,
            r.w,
            r.h,
            r.expect_orient,
            r.colour.name(),
            r.gainmap,
            r.sha256,
            r.signal_desc,
            r.donor_sha
        );
    }
    std::fs::write(path, s)
}

pub fn write_hypotheses_tsv(rows: &[FixtureRow], path: &Path) -> std::io::Result<()> {
    let mut s = String::from("fixture\thypothesis\tspec\tcorrect\n");
    for r in rows {
        for h in &r.hyps {
            let _ = writeln!(
                s,
                "{}\t{}\t{}\t{}",
                r.id,
                h.name,
                h.spec,
                u8::from(h.correct)
            );
        }
    }
    std::fs::write(path, s)
}

/// Orientation hypotheses for a *synthetic* fixture whose stored pixels are
/// the canonical pattern with display orientation tag `o`: candidates are the
/// pattern under every possible display orientation (correct = `o`, the rest
/// are what a reader produces by misreading or ignoring the tag).
///
/// `indistinguishable` marks pairs that collapse (orient1 == no-tag etc.) —
/// the scorer's self-test gate also checks these numerically.
pub fn synth_orient_hyps(correct: u8) -> Vec<Hyp> {
    (1..=8u8)
        .map(|o| Hyp {
            name: format!("orient{o}"),
            spec: format!("synth:orient={o}"),
            correct: o == correct,
        })
        .collect()
}

/// Colour hypotheses for a synthetic fixture: the pattern code values
/// displayed under each candidate colour interpretation.
pub fn synth_colour_hyps(correct: Colour, extra_orient: Option<u8>) -> Vec<Hyp> {
    let orient = extra_orient.unwrap_or(1);
    let mut out = Vec::new();
    for c in [Colour::Srgb, Colour::P3, Colour::AdobeRgb] {
        out.push(Hyp {
            name: format!("{}-as-{}", correct.name(), c.name()),
            spec: format!("synth:orient={orient};color={}", c.name()),
            correct: c == effective(correct),
        });
    }
    out
}

/// The colour a reader *should* converge to for a fixture.
fn effective(c: Colour) -> Colour {
    match c {
        // Untagged and uncalibrated-no-interop both mean "no declared colour";
        // the sRGB hypothesis is the semantically expected render.
        Colour::Untagged | Colour::Srgb | Colour::Uncalibrated => Colour::Srgb,
        c => c,
    }
}

/// Load fixtures.tsv + hypotheses.tsv back into rows (hyps merged by id).
pub fn load_fixtures(fixtures_dir: &Path) -> std::io::Result<Vec<FixtureRow>> {
    let fx = std::fs::read_to_string(fixtures_dir.join("fixtures.tsv"))?;
    let mut rows: Vec<FixtureRow> = Vec::new();
    for line in fx.lines().skip(1) {
        let f: Vec<&str> = line.split('\t').collect();
        if f.len() < 10 {
            continue;
        }
        rows.push(FixtureRow {
            id: f[0].into(),
            class: f[1].into(),
            file: f[2].into(),
            w: f[3]
                .parse()
                .unwrap_or_else(|_| panic!("fixtures.tsv: bad w {:?} for {}", f[3], f[0])),
            h: f[4]
                .parse()
                .unwrap_or_else(|_| panic!("fixtures.tsv: bad h {:?} for {}", f[4], f[0])),
            expect_orient: f[5].parse().unwrap_or_else(|_| {
                panic!("fixtures.tsv: bad expect_orient {:?} for {}", f[5], f[0])
            }),
            colour: match f[6] {
                "srgb" => Colour::Srgb,
                "p3" => Colour::P3,
                "adobe" => Colour::AdobeRgb,
                "uncalibrated" => Colour::Uncalibrated,
                _ => Colour::Untagged,
            },
            gainmap: f[7].into(),
            sha256: f[8].into(),
            signal_desc: f[9].into(),
            // Optional 11th column — manifests written before the donor pin
            // lack it; absence means "no recorded donor", not "synthetic".
            donor_sha: f.get(10).unwrap_or(&"").to_string(),
            expect: Vec::new(),
            hyps: Vec::new(),
        });
    }
    let hyp = std::fs::read_to_string(fixtures_dir.join("hypotheses.tsv"))?;
    for line in hyp.lines().skip(1) {
        let f: Vec<&str> = line.split('\t').collect();
        if f.len() < 4 {
            continue;
        }
        if let Some(r) = rows.iter_mut().find(|r| r.id == f[0]) {
            r.hyps.push(Hyp {
                name: f[1].into(),
                spec: f[2].into(),
                correct: f[3] == "1",
            });
        }
    }
    Ok(rows)
}
