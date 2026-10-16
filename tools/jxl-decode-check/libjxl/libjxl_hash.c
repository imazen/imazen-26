// libjxl leg of tools/jxl-decode-check: decode JPEG XL files with libjxl and hash what it gives.
//
//   libjxl_hash [--gainmap-dir DIR] < paths > report.tsv
//
// For each path on stdin, one TSV row: the base image decoded in displayed orientation (libjxl's
// default), native channels (colour + alpha) as 8-bit samples (16-bit little-endian above 8
// bits; `bits` gives that sample size), XXH3-64 of the interleaved samples; and, when the file has a `jhgm` box,
// libjxl's own bundle parser (JxlGainMapReadBundle) and a decode of the gain-map codestream,
// hashed the same way. With --gainmap-dir, each gain map is written as DIR/<basename>.pgm/.ppm
// and its ISO 21496-1 metadata as DIR/<basename>.iso21496, for comparison with the references.
// Third-party code: a test oracle only (EXPORT-PLAN.md, "Gates"); it never writes shipped files.
#include <jxl/decode.h>
#include <jxl/gain_map.h>
#include <xxhash.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  int ok;
  char err[160];
  uint32_t w, h, channels, bits, orientation;
  XXH64_hash_t xxh3;
  uint8_t *pixels;
  size_t pixels_len;
  uint8_t *jhgm;
  size_t jhgm_len;
} Decoded;

static uint8_t *read_file(const char *path, size_t *len) {
  FILE *f = fopen(path, "rb");
  if (!f) return NULL;
  if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
  long n = ftell(f);
  if (n < 0 || fseek(f, 0, SEEK_SET) != 0) { fclose(f); return NULL; }
  uint8_t *buf = malloc(n > 0 ? (size_t)n : 1);
  if (buf && fread(buf, 1, (size_t)n, f) != (size_t)n) { free(buf); buf = NULL; }
  fclose(f);
  *len = (size_t)n;
  return buf;
}

// The orientation the header signals (libjxl reports identity once it applies it itself).
static uint32_t header_orientation(const uint8_t *data, size_t len) {
  uint32_t o = 0;
  JxlDecoder *dec = JxlDecoderCreate(NULL);
  if (!dec) return 0;
  JxlBasicInfo info;
  if (JxlDecoderSubscribeEvents(dec, JXL_DEC_BASIC_INFO) == JXL_DEC_SUCCESS &&
      JxlDecoderSetKeepOrientation(dec, JXL_TRUE) == JXL_DEC_SUCCESS &&
      JxlDecoderSetInput(dec, data, len) == JXL_DEC_SUCCESS) {
    JxlDecoderCloseInput(dec);
    if (JxlDecoderProcessInput(dec) == JXL_DEC_BASIC_INFO && JxlDecoderGetBasicInfo(dec, &info) == JXL_DEC_SUCCESS)
      o = info.orientation;
  }
  JxlDecoderDestroy(dec);
  return o;
}

