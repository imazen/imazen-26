//! The deterministic test pattern.
//!
//! 384x256 (3:2, so a 90-degree error shows in the dimensions) and a 381x253
//! non-MCU-aligned variant. Layout: four distinct corner markers, an
//! asymmetric center glyph, a strip of colour patches chosen to move by many
//! dE when the declared colour space is ignored, and a 16-step neutral ramp.
//! Everything is generated as u16 code values; the declared space (sRGB,
//! Display P3, Adobe RGB) only changes what the values *mean*.

use crate::Rgb16;

/// A named colour patch: rect in pattern coordinates plus the u16 code value.
#[derive(Clone, Debug)]
pub struct Patch {
    pub name: &'static str,
    pub x: u32,
    pub y: u32,
    pub w: u32,
    pub h: u32,
    /// code value (u16) in the declared space
    pub code: [u16; 3],
}

pub struct Pattern {
    pub img: Rgb16,
    pub patches: Vec<Patch>,
}

const U16MAX: u16 = 65535;

fn u16c(v: f32) -> u16 {
    (v.clamp(0.0, 1.0) * U16MAX as f32 + 0.5) as u16
}

fn rect(img: &mut Rgb16, x0: i64, y0: i64, x1: i64, y1: i64, c: [u16; 3]) {
    let (w, h) = (img.w as i64, img.h as i64);
    for y in y0.max(0)..y1.min(h) {
        for x in x0.max(0)..x1.min(w) {
            img.set(x as u32, y as u32, c);
        }
    }
}

fn circle(img: &mut Rgb16, cx: f64, cy: f64, r: f64, c: [u16; 3]) {
    let r2 = r * r;
    let (x0, x1) = ((cx - r - 1.0) as i64, (cx + r + 1.0) as i64);
    let (y0, y1) = ((cy - r - 1.0) as i64, (cy + r + 1.0) as i64);
    for y in y0..y1 {
        for x in x0..x1 {
            if x < 0 || y < 0 || x >= img.w as i64 || y >= img.h as i64 {
                continue;
            }
            let dx = x as f64 + 0.5 - cx;
            let dy = y as f64 + 0.5 - cy;
            if dx * dx + dy * dy <= r2 {
                img.set(x as u32, y as u32, c);
            }
        }
    }
}

fn tri(img: &mut Rgb16, [ax, ay, bx, by, cx, cy]: [f64; 6], c: [u16; 3]) {
    let minx = (ax.min(bx).min(cx)) as i64 - 1;
    let maxx = (ax.max(bx).max(cx)) as i64 + 1;
    let miny = (ay.min(by).min(cy)) as i64 - 1;
    let maxy = (ay.max(by).max(cy)) as i64 + 1;
    let d = |px: f64, py: f64, x1: f64, y1: f64, x2: f64, y2: f64| {
        (px - x2) * (y1 - y2) - (x1 - x2) * (py - y2)
    };
    for y in miny..maxy {
        for x in minx..maxx {
            if x < 0 || y < 0 || x >= img.w as i64 || y >= img.h as i64 {
                continue;
            }
            let (px, py) = (x as f64 + 0.5, y as f64 + 0.5);
            let d1 = d(px, py, ax, ay, bx, by);
            let d2 = d(px, py, bx, by, cx, cy);
            let d3 = d(px, py, cx, cy, ax, ay);
            let neg = (d1 < 0.0) || (d2 < 0.0) || (d3 < 0.0);
            let pos = (d1 > 0.0) || (d2 > 0.0) || (d3 > 0.0);
            if !(neg && pos) {
                img.set(x as u32, y as u32, c);
            }
        }
    }
}

fn diamond(img: &mut Rgb16, cx: f64, cy: f64, r: f64, c: [u16; 3]) {
    for y in 0..img.h as i64 {
        for x in 0..img.w as i64 {
            let dx = (x as f64 + 0.5 - cx).abs();
            let dy = (y as f64 + 0.5 - cy).abs();
            if dx + dy <= r {
                img.set(x as u32, y as u32, c);
            }
        }
    }
}

/// The colour-patch set, in the *declared* space's code values.
/// Index order is stable and recorded in pattern.json for the scorer.
const PATCH_CODES: [(&str, [f32; 3]); 10] = [
    ("p3_r", [1.0, 0.0, 0.0]),
    ("p3_g", [0.0, 1.0, 0.0]),
    ("p3_b", [0.0, 0.0, 1.0]),
    ("p3_c", [0.0, 1.0, 1.0]),
    ("p3_m", [1.0, 0.0, 1.0]),
    ("p3_y", [1.0, 1.0, 0.0]),
    ("mid_warm", [0.75, 0.45, 0.35]),
    ("mid_green", [0.35, 0.65, 0.35]),
    ("mid_cool", [0.35, 0.45, 0.75]),
    ("mid_neutral", [0.5, 0.5, 0.5]),
];

