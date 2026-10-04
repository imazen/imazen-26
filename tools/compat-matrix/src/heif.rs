//! Minimal HEIF demux/remux for fixture generation.
//!
//! There is no imazen HEVC encoder, so HEIC fixtures are *byte-level remuxes*:
//! we copy a corpus HEIC's items (grid + tiles or a plain image), properties
//! and references into a fresh container whose signalling boxes (irot, imir,
//! colr, Exif item) we control. The HEVC payload is copied verbatim — imazen
//! authors the container, not the codestream, same rule as MPF patching.
//! The box readers/serializers live in `heif_box.rs`.

use std::collections::BTreeMap;

pub use crate::heif_box::*;

// ----------------------------------------------------------------- model

/// A demuxed HEIC image: all items, extents, properties, references.
pub struct Demux {
    pub ftyp: HBox,
    pub primary: u32,
    pub items: Vec<IinfEntry>,
    pub iloc: Vec<IlocEntry>,
    pub ipco: Vec<HBox>,
    pub ipma: Vec<IpmaAssoc>,
    pub iref: BTreeMap<[u8; 4], Vec<(u32, u32)>>,
    /// raw extent bytes per item (file-offset method only)
    pub payload: BTreeMap<u32, Vec<u8>>,
    /// `dinf` verbatim (data information box; exiftool reads it).
    pub dinf: Option<HBox>,
    pub source: Vec<u8>,
}

impl Demux {
    /// Locate `meta` children inside the file.
    pub fn load(d: &[u8]) -> Result<Self, String> {
        let top = parse_boxes(d)?;
        let ftyp = top
            .iter()
            .find(|b| &b.ty == b"ftyp")
            .cloned()
            .ok_or("no ftyp")?;
        let meta = top.iter().find(|b| &b.ty == b"meta").ok_or("no meta")?;
        let m = &meta.data[4..]; // skip fullbox hdr
        let children = parse_boxes(m)?;
        let mut items = Vec::new();
        let mut iloc = Vec::new();
        let mut ipco = Vec::new();
        let mut ipma = Vec::new();
        let mut iref = BTreeMap::new();
        let mut primary = 0u32;
        let mut dinf: Option<HBox> = None;
        let mut idat: Vec<u8> = Vec::new();
        for c in &children {
            match &c.ty {
                b"pitm" => primary = parse_pitm(&c.data),
                b"iinf" => items = parse_iinf(&c.data)?,
                b"iloc" => iloc = parse_iloc(&c.data)?,
                b"idat" => idat = c.data.clone(),
                b"iprp" => {
                    for cc in parse_boxes(&c.data)? {
                        match &cc.ty {
                            b"ipco" => ipco = parse_ipco(&cc.data),
                            b"ipma" => ipma = parse_ipma(&cc.data)?,
                            _ => {}
                        }
                    }
                }
                b"iref" => iref = parse_iref(&c.data),
                b"dinf" => dinf = Some(c.clone()),
                _ => {}
            }
        }
        let mut payload = BTreeMap::new();
        for e in &iloc {
            let src: &[u8] = match e.construction_method {
                0 => d,
                1 => &idat,
                m => {
                    return Err(format!(
                        "item {} uses construction_method {m} (unsupported)",
                        e.item_id
                    ));
                }
            };
            let mut buf = Vec::new();
            for x in &e.extents {
                let s = x.offset as usize;
                let e2 = s + x.length as usize;
                if e2 > src.len() {
                    return Err(format!("item {} extent past end of its store", e.item_id));
                }
                buf.extend_from_slice(&src[s..e2]);
            }
            payload.insert(e.item_id, buf);
        }
        Ok(Demux {
            ftyp,
            primary,
            items,
            iloc,
            ipco,
            ipma,
            iref,
            payload,
            dinf,
            source: d.to_vec(),
        })
    }

    /// Find the property list for an item (1-based indices into ipco).
    pub fn props_for(&self, item: u32) -> Vec<(u16, bool)> {
        self.ipma
            .iter()
            .find(|a| a.item_id == item)
            .map(|a| a.props.clone())
            .unwrap_or_default()
    }

