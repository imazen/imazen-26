//! Shared code for the compat-matrix tools: the deterministic test pattern,
//! minimal ICC/EXIF writers, and byte-level container editors (JPEG, PNG,
//! JXL codestream, HEIF). Everything here is imazen code — fixtures are never
//! written by third-party tools.

pub mod exif;
pub mod generate;
pub mod heif;
pub mod heif_box;
pub mod icc;
pub mod jpeg;
pub mod jxl;
pub mod manifest;
pub mod pattern;
pub mod png;
pub mod probe;
pub mod score;
pub mod verify;

/// A u16 RGB image.
#[derive(Clone, Debug)]
pub struct Rgb16 {
    pub w: u32,
    pub h: u32,
    /// w*h*3 samples, row-major.
    pub px: Vec<u16>,
}

impl Rgb16 {
    pub fn new(w: u32, h: u32) -> Self {
        Self {
            w,
            h,
            px: vec![0; (w * h * 3) as usize],
        }
    }
    pub fn get(&self, x: u32, y: u32) -> [u16; 3] {
        let i = ((y * self.w + x) * 3) as usize;
        [self.px[i], self.px[i + 1], self.px[i + 2]]
    }
    pub fn set(&mut self, x: u32, y: u32, v: [u16; 3]) {
        let i = ((y * self.w + x) * 3) as usize;
        self.px[i..i + 3].copy_from_slice(&v);
    }
    /// 16-bit to 8-bit: /257 maps the u16 range onto u8 (nearest: 65535->255,
    /// 0->0; it's round-down of the scaled value, standard for 16->8).
    pub fn to_rgb8(&self) -> Vec<u8> {
        self.px.iter().map(|&v| (v / 257) as u8).collect()
    }
}

/// Apply an EXIF orientation (1–8) as the *display* transform: takes stored
/// pixels to display pixels.
pub fn orient_display(src: &Rgb16, o: u8) -> Rgb16 {
    let (w, h) = (src.w, src.h);
    let (dw, dh) = if (5..=8).contains(&o) { (h, w) } else { (w, h) };
    let mut out = Rgb16::new(dw, dh);
    for y in 0..dh {
        for x in 0..dw {
            let (sx, sy) = orient_map(x, y, w, h, o);
            out.set(x, y, src.get(sx, sy));
        }
    }
    out
}

/// Display->stored pixel map for EXIF orientation `o` on a `w`x`h` stored
/// image. THE single orientation definition — `orient_display`,
/// `probe::apply_orientation_rgba8`, and any rect mapper all derive from it
/// (verified against managed_hyps.py's ORIENT table).
pub fn orient_map(x: u32, y: u32, w: u32, h: u32, o: u8) -> (u32, u32) {
    match o {
        2 => (w - 1 - x, y),
        3 => (w - 1 - x, h - 1 - y),
        4 => (x, h - 1 - y),
        5 => (y, x),
        6 => (y, h - 1 - x),
        7 => (w - 1 - y, h - 1 - x),
        8 => (w - 1 - y, x),
        _ => (x, y),
    }
}

/// Inverse EXIF orientation: display pixels -> stored pixels for tag `o`.
/// 1–5 and 7 are involutions (reflections/rot180); 6<->8 swap under inversion.
pub fn orient_inverse_display(src: &Rgb16, o: u8) -> Rgb16 {
    let inv = match o {
        6 => 8,
        8 => 6,
        _ => o,
    };
    orient_display(src, inv)
}
