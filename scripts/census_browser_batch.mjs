// Browser leg of scripts/render_v4_compat_census.py: each file through a headless browser's own
// image decoder, one browser launch per chunk. The decode is the compat matrix's canvas mode
// (/opt/adapters/browser_decode.mjs in imazen26-compat:browsers: decode in an image element, draw
// on a canvas, read back with getImageData) over another transport.
//
//   node census_browser_batch.mjs <chromium|firefox|webkit> <list.tsv> <out-dir>
//
// list.tsv: <n><TAB><input path> per line. For each file it writes <out-dir>/<n>.png and
// <out-dir>/<n>.json with the adapter's fields (status, w, h, ms, version, error_head, mean, std).
//
// A loopback server inside the container (which has no network) serves the file to the page the
// way a site serves an image; the page decodes it with Image.decode(), draws it, and posts the
// getImageData() pixels back, which this script writes as an 8-bit RGBA PNG. The adapter instead
// puts the file in a data: URL inside the page's HTML and returns the canvas as another data: URL,
// and both strings cross the browser's automation connection. In the first census pass
// (2026-10-16, compat-census/census.data-url-2026-10-16.tsv) WebKit failed every file of 51.5 MB
// and up and read every one up to 49.2 MB (the base64 passes 64 MiB in between), and Chromium's
// renderer crashed on every file of 87.6 MB and up: limits of that transport, reached before any
// image decoder saw the bytes.
//
// An all-zero readback after a successful decode is a readback failure (WebKit), not a decode.
// A crashed or stuck browser is relaunched for the next file.
import { readFileSync, writeFileSync, mkdtempSync, createReadStream, statSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import http from 'node:http';
import { pipeline } from 'node:stream';
import zlib from 'node:zlib';
import os from 'node:os';
import { join } from 'node:path';
import { chromium, firefox, webkit } from '/opt/adapters/node_modules/playwright/index.mjs';

const [engineName, listPath, outDir] = process.argv.slice(2);
const engine = { chromium, firefox, webkit }[engineName];
if (!engine) throw new Error(`unknown engine ${engineName}`);
const items = readFileSync(listPath, 'utf8').split('\n').filter(Boolean).map(l => l.split('\t'));
const inputs = new Map(items);
// Decoding and reading back a 124 MP image takes WebKit minutes; a file past this is stuck.
const FILE_TIMEOUT_MS = 900_000;

function mime(p) {
  return p.endsWith('.png') ? 'image/png' : /\.jxl$/i.test(p) ? 'image/jxl' : p.endsWith('.webp') ? 'image/webp' : 'image/jpeg';
}

// The readback of the file being read (a late post from an abandoned file is dropped).
const posted = new Map();
let current = null;
const server = http.createServer((req, res) => {
  const path = new URL(req.url, 'http://loopback').pathname;
  let m;
  if (req.method === 'GET' && path === '/') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    res.end('<!doctype html><body style="margin:0"></body>');
  } else if (req.method === 'GET' && (m = path.match(/^\/img\/(\d+)$/)) && inputs.has(m[1])) {
    const input = inputs.get(m[1]);
    res.writeHead(200, { 'content-type': mime(input), 'content-length': statSync(input).size, 'cache-control': 'no-store' });
    pipeline(createReadStream(input), res, () => {});
  } else if (req.method === 'POST' && (m = path.match(/^\/out\/(\d+)$/))) {
    const parts = [];
    req.on('data', d => parts.push(d));
    req.on('end', () => {
      if (m[1] === current) posted.set(m[1], Buffer.concat(parts));
      res.writeHead(204);
      res.end();
    });
  } else {
    res.writeHead(404);
    res.end();
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;

// Runs in the page: decode, draw, read back, post the pixels to the loopback server.
async function readInPage(n) {
  const img = new Image();
  img.src = `/img/${n}`;
  try {
    await img.decode();
  } catch (e) {
    throw new Error(`image failed to decode (${e && e.name}: ${e && e.message})`);
  }
  const w = img.naturalWidth, h = img.naturalHeight;
  if (!(w > 0 && h > 0)) throw new Error(`image failed to decode (naturalWidth=${w})`);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d');
  if (!ctx) throw new Error(`no 2d context for a ${w}x${h} canvas`);
  ctx.drawImage(img, 0, 0);
  const d = ctx.getImageData(0, 0, w, h).data;
  const px = w * h, mean = [0, 0, 0], varr = [0, 0, 0];
  for (let i = 0; i < d.length; i += 4) { mean[0] += d[i]; mean[1] += d[i + 1]; mean[2] += d[i + 2]; }
  mean[0] /= px; mean[1] /= px; mean[2] /= px;
  for (let i = 0; i < d.length; i += 4) {
    varr[0] += (d[i] - mean[0]) ** 2; varr[1] += (d[i + 1] - mean[1]) ** 2; varr[2] += (d[i + 2] - mean[2]) ** 2;
  }
  const std = varr.map(v => Math.sqrt(v / px));
  if (mean.every(v => v === 0) && std.every(v => v === 0)) throw new Error('canvas readback returned all-zero pixels');
  // A Blob body: Chromium's protocol connection copies a typed-array request body into its
  // request event, which for a large readback passes the 512 MB string Playwright can parse.
  const r = await fetch(`/out/${n}`, { method: 'POST', body: new Blob([d]) });
  if (!r.ok) throw new Error(`readback post failed: HTTP ${r.status}`);
  return { w, h, mean: mean.map(x => Math.round(x * 100) / 100), std: std.map(x => Math.round(x * 100) / 100) };
}

function withTimeout(promise, ms, what) {
  let timer;
  const expire = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${what} timed out after ${ms / 1000} s`)), ms);
  });
  return Promise.race([promise, expire]).finally(() => clearTimeout(timer));
}

// An 8-bit RGBA PNG of a readback: filter 0 on every row, one IDAT.
function pngChunk(type, data) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, 'latin1');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(zlib.crc32(data, zlib.crc32(head.subarray(4))), 0);
  return [head, data, crc];
}

function encodePng(w, h, rgba) {
  const stride = w * 4;
  const raw = Buffer.alloc((stride + 1) * h);
  for (let y = 0; y < h; y++) rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // colour type: RGBA
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), ...pngChunk('IHDR', ihdr),
    ...pngChunk('IDAT', zlib.deflateSync(raw, { level: 1 })), ...pngChunk('IEND', Buffer.alloc(0))]);
}

async function launch() {
  if (engineName === 'firefox') {
    const dir = join(mkdtempSync(join(os.tmpdir(), 'cm-ffprof-')), 'profile');
    const ctx = await firefox.launchPersistentContext(dir, { deviceScaleFactor: 1 });
    const version = execFileSync(firefox.executablePath(), ['--version']).toString().match(/(\d+\.\d+[\w.]*)/)?.[1] ?? 'unknown';
    return { version, close: () => ctx.close(), newPage: () => ctx.newPage() };
  }
  const b = await engine.launch(engineName === 'chromium' ? { channel: 'chromium' } : {});
  return { version: b.version(), close: () => b.close(), newPage: () => b.newPage({ deviceScaleFactor: 1 }) };
}

async function quietly(promise) {
  try { await withTimeout(promise, 60_000, 'close'); } catch { /* gone or stuck: dropped */ }
}

let br = null;
for (const [n] of items) {
  const t0 = Date.now();
  const json = { status: 'error', w: 0, h: 0, ms: 0, version: '', error_head: '' };
  let page = null, relaunch = false;
  current = n;
  try {
    if (!br) br = await launch();
    json.version = `${engineName}-${br.version}-canvas-http`;
    page = await br.newPage();
    await page.goto(`${origin}/`);
    const result = await withTimeout(page.evaluate(readInPage, n), FILE_TIMEOUT_MS, 'decode and readback');
    const rgba = posted.get(n);
    if (!rgba || rgba.length !== result.w * result.h * 4) {
      throw new Error(`readback holds ${rgba ? rgba.length : 0} bytes for ${result.w}x${result.h}`);
    }
    writeFileSync(join(outDir, `${n}.png`), encodePng(result.w, result.h, rgba));
    Object.assign(json, { status: 'ok', w: result.w, h: result.h, mean: result.mean, std: result.std });
  } catch (e) {
    json.error_head = String(e && e.message || e).replace(/\s+/g, ' ').slice(0, 300);
    relaunch = /timed out|Target (page, context or browser )?(has been )?closed|Browser has been closed|crash/i.test(json.error_head);
  } finally {
    current = null;
    posted.delete(n);
    if (page) await quietly(page.close());
  }
  if (relaunch && br) {
    await quietly(br.close());
    br = null;
  }
  json.ms = Date.now() - t0;
  writeFileSync(join(outDir, `${n}.json`), JSON.stringify(json) + '\n');
}
if (br) await quietly(br.close());
server.closeAllConnections();
server.close();
process.exit(0);