    /// (w, h) of an item per its `ispe` property, or of the primary.
    pub fn dims_of(&self, item: u32) -> Option<(u32, u32)> {
        for (idx, _ess) in self.props_for(item) {
            if let Some(p) = self.ipco.get(idx as usize - 1)
                && &p.ty == b"ispe"
                && p.data.len() >= 12
            {
                let w = u32::from_be_bytes([p.data[4], p.data[5], p.data[6], p.data[7]]);
                let h = u32::from_be_bytes([p.data[8], p.data[9], p.data[10], p.data[11]]);
                return Some((w, h));
            }
        }
        None
    }

    /// The grid item's derived dimensions from its `grid` payload, if the
    /// primary is a derived grid (rows/cols/field sizes live in the payload).
    pub fn grid_dims(&self) -> Option<(u32, u32)> {
        let item = self.items.iter().find(|i| i.item_id == self.primary)?;
        if &item.item_type != b"grid" {
            return None;
        }
        let p = self.payload.get(&self.primary)?;
        // grid payload: version(1), flags(1), rows_minus1(1), cols_minus1(1),
        //   output_width u32/u16 per flags bit0, output_height same
        if p.len() < 8 {
            return None;
        }
        let wide = p[1] & 1 == 1;
        if wide {
            Some((
                u32::from_be_bytes([p[4], p[5], p[6], p[7]]),
                u32::from_be_bytes([p[8], p[9], p[10], p[11]]),
            ))
        } else {
            Some((
                u16::from_be_bytes([p[4], p[5]]) as u32,
                u16::from_be_bytes([p[6], p[7]]) as u32,
            ))
        }
    }
}

/// Remux control: what signalling to put on the primary item (and grid).
#[derive(Default)]
pub struct RemuxSignalling {
    /// irot angle (0-3 => counter-clockwise 0/90/180/270). Replaces existing.
    pub irot: Option<Option<u8>>,
    /// imir axis (0=top-bottom flip/EXIF 4, 1=left-right/EXIF 2 per
    /// ISO/IEC 23008-12:2022 6.5.12). Replaces existing.
    pub imir: Option<Option<u8>>,
    /// Extra colr property (nclx or prof bytes). `Some(bytes)` where the box
    /// must already be a valid property payload e.g. `colr` body.
    pub colr: Option<Option<HBox>>,
    /// Drop property types from the primary item's association list.
    pub drop_props: Vec<[u8; 4]>,
    /// Drop only `colr` properties whose colour_information_type is `prof` or
    /// `rICC` (keeps `nclx`). Used to render "honours nclx, ignores ICC" bases.
    pub drop_icc_colr: bool,
    /// If set: append an Exif item (raw TIFF bytes) + cdsc ref to primary.
    pub exif: Option<Vec<u8>>,
    /// Also set irot on the grid item (tiles are usually unrotated).
    pub apply_rotation_to: Vec<u32>,
    /// Extra property boxes appended (essential) to edit targets —
    /// e.g. a second `colr` for ICC-vs-nclx conflict fixtures.
    pub extra_props: Vec<HBox>,
    /// Item ids to remove entirely (iinf/iloc/ipma/iref/mdat).
    pub drop_items: Vec<u32>,
    /// If set: append a hidden `mime` item carrying an XMP packet
    /// (content_type application/rdf+xml, cdsc -> primary). The donor file
    /// carries none — the item is the thing under test, injected so the
    /// fixture is donor-independent.
    pub xmp_mime: Option<Vec<u8>>,
    /// New primary item id for `pitm` (default: keep source primary).
    pub primary: Option<u32>,
    /// Clear the iinf `hidden` flag on the new primary (a promoted tile
    /// must be displayable).
    pub unhide_primary: bool,
}

