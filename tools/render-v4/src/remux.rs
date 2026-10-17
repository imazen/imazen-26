//! `jxl-remux`: the JPEG XL layers in libjxl's box order without encoding them again
//! (2026-10-17).
//!
//! jxl-encoder 11ffbf9c writes the codestream header in its own first `jxlp` box, then the
//! metadata boxes, then the frames, as libjxl does; until then every box followed the
//! codestream. Only the container changed: the codestreams `jxl` writes are byte for byte the
//! ones it wrote before. So this rewrites each file of a finished `jxl` pass into the layout
//! `jxl` writes now, keeping its codestream:
//!
//! - a bare codestream (no reconstruction data) has no boxes and is copied;
//! - a `jxlc` file (lossless, with its provenance `xml ` box, a `jxll` box at level 10, and
//!   `jhgm` on a gain-map form) goes through the calls `jxl` makes: jxl-encoder's container
//!   writer for the codestream and XMP, then `zenjxl::append_gain_map_box`;
//! - a JPEG-in-JXL file (`jxlp` 0, `jbrd`, `jxlp` 1, then Exif, XMP and `jhgm`) gets those
//!   boxes moved, in order, ahead of `jxlp` 1, which is where the transcode now writes them.
//!
//! Each output must hold the input's codestream and be in libjxl's order. The report rows are
//! the input's (kind, colour, pixel and JPEG hashes: they describe the codestream) with the new
//! file's size and sha256.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use sha2::{Digest, Sha256};

use super::{Row, hex};

/// The finished pass's layers: `<from>/<path>` for each report path (`--from`).
pub(crate) static FROM: OnceLock<PathBuf> = OnceLock::new();

/// The finished pass's report rows by id (`jxl-report.tsv` and `jxl-hdr-report.tsv` under the
/// out-dir), each split into its columns.
static ROWS: OnceLock<HashMap<String, Vec<Vec<String>>>> = OnceLock::new();

fn report_rows(out_dir: &Path) -> &'static HashMap<String, Vec<Vec<String>>> {
    ROWS.get_or_init(|| {
        let mut by_id: HashMap<String, Vec<Vec<String>>> = HashMap::new();
        for name in ["jxl-report.tsv", "jxl-hdr-report.tsv"] {
            let text = fs::read_to_string(out_dir.join(name))
                .unwrap_or_else(|e| panic!("read {name}: {e}"));
            for line in text.lines().skip(1).filter(|l| !l.is_empty()) {
                let cols: Vec<String> = line.split('\t').map(str::to_owned).collect();
                by_id.entry(cols[0].clone()).or_default().push(cols);
            }
        }
        by_id
    })
}

/// One top-level box: its type and the byte ranges of the box and of its payload.
struct Bx {
    kind: [u8; 4],
    start: usize,
    payload: usize,
    end: usize,
}

fn boxes(data: &[u8]) -> Result<Vec<Bx>, String> {
    let mut out = Vec::new();
    let mut pos = 0usize;
    while pos < data.len() {
        let head = data
            .get(pos..pos + 8)
            .ok_or_else(|| format!("truncated box header at {pos}"))?;
        let size32 = u32::from_be_bytes(head[..4].try_into().unwrap()) as usize;
        let kind: [u8; 4] = head[4..8].try_into().unwrap();
        let (header, size) = match size32 {
            0 => (8, data.len() - pos),
            1 => {
                let ext = data
                    .get(pos + 8..pos + 16)
                    .ok_or("truncated 64-bit box size")?;
                (16, u64::from_be_bytes(ext.try_into().unwrap()) as usize)
            }
            n => (8, n),
        };
        if size < header || pos + size > data.len() {
            return Err(format!("box at {pos} runs past the file"));
        }
        out.push(Bx {
            kind,
            start: pos,
            payload: pos + header,
            end: pos + size,
        });
        pos += size;
    }
    Ok(out)
}

/// The codestream: a bare codestream, or the `jxlc` payload or the `jxlp` payloads joined.
fn codestream(data: &[u8]) -> Result<Vec<u8>, String> {
    if data.starts_with(&[0xFF, 0x0A]) {
        return Ok(data.to_vec());
    }
    let mut out = Vec::new();
    for b in boxes(data)? {
        match &b.kind {
            b"jxlc" => out.extend_from_slice(&data[b.payload..b.end]),
            b"jxlp" => out.extend_from_slice(&data[b.payload + 4..b.end]),
            _ => {}
        }
    }
    Ok(out)
}