/// Render the pattern at `w`x`h`. Layout is proportional so both the 384x256
/// and the 381x253 renders carry the same semantics.
pub fn render(w: u32, h: u32) -> Pattern {
    let mut img = Rgb16::new(w, h);
    let (wf, hf) = (w as f64, h as f64);

    // Background: asymmetric diagonal ramp, low contrast so markers dominate.
    for y in 0..h {
        for x in 0..w {
            let t = (x as f64 / wf * 0.6 + y as f64 / hf * 0.4) as f32;
            let g = 0.82 + 0.10 * t;
            img.set(x, y, [u16c(g * 0.97), u16c(g), u16c(g * 0.94)]);
        }
    }

    // Corner markers, ~15% of the short side.
    let m = (hf * 0.22) as i64; // marker extent
    let inset = (hf * 0.03) as i64;
    // TL: dark red square with white bars top+left ("L" corner mark)
    rect(
        &mut img,
        inset,
        inset,
        inset + m,
        inset + m,
        [u16c(0.55), u16c(0.08), u16c(0.10)],
    );
    rect(
        &mut img,
        inset,
        inset,
        inset + m,
        inset + m / 5,
        [U16MAX; 3],
    );
    rect(
        &mut img,
        inset,
        inset,
        inset + m / 5,
        inset + m,
        [U16MAX; 3],
    );
    // TR: dark blue square with green circle
    let tx0 = wf as i64 - inset - m;
    rect(
        &mut img,
        tx0,
        inset,
        tx0 + m,
        inset + m,
        [u16c(0.10), u16c(0.16), u16c(0.55)],
    );
    circle(
        &mut img,
        tx0 as f64 + m as f64 / 2.0,
        inset as f64 + m as f64 / 2.0,
        m as f64 * 0.36,
        [u16c(0.05), u16c(0.75), u16c(0.15)],
    );
    // BL: dark red square with blue triangle
    let by0 = hf as i64 - inset - m;
    rect(
        &mut img,
        inset,
        by0,
        inset + m,
        by0 + m,
        [u16c(0.55), u16c(0.10), u16c(0.10)],
    );
    tri(
        &mut img,
        [
            inset as f64,
            (by0 + m) as f64,
            inset as f64,
            by0 as f64,
            (inset + m) as f64,
            (by0 + m) as f64,
        ],
        [u16c(0.08), u16c(0.15), u16c(0.8)],
    );
    // BR: dark green square with yellow diamond
    rect(
        &mut img,
        tx0,
        by0,
        tx0 + m,
        by0 + m,
        [u16c(0.08), u16c(0.45), u16c(0.12)],
    );
    diamond(
        &mut img,
        tx0 as f64 + m as f64 / 2.0,
        by0 as f64 + m as f64 / 2.0,
        m as f64 * 0.42,
        [u16c(0.95), u16c(0.85), u16c(0.10)],
    );

    // Asymmetric glyph: a bold NE arrow — shaft plus head, plus a hole dot.
    let gx = wf * 0.44;
    let gy = hf * 0.44;
    let gl = hf * 0.30;
    let gt = hf * 0.055;
    // shaft along the SW->NE diagonal
    for i in 0..(gl as i64) {
        let t = i as f64 / gl;
        let cx = gx + t * gl * 0.9;
        let cy = gy + gl * 0.62 - t * gl * 0.9;
        rect(
            &mut img,
            (cx - gt) as i64,
            (cy - gt) as i64,
            (cx + gt) as i64,
            (cy + gt) as i64,
            [u16c(0.06); 3],
        );
    }
    // arrow head: triangle at the NE end
    let hx = gx + gl * 0.9;
    let hy = gy + gl * 0.62 - gl * 0.9;
    tri(
        &mut img,
        [
            hx + gl * 0.30,
            hy - gl * 0.30,
            hx - gl * 0.02,
            hy - gl * 0.34,
            hx + gl * 0.34,
            hy + gl * 0.02,
        ],
        [u16c(0.06); 3],
    );
    // hole dot at the SW end
    circle(&mut img, gx, gy + gl * 0.62, gt * 0.8, [u16c(0.92); 3]);

    let patches = patch_layout(w, h);
    for p in patches.iter() {
        rect(
            &mut img,
            p.x as i64 - 1,
            p.y as i64 - 1,
            (p.x + p.w) as i64 + 1,
            (p.y + p.h) as i64 + 1,
            [u16c(0.1); 3],
        );
        rect(
            &mut img,
            p.x as i64,
            p.y as i64,
            (p.x + p.w) as i64,
            (p.y + p.h) as i64,
            p.code,
        );
    }

    // 16-step neutral ramp along the bottom.
    let rh = (hf * 0.10) as i64;
    let ry = hf as i64 - rh;
    let rw = wf as i64 / 16;
    for i in 0..16 {
        let v = i as f32 / 15.0;
        rect(&mut img, i * rw, ry, (i + 1) * rw, hf as i64, [u16c(v); 3]);
    }

    Pattern { img, patches }
}

/// The colour-patch strip layout for a `w`x`h` pattern render — the same
/// geometry `render` draws. Exposed so the scorer can sample patch means
/// without re-rendering the image.
pub fn patch_layout(w: u32, h: u32) -> Vec<Patch> {
    let (wf, hf) = (w as f64, h as f64);
    let pw = (wf * 0.055) as i64;
    let ph = (hf * 0.11) as i64;
    let gap = ((wf - 10.0 * pw as f64) / 11.0) as i64;
    let py = (hf * 0.60) as i64;
    let u16c = |v: f32| (v * 65535.0) as u16;
    PATCH_CODES
        .iter()
        .enumerate()
        .map(|(i, (name, c))| Patch {
            name,
            x: (gap + i as i64 * (pw + gap)) as u32,
            y: py as u32,
            w: pw as u32,
            h: ph as u32,
            code: [u16c(c[0]), u16c(c[1]), u16c(c[2])],
        })
        .collect()
}