// Decode one codestream or container in displayed orientation (libjxl's default); with
// want_jhgm, also capture the decompressed jhgm box.
static void decode(const uint8_t *data, size_t len, int want_jhgm, int keep_pixels, Decoded *out) {
  memset(out, 0, sizeof *out);
  JxlDecoder *dec = JxlDecoderCreate(NULL);
  if (!dec) { snprintf(out->err, sizeof out->err, "JxlDecoderCreate failed"); return; }
  int events = JXL_DEC_BASIC_INFO | JXL_DEC_FULL_IMAGE;
  if (want_jhgm) events |= JXL_DEC_BOX | JXL_DEC_BOX_COMPLETE;
  if (JxlDecoderSubscribeEvents(dec, events) != JXL_DEC_SUCCESS ||
      (want_jhgm && JxlDecoderSetDecompressBoxes(dec, JXL_TRUE) != JXL_DEC_SUCCESS) ||
      JxlDecoderSetInput(dec, data, len) != JXL_DEC_SUCCESS) {
    snprintf(out->err, sizeof out->err, "decoder setup failed");
    JxlDecoderDestroy(dec);
    return;
  }
  JxlDecoderCloseInput(dec);
  JxlBasicInfo info;
  JxlPixelFormat fmt = {0, JXL_TYPE_UINT8, JXL_LITTLE_ENDIAN, 0};
  int in_jhgm = 0, have_image = 0;
  size_t box_cap = 0;
  for (;;) {
    JxlDecoderStatus st = JxlDecoderProcessInput(dec);
    if (st == JXL_DEC_ERROR) { snprintf(out->err, sizeof out->err, "libjxl decode error"); break; }
    if (st == JXL_DEC_NEED_MORE_INPUT) { snprintf(out->err, sizeof out->err, "truncated input"); break; }
    if (st == JXL_DEC_BASIC_INFO) {
      if (JxlDecoderGetBasicInfo(dec, &info) != JXL_DEC_SUCCESS) { snprintf(out->err, sizeof out->err, "basic info"); break; }
      if (info.exponent_bits_per_sample != 0) { snprintf(out->err, sizeof out->err, "float samples"); break; }
      out->w = info.xsize; out->h = info.ysize; out->orientation = header_orientation(data, len);
      out->channels = info.num_color_channels + (info.alpha_bits > 0 ? 1 : 0);
      // The output sample size, as the other legs report it: 8, or 16 above 8 bits (a 1-bit
      // image decodes to 8-bit samples of 0 and 255).
      out->bits = info.bits_per_sample <= 8 ? 8 : 16;
      fmt.num_channels = out->channels;
      fmt.data_type = info.bits_per_sample <= 8 ? JXL_TYPE_UINT8 : JXL_TYPE_UINT16;
    } else if (st == JXL_DEC_NEED_IMAGE_OUT_BUFFER) {
      size_t need;
      if (JxlDecoderImageOutBufferSize(dec, &fmt, &need) != JXL_DEC_SUCCESS) { snprintf(out->err, sizeof out->err, "out buffer size"); break; }
      out->pixels = malloc(need);
      out->pixels_len = need;
      if (!out->pixels || JxlDecoderSetImageOutBuffer(dec, &fmt, out->pixels, need) != JXL_DEC_SUCCESS) { snprintf(out->err, sizeof out->err, "out buffer"); break; }
    } else if (st == JXL_DEC_FULL_IMAGE) {
      have_image = 1;
    } else if (st == JXL_DEC_BOX) {
      if (in_jhgm) { out->jhgm_len = box_cap - JxlDecoderReleaseBoxBuffer(dec); in_jhgm = 0; }
      JxlBoxType type;
      if (JxlDecoderGetBoxType(dec, type, JXL_TRUE) != JXL_DEC_SUCCESS) { snprintf(out->err, sizeof out->err, "box type"); break; }
      if (memcmp(type, "jhgm", 4) == 0) {
        if (out->jhgm) { snprintf(out->err, sizeof out->err, "two jhgm boxes"); break; }
        box_cap = 1 << 16;
        out->jhgm = malloc(box_cap);
        if (!out->jhgm || JxlDecoderSetBoxBuffer(dec, out->jhgm, box_cap) != JXL_DEC_SUCCESS) { snprintf(out->err, sizeof out->err, "box buffer"); break; }
        in_jhgm = 1;
      }
    } else if (st == JXL_DEC_BOX_NEED_MORE_OUTPUT) {
      size_t left = JxlDecoderReleaseBoxBuffer(dec), used = box_cap - left;
      size_t cap = box_cap * 2;
      uint8_t *grown = realloc(out->jhgm, cap);
      if (!grown) { snprintf(out->err, sizeof out->err, "box realloc"); break; }
      out->jhgm = grown; box_cap = cap;
      if (JxlDecoderSetBoxBuffer(dec, out->jhgm + used, box_cap - used) != JXL_DEC_SUCCESS) { snprintf(out->err, sizeof out->err, "box buffer"); break; }
    } else if (st == JXL_DEC_BOX_COMPLETE) {
      if (in_jhgm) { out->jhgm_len = box_cap - JxlDecoderReleaseBoxBuffer(dec); in_jhgm = 0; }
    } else if (st == JXL_DEC_SUCCESS) {
      if (in_jhgm) { out->jhgm_len = box_cap - JxlDecoderReleaseBoxBuffer(dec); in_jhgm = 0; }
      if (!have_image) { snprintf(out->err, sizeof out->err, "no image"); break; }
      out->xxh3 = XXH3_64bits(out->pixels, out->pixels_len);
      out->ok = 1;
      break;
    }
  }
  JxlDecoderDestroy(dec);
  if (!out->ok || !keep_pixels) { free(out->pixels); out->pixels = NULL; }
  if (!out->ok) { free(out->jhgm); out->jhgm = NULL; out->jhgm_len = 0; }
}

