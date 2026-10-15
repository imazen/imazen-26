# png-crush

Losslessly recompresses corpus PNGs with zenpng, built against the main branch of every
imazen crate (`../corpus-thumbs/sync-main.sh` supplies zencodec by path).

```sh
cd tools/png-crush
../corpus-thumbs/sync-main.sh
~/work/zen/scripts/run-heavy -- cargo build --release
target/release/png-crush crush list.tsv out/    # list: id<TAB>input<TAB>output-relative-path
```

For each file it decodes with zenpng, re-encodes at the given effort (`crush`, `maniac`
or a number, 0–200), decodes the result again and writes it only if the pixels match the
source exactly (compared as RGBA8). A TSV report goes to stdout: bytes in and out, encode
milliseconds, colour layout before and after, and the chunks that were dropped.

- **Carried over:** ICC, EXIF, gamma, sRGB intent, chromaticities, cICP, cLLI, mDCV and
  `pHYs`. The tool fails a file if ICC, EXIF or `pHYs` don't survive.
- **Dropped:** text chunks, XMP, C2PA (`caBX`) and other unknown chunks, `sBIT`, `bKGD` and
  `tIME`. The corpus's `sBIT` chunks are all 8,8,8, which says nothing an 8-bit PNG doesn't.
- **Layout:** zenpng picks the smallest lossless layout. RGB becomes grey or palette where
  the pixels allow, and a fully opaque alpha channel is removed.