impl RemuxSignalling {
    pub fn irot(angle: u8) -> Self {
        Self {
            irot: Some(Some(angle & 3)),
            ..Self::default()
        }
    }
    pub fn imir(axis: u8) -> Self {
        Self {
            imir: Some(Some(axis & 1)),
            ..Self::default()
        }
    }
    pub fn no_orientation() -> Self {
        Self {
            irot: Some(None),
            imir: Some(None),
            ..Self::default()
        }
    }
    pub fn with_colr(mut self, b: Option<HBox>) -> Self {
        self.colr = Some(b);
        self
    }
    pub fn dropping(mut self, ty: &[u8; 4]) -> Self {
        self.drop_props.push(*ty);
        self
    }
    pub fn with_exif(mut self, tiff: Vec<u8>) -> Self {
        self.exif = Some(tiff);
        self
    }
    pub fn with_xmp_mime(mut self, xmp: Vec<u8>) -> Self {
        self.xmp_mime = Some(xmp);
        self
    }
    pub fn rotate_items(mut self, ids: Vec<u32>) -> Self {
        self.apply_rotation_to = ids;
        self
    }
    pub fn with_extra_prop(mut self, b: HBox) -> Self {
        self.extra_props.push(b);
        self
    }
    /// Keep only `keep` items; the first becomes primary (unhidden).
    pub fn keep_only(mut self, keep: &[u32], all: &[u32]) -> Self {
        self.drop_items = all.iter().cloned().filter(|i| !keep.contains(i)).collect();
        self.primary = keep.first().copied();
        self.unhide_primary = true;
        self
    }
}

/// Item ids carrying an `auxC` property whose aux_type contains `needle`
/// (e.g. `auxid:2` = the depth aux class). Used to drop libheif-rejected
/// depth auxes when rendering hypothesis bases on real iPhone HEICs —
/// the pixel payload of the surviving items is verbatim.
pub fn items_with_aux(dm: &Demux, needle: &[u8]) -> Vec<u32> {
    dm.items
        .iter()
        .filter(|i| {
            dm.props_for(i.item_id).iter().any(|(idx, _)| {
                dm.ipco
                    .get(*idx as usize - 1)
                    .map(|p| &p.ty == b"auxC" && p.data.windows(needle.len()).any(|w| w == needle))
                    .unwrap_or(false)
            })
        })
        .map(|i| i.item_id)
        .collect()
}

/// Make an `irot` property box: 1 byte, angle_code = angle/90 (NOT a FullBox).
pub fn irot_box(angle: u8) -> HBox {
    HBox::new(b"irot", vec![angle & 3])
}

/// Make an `imir` property box: 1 byte axis (NOT a FullBox).
pub fn imir_box(axis: u8) -> HBox {
    HBox::new(b"imir", vec![axis & 1])
}