static int write_pnm(const char *path, const Decoded *d) {
  if (d->bits > 8 || (d->channels != 1 && d->channels != 3)) return -1;
  FILE *f = fopen(path, "wb");
  if (!f) return -1;
  fprintf(f, "P%c\n%u %u\n255\n", d->channels == 1 ? '5' : '6', d->w, d->h);
  size_t n = fwrite(d->pixels, 1, d->pixels_len, f);
  return (fclose(f) == 0 && n == d->pixels_len) ? 0 : -1;
}

int main(int argc, char **argv) {
  const char *dir = NULL;
  if (argc == 3 && strcmp(argv[1], "--gainmap-dir") == 0) dir = argv[2];
  else if (argc != 1) { fprintf(stderr, "usage: libjxl_hash [--gainmap-dir DIR] < paths\n"); return 2; }
  printf("path\tdecoder\tstatus\twidth\theight\tchannels\tbits\torientation\txxh3\tjhgm_bytes\tjhgm_version\t"
         "metadata_bytes\tmetadata_xxh3\thas_color_encoding\talt_icc_bytes\tgain_map_bytes\tgm_status\tgm_width\t"
         "gm_height\tgm_channels\tgm_bits\tgm_xxh3\terror\n");
  char line[8192];
  int failures = 0;
  while (fgets(line, sizeof line, stdin)) {
    line[strcspn(line, "\r\n")] = 0;
    if (!*line) continue;
    size_t len;
    uint8_t *data = read_file(line, &len);
    if (!data) { printf("%s\tlibjxl\terror\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\tread: %s\n", line, strerror(errno)); failures++; continue; }
    Decoded d;
    decode(data, len, 1, 0, &d);
    printf("%s\tlibjxl\t%s\t%u\t%u\t%u\t%u\t%u\t", line, d.ok ? "ok" : "error", d.w, d.h, d.channels, d.bits, d.orientation);
    if (d.ok) printf("%016" PRIx64, (uint64_t)d.xxh3);
    char err[9000] = "";
    if (!d.ok) { snprintf(err, sizeof err, "%s", d.err); failures++; }
    if (d.ok && d.jhgm) {
      JxlGainMapBundle b;
      memset(&b, 0, sizeof b);
      size_t used = 0;
      printf("\t%zu", d.jhgm_len);
      if (!JxlGainMapReadBundle(&b, d.jhgm, d.jhgm_len, &used)) {
        printf("\t\t\t\t\t\t\terror\t\t\t\t\t\t");
        snprintf(err, sizeof err, "JxlGainMapReadBundle failed");
        failures++;
      } else {
        Decoded g;
        decode(b.gain_map, b.gain_map_size, 0, 1, &g);
        printf("\t%u\t%u\t%016" PRIx64 "\t%d\t%u\t%u\t%s\t%u\t%u\t%u\t%u\t", b.jhgm_version, b.gain_map_metadata_size,
               (uint64_t)XXH3_64bits(b.gain_map_metadata, b.gain_map_metadata_size), b.has_color_encoding ? 1 : 0,
               b.alt_icc_size, b.gain_map_size, g.ok ? "ok" : "error", g.w, g.h, g.channels, g.bits);
        if (g.ok) printf("%016" PRIx64, (uint64_t)g.xxh3);
        if (!g.ok) { snprintf(err, sizeof err, "gain map: %s", g.err); failures++; }
        if (used != d.jhgm_len) { snprintf(err, sizeof err, "bundle read %zu of %zu bytes", used, d.jhgm_len); failures++; }
        if (dir && g.ok) {
          const char *base = strrchr(line, '/');
          base = base ? base + 1 : line;
          char p[8400];
          snprintf(p, sizeof p, "%s/%s.%s", dir, base, g.channels == 1 ? "pgm" : "ppm");
          if (write_pnm(p, &g) != 0) { snprintf(err, sizeof err, "write %s", p); failures++; }
          snprintf(p, sizeof p, "%s/%s.iso21496", dir, base);
          FILE *f = fopen(p, "wb");
          if (!f || fwrite(b.gain_map_metadata, 1, b.gain_map_metadata_size, f) != b.gain_map_metadata_size) { snprintf(err, sizeof err, "write %s", p); failures++; }
          if (f) fclose(f);
        }
        free(g.pixels);
      }
    } else {
      printf("\t\t\t\t\t\t\t\t\t\t\t\t\t");
    }
    printf("\t%s\n", err);
    fflush(stdout);
    free(d.jhgm);
    free(data);
  }
  return failures ? 1 : 0;
}
