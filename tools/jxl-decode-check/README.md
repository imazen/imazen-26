# jxl-decode-check

Decodes the imazen-26 render v4 layers with independent decoders and hashes every decoded
bitmap: zenpng for the PNG layers; zenjxl, jxl-rs and libjxl for the JPEG XL layers, including
every `jhgm` gain map. `scripts/render_v4_decode_check.sh` runs it over a render tree and
`scripts/render_v4_decode_report.py` compares the decoders (EXPORT-PLAN.md, "Gates").

```sh
# libjxl v0.12.0, out of tree (the gain-map bundle parser is in libjxl's extras library, which
# the distribution packages leave out); the same build jxl-encoder's tests use
git -C ~/work/jxl-efforts/libjxl checkout v0.12.0
cmake -S ~/work/jxl-efforts/libjxl -B ~/tmp/libjxl-v012-build -DCMAKE_BUILD_TYPE=Release \
  -DJPEGXL_ENABLE_OPENEXR=OFF -DBUILD_TESTING=OFF -DJPEGXL_ENABLE_BENCHMARK=OFF \
  -DJPEGXL_ENABLE_EXAMPLES=OFF -DJPEGXL_ENABLE_JPEGLI=OFF
make -C ~/tmp/libjxl-v012-build -j16 cjxl djxl jxl-internal jxl_extras_nocodec-internal jxl_cms

scripts/render_v4_decode_check.sh <render-dir> [jobs]
```

The hash is XXH3-64 (seed 0) of the interleaved samples in the image's own layout (gray,
gray+alpha, RGB or RGBA; 8-bit, or 16-bit little-endian above 8 bits), rows packed, in displayed
orientation. Every decoder is asked for exactly that layout, so equal hashes mean equal pixels.

- `zenjxl` decodes through its zencodec job with `OrientationHint::Correct` and
  `GainMapRender::Components`; zenjxl's bundle parser reads the `jhgm` box.
- `jxl-rs` (crates.io `jxl` 0.7.4) returns the `jhgm` box's bytes only; the tool reads the
  bundle layout of libjxl's `jxl/gain_map.h` itself and decodes the gain-map codestream with
  jxl-rs.
- `libjxl` (`libjxl/libjxl_hash.c`) reads the box with the decoder's box API and parses it
  with `JxlGainMapReadBundle`.
- `hdr` mode applies each gain map with zenjxl's `GainMapRender::ReconstructHdr` and compares
  the result with the 16-bit PQ render: differences in 10-bit PQ code values over every sample,
  and in stops over samples at or above 5% of SDR white.

jxl-rs and libjxl are third-party test oracles: they read, and never write anything shipped.
The zen crates come from main with the patches of `tools/render-v4`, and `Cargo.lock` started
from render-v4's, so the zen decode is the one that wrote the files.