/// Why a file is not in libjxl's box order (the rule of `render_v4_jxl_check.py`), or `None`.
fn box_order_error(data: &[u8]) -> Result<Option<String>, String> {
    if data.starts_with(&[0xFF, 0x0A]) {
        return Ok(None);
    }
    let bx = boxes(data)?;
    let kinds: Vec<&[u8; 4]> = bx.iter().map(|b| &b.kind).collect();
    if kinds.len() < 3 || kinds[0] != b"JXL " || kinds[1] != b"ftyp" {
        return Ok(Some("no signature and ftyp".into()));
    }
    let lead = if kinds[2] == b"jxll" { 3 } else { 2 };
    let cs: Vec<usize> = (0..bx.len())
        .filter(|&i| kinds[i] == b"jxlc" || kinds[i] == b"jxlp")
        .collect();
    let (Some(&first), Some(&last)) = (cs.first(), cs.last()) else {
        return Ok(Some("no codestream box".into()));
    };
    if last != bx.len() - 1 {
        return Ok(Some("a box after the last codestream box".into()));
    }
    if kinds[first] == b"jxlc" {
        return Ok((cs.len() != 1 || first != lead || bx.len() != lead + 1)
            .then(|| "jxlc with other boxes".into()));
    }
    let parts: Vec<u32> = cs
        .iter()
        .map(|&i| u32::from_be_bytes(data[bx[i].payload..bx[i].payload + 4].try_into().unwrap()))
        .collect();
    let n = parts.len() as u32;
    let want: Vec<u32> = (0..n)
        .map(|k| if k + 1 == n { k | 0x8000_0000 } else { k })
        .collect();
    if first != lead || parts != want || cs.windows(2).skip(1).any(|w| w[1] != w[0] + 1) {
        return Ok(Some(format!("jxlp parts {parts:x?} at {cs:?}")));
    }
    Ok(None)
}

/// The file in libjxl's box order, with the same codestream.
fn remux_file(old: &[u8]) -> Result<Vec<u8>, String> {
    if old.starts_with(&[0xFF, 0x0A]) {
        return Ok(old.to_vec());
    }
    let bx = boxes(old)?;
    let kind = |i: usize| &bx[i].kind;
    let payload = |b: &Bx| &old[b.payload..b.end];
    if bx.len() < 3 || kind(0) != b"JXL " || kind(1) != b"ftyp" {
        return Err("not a JPEG XL container".into());
    }
    let cs: Vec<usize> = (0..bx.len())
        .filter(|&i| kind(i) == b"jxlc" || kind(i) == b"jxlp")
        .collect();
    let new = match cs.as_slice() {
        // Lossless: [JXL ftyp (jxll) jxlc xml (jhgm)].
        &[c] if kind(c) == b"jxlc" => {
            let (level, after_header) = if kind(2) == b"jxll" {
                (payload(&bx[2]), 3)
            } else {
                (&[][..], 2)
            };
            let rest: Vec<&[u8; 4]> = (c + 1..bx.len()).map(kind).collect();
            if c != after_header || !(rest == [b"xml "] || rest == [b"xml ", b"jhgm"]) {
                return Err(format!("unexpected boxes around jxlc: {:?}", names(&bx)));
            }
            let codestream = payload(&bx[c]);
            // A level-10 codestream goes in as the container the encoder makes for it without
            // metadata (jxll + jxlc); the writer keeps that level.
            let base = match level {
                [] => codestream.to_vec(),
                [10] => {
                    let mut b = old[..bx[2].end].to_vec();
                    b.extend_from_slice(&old[bx[c].start..bx[c].end]);
                    b
                }
                other => return Err(format!("unexpected jxll payload {other:?}")),
            };
            let mut out = jxl_encoder::wrap_in_container(&base, None, Some(payload(&bx[c + 1])));
            if rest.len() == 2 {
                out = zenjxl::append_gain_map_box(&out, payload(&bx[c + 2]));
            }
            out
        }
        // JPEG-in-JXL: [JXL ftyp (jxll) jxlp jbrd jxlp (Exif|brob) (xml |brob) (jhgm)].
        &[p0, p1] if kind(p0) == b"jxlp" && kind(p1) == b"jxlp" => {
            let between: Vec<&[u8; 4]> = (p0 + 1..p1).map(kind).collect();
            let after: Vec<&[u8; 4]> = (p1 + 1..bx.len()).map(kind).collect();
            if between != [b"jbrd"]
                || after
                    .iter()
                    .any(|k| ![b"Exif", b"xml ", b"brob", b"jhgm"].contains(k))
            {
                return Err(format!("unexpected boxes around jxlp: {:?}", names(&bx)));
            }
            let mut out = old[..bx[p1].start].to_vec();
            out.extend_from_slice(&old[bx[p1].end..]);
            out.extend_from_slice(&old[bx[p1].start..bx[p1].end]);
            out
        }
        _ => return Err(format!("unexpected layout: {:?}", names(&bx))),
    };
    if codestream(&new)? != codestream(old)? {
        return Err("REMUX CHANGED THE CODESTREAM".into());
    }
    if let Some(why) = box_order_error(&new)? {
        return Err(format!("not in libjxl's box order after the remux: {why}"));
    }
    Ok(new)
}