/// Patch the AV1 sequence-header OBU's `matrix_coefficients` inside an
/// `av01` item payload (r13 §2): zenavif 11033c9's `matrix_coefficients()`
/// config is dead — no backend consults it — so the mc=1 fixtures patch
/// the coded stream's colour_description directly. OBU framing: header
/// byte (forbidden|type<<3|ext_flag<<2|has_size<<1|reserved), optional
/// extension byte, LEB128 size, payload. Inside the seq-header OBU the
/// fields are bit-packed per AV1 §5.5 — the colour_description triple is
/// located by parsing, and `matrix_coefficients` is rewritten in place;
/// only `reduced_still_image_header` streams (what a still-image encoder
/// emits) are supported — anything else errors rather than guesses.
pub fn av1_seq_mc_patch(
    payload: &mut [u8],
    expect_cp: u8,
    expect_tc: u8,
    mc_to: u8,
) -> Result<(), String> {
    struct BitR<'a> {
        d: &'a [u8],
        p: usize,
    }
    impl BitR<'_> {
        fn u(&mut self, n: usize) -> Result<u32, String> {
            if self.p + n > self.d.len() * 8 {
                return Err("av1 seq header: bit underrun".into());
            }
            let mut v = 0u32;
            for _ in 0..n {
                v = (v << 1) | ((self.d[self.p / 8] >> (7 - self.p % 8)) & 1) as u32;
                self.p += 1;
            }
            Ok(v)
        }
    }
    fn set_bits(d: &mut [u8], pos: usize, n: usize, v: u32) {
        for k in 0..n {
            let i = pos + k;
            let bit = (v >> (n - 1 - k)) & 1;
            if bit == 1 {
                d[i / 8] |= 1 << (7 - i % 8);
            } else {
                d[i / 8] &= !(1 << (7 - i % 8));
            }
        }
    }
    // Locate the matrix_coefficients bit offset in a seq-header OBU body.
    fn seq_mc_bitpos(body: &[u8]) -> Result<Option<(u8, u8, usize)>, String> {
        let mut r = BitR { d: body, p: 0 };
        let prof = r.u(3)?;
        r.u(1)?; // still_image
        if r.u(1)? == 0 {
            return Err("av1 seq header: not reduced_still_image_header".into());
        }
        r.u(5)?; // seq_level_idx[0]
        let fw = r.u(4)? as usize + 1;
        let fh = r.u(4)? as usize + 1;
        r.u(fw)?; // max_frame_width_minus_1
        r.u(fh)?; // max_frame_height_minus_1
        r.u(1)?; // use_128x128_superblock
        r.u(1)?; // enable_filter_intra
        r.u(1)?; // enable_intra_edge_filter
        r.u(1)?; // enable_superres
        r.u(1)?; // enable_cdef
        r.u(1)?; // enable_restoration
        let hb = r.u(1)?; // high_bitdepth
        if prof == 2 && hb == 1 {
            r.u(1)?; // twelve_bit
        }
        if prof != 1 {
            r.u(1)?; // mono_chrome
        }
        if r.u(1)? == 0 {
            return Ok(None); // color_description_present_flag
        }
        let cp = r.u(8)? as u8;
        let tc = r.u(8)? as u8;
        Ok(Some((cp, tc, r.p)))
    }
    let mut i = 0usize;
    while i < payload.len() {
        let hdr = payload[i];
        let ty = (hdr >> 3) & 0x0f;
        let ext = hdr & 0x04 != 0;
        let has_size = hdr & 0x02 != 0;
        i += 1;
        if ext {
            i += 1;
        }
        let mut size = 0u64;
        if has_size {
            let mut shift = 0;
            loop {
                let Some(&b) = payload.get(i) else {
                    return Err("av1 OBU: truncated leb128 size".into());
                };
                i += 1;
                size |= ((b & 0x7f) as u64) << shift;
                shift += 7;
                if b & 0x80 == 0 {
                    break;
                }
            }
        } else {
            size = (payload.len() - i) as u64;
        }
        let end = i + size as usize;
        if end > payload.len() {
            return Err("av1 OBU: size overruns payload".into());
        }
        if ty == 1 {
            match seq_mc_bitpos(&payload[i..end])? {
                None => return Err("av1 seq header: no colour_description present".into()),
                Some((cp, tc, pos)) => {
                    if cp != expect_cp || tc != expect_tc {
                        return Err(format!(
                            "av1 seq header: cp/tc {cp}/{tc}, expected {expect_cp}/{expect_tc}"
                        ));
                    }
                    set_bits(&mut payload[i..end], pos, 8, mc_to as u32);
                    return Ok(());
                }
            }
        }
        i = end;
    }
    Err("av1 payload: no sequence_header_obu".into())
}

/// Make a `colr` property box: `nclx` = [primaries,transfer,matrix u16 BE][full byte] or `prof`/`rICC` payload.
pub fn colr_nclx(cp: u16, tc: u16, mc: u16, full_range: bool) -> HBox {
    let mut d = b"nclx".to_vec();
    d.extend_from_slice(&cp.to_be_bytes());
    d.extend_from_slice(&tc.to_be_bytes());
    d.extend_from_slice(&mc.to_be_bytes());
    d.push(u8::from(full_range) << 7);
    HBox::new(b"colr", d)
}

/// `colr` box carrying a full ICC profile (`prof` — restricted, or `rICC`).
pub fn colr_prof(icc: &[u8]) -> HBox {
    let mut d = b"prof".to_vec();
    d.extend_from_slice(icc);
    HBox::new(b"colr", d)
}

