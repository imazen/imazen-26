//! Patch the 3-bit `orientation - 1` field in a bare JXL codestream.
//!
//! The encoder must have been run with an intrinsic size so `extra_fields`
//! is set and the orientation slot physically exists. We locate it by
//! parsing only the SizeHeader + the two metadata flag bits — LSB-first,
//! matching jxl-encoder's BitWriter.

fn bit(d: &[u8], i: usize) -> u64 {
    ((d[i / 8] >> (i % 8)) & 1) as u64
}

fn bits(d: &[u8], i: usize, n: usize) -> u64 {
    (0..n).fold(0u64, |v, k| v | (bit(d, i + k) << k))
}

fn set_bits(d: &mut [u8], i: usize, n: usize, v: u64) {
    for k in 0..n {
        let idx = (i + k) / 8;
        let bitpos = (i + k) % 8;
        d[idx] = (d[idx] & !(1 << bitpos)) | ((((v >> k) & 1) as u8) << bitpos);
    }
}

const U2S_PAYLOAD: [usize; 4] = [9, 13, 18, 30];

/// Bit offset of the 3 orientation bits, counted from byte 0 of a bare
/// codestream (`FF 0A` signature). Err when the fields aren't present.
pub fn orientation_bit_offset(d: &[u8]) -> Result<usize, String> {
    if d.len() < 4 || d[0] != 0xFF || d[1] != 0x0A {
        return Err("not a bare JXL codestream".into());
    }
    let mut pos = 16usize;
    let small = bits(d, pos, 1) == 1;
    pos += 1;
    if small {
        pos += 5; // ysize_div8_minus_1
        let ratio = bits(d, pos, 3);
        pos += 3;
        if ratio == 0 {
            pos += 5; // xsize_div8_minus_1
        }
    } else {
        let sel = bits(d, pos, 2) as usize;
        pos += 2 + U2S_PAYLOAD[sel]; // ysize
        let ratio = bits(d, pos, 3);
        pos += 3;
        if ratio == 0 {
            let sel = bits(d, pos, 2) as usize;
            pos += 2 + U2S_PAYLOAD[sel]; // xsize
        }
    }
    let all_default = bit(d, pos) == 1;
    pos += 1;
    if all_default {
        return Err("all_default metadata: no orientation field".into());
    }
    let extra_fields = bit(d, pos) == 1;
    pos += 1;
    if !extra_fields {
        return Err("extra_fields unset: no orientation field".into());
    }
    Ok(pos)
}

/// Set the codestream orientation (1–8). Returns the previous value.
pub fn set_orientation(d: &mut [u8], o: u8) -> Result<u8, String> {
    if !(1..=8).contains(&o) {
        return Err("orientation out of range".into());
    }
    let off = orientation_bit_offset(d)?;
    let prev = (bits(d, off, 3) + 1) as u8;
    set_bits(d, off, 3, (o - 1) as u64);
    Ok(prev)
}

/// Read the codestream orientation field (1–8).
pub fn get_orientation(d: &[u8]) -> Result<u8, String> {
    let off = orientation_bit_offset(d)?;
    Ok((bits(d, off, 3) + 1) as u8)
}