fn names(bx: &[Bx]) -> Vec<String> {
    bx.iter()
        .map(|b| String::from_utf8_lossy(&b.kind).into_owned())
        .collect()
}

/// `jxl-remux`: rewrite every JXL file of one source into libjxl's box order.
pub(crate) fn remux(row: &Row, out_dir: &Path) -> Result<Vec<String>, String> {
    let from = FROM.get().ok_or("no --from")?;
    let rows = report_rows(out_dir)
        .get(row.id)
        .ok_or("no rows in jxl-report.tsv or jxl-hdr-report.tsv")?;
    let mut lines = Vec::new();
    for cols in rows {
        // jxl-hdr-report.tsv rows stop after the jhgm column (13); an error column must be empty.
        if cols.len() < 13 || cols.get(13).is_some_and(|e| !e.is_empty()) {
            return Err(format!(
                "{}: not a finished row",
                cols.get(2).map_or("", |s| s)
            ));
        }
        let path = &cols[2];
        let old = fs::read(from.join(path)).map_err(|e| format!("read {path}: {e}"))?;
        if hex(&Sha256::digest(&old)) != cols[8] {
            return Err(format!(
                "{path}: the input is not the file jxl-report.tsv lists"
            ));
        }
        let new = remux_file(&old).map_err(|e| format!("{path}: {e}"))?;
        let dst = out_dir.join(path);
        fs::create_dir_all(dst.parent().unwrap()).map_err(|e| format!("mkdir: {e}"))?;
        fs::write(&dst, &new).map_err(|e| format!("write {path}: {e}"))?;
        let mut out = cols.clone();
        out[7] = new.len().to_string();
        out[8] = hex(&Sha256::digest(&new));
        lines.push(out.join("\t"));
    }
    Ok(lines)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bx(out: &mut Vec<u8>, kind: &[u8; 4], payload: &[u8]) {
        out.extend_from_slice(&((8 + payload.len()) as u32).to_be_bytes());
        out.extend_from_slice(kind);
        out.extend_from_slice(payload);
    }

    #[test]
    fn jpeg_layout_moves_the_metadata_ahead_of_the_frames() {
        let mut old = Vec::new();
        bx(&mut old, b"JXL ", &[0x0D, 0x0A, 0x87, 0x0A]);
        bx(&mut old, b"ftyp", b"jxl \0\0\0\0jxl ");
        bx(&mut old, b"jxlp", &[0, 0, 0, 0, 0xFF, 0x0A, 1]);
        bx(&mut old, b"jbrd", b"r");
        bx(&mut old, b"jxlp", &[0x80, 0, 0, 1, 2, 3]);
        bx(&mut old, b"brob", b"Exif.");
        bx(&mut old, b"jhgm", b"g");
        let new = remux_file(&old).unwrap();
        let kinds: Vec<String> = names(&boxes(&new).unwrap());
        assert_eq!(
            kinds,
            ["JXL ", "ftyp", "jxlp", "jbrd", "brob", "jhgm", "jxlp"]
        );
        assert_eq!(codestream(&new).unwrap(), [0xFF, 0x0A, 1, 2, 3]);
        assert_eq!(new.len(), old.len());
    }

    #[test]
    fn unexpected_layouts_are_refused() {
        let mut old = Vec::new();
        bx(&mut old, b"JXL ", &[0x0D, 0x0A, 0x87, 0x0A]);
        bx(&mut old, b"ftyp", b"jxl \0\0\0\0jxl ");
        bx(&mut old, b"jxlc", &[0xFF, 0x0A, 1]);
        bx(&mut old, b"jumb", b"c2pa");
        assert!(remux_file(&old).is_err());
    }
}