/// Remux with new signalling. `next_id` for added items is max(items)+1.
/// Applies `drop_props` + replacements to `apply_rotation_to` items and the
/// primary item.
pub fn remux(dm: &Demux, sig: &RemuxSignalling) -> Result<Vec<u8>, String> {
    let mut ipco: Vec<HBox> = dm.ipco.clone();

    // Items receiving signalling edits: the rotation list plus the primary.
    let primary = sig.primary.unwrap_or(dm.primary);
    let mut edits: Vec<u32> = sig.apply_rotation_to.clone();
    if !edits.contains(&primary) {
        edits.push(primary);
    }

    // New properties (appended to ipco) — one per edit target set.
    let mut new_irot_idx: Option<u16> = None;
    let mut new_imir_idx: Option<u16> = None;
    let mut new_colr_idx: Option<u16> = None;
    if let Some(Some(a)) = sig.irot {
        ipco.push(irot_box(a));
        new_irot_idx = Some(ipco.len() as u16);
    }
    if let Some(Some(ax)) = sig.imir {
        ipco.push(imir_box(ax));
        new_imir_idx = Some(ipco.len() as u16);
    }
    if let Some(Some(ref c)) = sig.colr {
        ipco.push(c.clone());
        new_colr_idx = Some(ipco.len() as u16);
    }
    let extra_idx_base = ipco.len() as u16;
    for p in &sig.extra_props {
        ipco.push(p.clone());
    }

    let mut assocs: Vec<(u32, Vec<(u16, bool)>)> = Vec::new();
    for a in &dm.ipma {
        let mut props = a.props.clone();
        if edits.contains(&a.item_id) {
            props.retain(|(idx, _)| {
                let ty = ipco_type(&dm.ipco, *idx);
                !sig.drop_props.iter().any(|t| t == ty)
                    && !(sig.irot.is_some() && ty == b"irot")
                    && !(sig.imir.is_some() && ty == b"imir")
                    && !(sig.colr.is_some() && ty == b"colr")
                    && !(sig.drop_icc_colr
                        && ty == b"colr"
                        && matches!(
                            dm.ipco
                                .get(idx.saturating_sub(1) as usize)
                                .and_then(|b| b.data.get(..4)),
                            Some(x) if x == b"prof" || x == b"rICC"
                        ))
            });
            if let Some(i) = new_irot_idx {
                props.push((i, true)); // irot MUST be essential
            }
            if let Some(i) = new_imir_idx {
                props.push((i, true)); // imir MUST be essential
            }
            if let Some(i) = new_colr_idx {
                props.push((i, true)); // colr is essential
            }
            for k in 0..sig.extra_props.len() {
                props.push((extra_idx_base + k as u16 + 1, true));
            }
        }
        assocs.push((a.item_id, props));
    }

    // Item list: original order minus dropped items, plus an Exif item if
    // requested. The new primary (e.g. a promoted grid tile) is unhidden.
    let mut items: Vec<IinfEntry> = dm
        .items
        .iter()
        .filter(|e| !sig.drop_items.contains(&e.item_id))
        .map(|e| IinfEntry {
            item_id: e.item_id,
            item_type: e.item_type,
            name: e.name.clone(),
            content_type: e.content_type.clone(),
            hidden: e.hidden && !(sig.unhide_primary && e.item_id == primary),
        })
        .collect();
    assocs.retain(|(id, _)| !sig.drop_items.contains(id));
    let mut iref_refs: Vec<(u32, [u8; 4], Vec<u32>)> = Vec::new();
    for (rt, pairs) in &dm.iref {
        let mut grouped: BTreeMap<u32, Vec<u32>> = BTreeMap::new();
        for (f, t) in pairs {
            if !sig.drop_items.contains(f) && !sig.drop_items.contains(t) {
                grouped.entry(*f).or_default().push(*t);
            }
        }
        for (f, tos) in grouped {
            iref_refs.push((f, *rt, tos));
        }
    }
    let mut item_payloads: BTreeMap<u32, Vec<u8>> = dm
        .payload
        .iter()
        .filter(|(id, _)| !sig.drop_items.contains(id))
        .map(|(id, b)| (*id, b.clone()))
        .collect();

    if let Some(tiff) = &sig.exif {
        let exif_id = items.iter().map(|i| i.item_id).max().unwrap_or(0) + 1;
        // HEIF Exif item payload starts with a 4-byte TIFF-header offset.
        let mut body = Vec::with_capacity(tiff.len() + 4);
        body.extend_from_slice(&0u32.to_be_bytes());
        body.extend_from_slice(tiff);
        item_payloads.insert(exif_id, body);
        items.push(IinfEntry {
            item_id: exif_id,
            item_type: *b"Exif",
            name: "Exif".to_string(),
            content_type: None,
            hidden: false,
        });
        // Exif references the image it describes via 'cdsc'.
        iref_refs.push((exif_id, *b"cdsc", vec![primary]));
        // Exif item needs no properties.
        assocs.push((exif_id, Vec::new()));
    }
    if let Some(xmp) = &sig.xmp_mime {
        let xmp_id = items.iter().map(|i| i.item_id).max().unwrap_or(0) + 1;
        item_payloads.insert(xmp_id, xmp.clone());
        items.push(IinfEntry {
            item_id: xmp_id,
            item_type: *b"mime",
            name: "xmp".to_string(),
            content_type: Some("application/rdf+xml".to_string()),
            hidden: true,
        });
        iref_refs.push((xmp_id, *b"cdsc", vec![primary]));
        assocs.push((xmp_id, Vec::new()));
    }

    // Compact ipco: entries no surviving item references are orphans (they'd
    // be dead weight and can confuse property-index assumptions in readers).
    // Associations keep relative order; out-of-range indices pass through.
    let mut referenced: Vec<u16> = assocs
        .iter()
        .flat_map(|(_, props)| props.iter().map(|(i, _)| *i))
        .collect();
    referenced.sort_unstable();
    referenced.dedup();
    let mut remap = vec![0u16; ipco.len() + 1];
    let mut compact: Vec<HBox> = Vec::with_capacity(referenced.len());
    for old_i in &referenced {
        if let Some(p) = ipco.get(*old_i as usize - 1) {
            compact.push(p.clone());
            remap[*old_i as usize] = compact.len() as u16;
        }
    }
    let old_ipco_len = ipco.len();
    ipco = compact;
    for (_, props) in &mut assocs {
        for (idx, _) in props.iter_mut() {
            if *idx as usize <= old_ipco_len && remap[*idx as usize] != 0 {
                *idx = remap[*idx as usize];
            }
        }
    }

    // mdat: concatenate payloads in item-id order; record extents.
    let mut mdat_start: Vec<(u32, Vec<(u64, u64)>)> = Vec::new();
    let ids: Vec<u32> = {
        let mut v: Vec<u32> = item_payloads.keys().cloned().collect();
        v.sort();
        v
    };
    for id in &ids {
        let buf = &item_payloads[id];
        let mut exts = Vec::new();
        if !buf.is_empty() {
            // single extent per item (we re-pack)
            exts.push((0u64, buf.len() as u64));
        }
        mdat_start.push((*id, exts));
    }

    // Serialize once with dummy offsets to compute where mdat payloads start;
    // iloc size doesn't depend on the offset values (fixed 4-byte fields).
    let build = |iloc: HBox, mdat_payload: &[u8]| -> Vec<u8> {
        let mut meta_children = vec![make_hdlr()];
        if let Some(d) = &dm.dinf {
            meta_children.push(d.clone());
        }
        meta_children.extend([
            make_pitm(primary),
            make_iinf(&items),
            iloc,
            make_iprp(&ipco, &assocs),
            make_iref(&iref_refs),
        ]);
        let meta = make_meta(meta_children);
        let mut out = dm.ftyp.serialize();
        out.extend_from_slice(&meta.serialize());
        out.extend_from_slice(&((8 + mdat_payload.len()) as u32).to_be_bytes());
        out.extend_from_slice(b"mdat");
        out.extend_from_slice(mdat_payload);
        out
    };

    let zero_iloc = iloc_with_offsets(&mdat_start);
    let probe = build(zero_iloc, &[]);
    let mut off = probe.len() as u64; // mdat payload begins here
    let mut mdat_payload = Vec::new();
    let mut real: Vec<(u32, Vec<(u64, u64)>)> = Vec::new();
    for (id, _) in &mdat_start {
        let buf = &item_payloads[id];
        let mut exts = Vec::new();
        if !buf.is_empty() {
            exts.push((off, buf.len() as u64));
            off += buf.len() as u64;
        }
        real.push((*id, exts));
        mdat_payload.extend_from_slice(buf);
    }
    Ok(build(iloc_with_offsets(&real), &mdat_payload))
}

fn iloc_with_offsets(entries: &[(u32, Vec<(u64, u64)>)]) -> HBox {
    let refs: Vec<(u32, &[(u64, u64)])> = entries.iter().map(|(i, e)| (*i, e.as_slice())).collect();
    make_iloc(&refs)
}

fn ipco_type(ipco: &[HBox], idx1: u16) -> &[u8; 4] {
    if idx1 == 0 || idx1 as usize > ipco.len() {
        return b"    ";
    }
    &ipco[idx1 as usize - 1].ty
}
