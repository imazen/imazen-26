// Browser leg of scripts/render_v4_compat_census.py: the compat matrix's canvas-mode browser
// adapter (/opt/adapters/browser_decode.mjs in imazen26-compat:browsers) over a whole chunk with
// one browser launch, instead of a launch per file.
//
//   node census_browser_batch.mjs <chromium|firefox|webkit> <list.tsv> <out-dir>
//
// list.tsv: <n><TAB><input path> per line. For each file it writes <out-dir>/<n>.png and
// <out-dir>/<n>.json with the adapter's fields (status, w, h, ms, version, error_head, mean,
// std). The decode path is the adapter's canvas mode, unchanged: the file as a data: URL in an
// <img>, which must decode (naturalWidth > 0), then drawImage and getImageData; an all-zero
// readback after a successful load is a readback failure (WebKit), not a decode. A crashed
// browser is relaunched for the next file.
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import os from 'node:os';
import { join } from 'node:path';
import { chromium, firefox, webkit } from '/opt/adapters/node_modules/playwright/index.mjs';

const [engineName, listPath, outDir] = process.argv.slice(2);
const engine = { chromium, firefox, webkit }[engineName];
if (!engine) throw new Error(`unknown engine ${engineName}`);
const items = readFileSync(listPath, 'utf8').split('\n').filter(Boolean).map(l => l.split('\t'));

async function launch() {
  if (engineName === 'firefox') {
    const dir = join(mkdtempSync(join(os.tmpdir(), 'cm-ffprof-')), 'profile');
    const ctx = await firefox.launchPersistentContext(dir, { deviceScaleFactor: 1 });
    const version = execFileSync(firefox.executablePath(), ['--version']).toString().match(/(\d+\.\d+[\w.]*)/)?.[1] ?? 'unknown';
    return { ctx, close: () => ctx.close(), version, newPage: () => ctx.newPage() };
  }
  const b = await engine.launch(engineName === 'chromium' ? { channel: 'chromium' } : {});
  return { close: () => b.close(), version: b.version(), newPage: () => b.newPage({ deviceScaleFactor: 1 }) };
}

function mime(p) {
  return p.endsWith('.png') ? 'image/png' : /\.jxl$/i.test(p) ? 'image/jxl' : p.endsWith('.webp') ? 'image/webp' : 'image/jpeg';
}

let br = null;
for (const [n, input] of items) {
  const t0 = Date.now();
  const json = { status: 'error', w: 0, h: 0, ms: 0, version: '', error_head: '' };
  let page = null;
  try {
    if (!br) br = await launch();
    json.version = `${engineName}-${br.version}-canvas`;
    page = await br.newPage();
    const url = `data:${mime(input)};base64,${readFileSync(input).toString('base64')}`;
    await page.setContent(`<body style="margin:0"><img id="t" src="${url}" style="display:block"></body>`);
    const decoded = await page.waitForFunction(() => {
      const im = document.getElementById('t');
      return im && im.complete ? im.naturalWidth > 0 : null;
    }, { timeout: 60000 }).then(() => true).catch(() => false);
    if (!decoded) throw new Error(`image failed to decode in ${engineName} (naturalWidth=0 or load timeout)`);
    const result = await page.evaluate(async (url) => {
      const img = new Image();
      const loaded = new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error('img.onerror')); });
      img.src = url;
      await loaded;
      const w = img.naturalWidth, h = img.naturalHeight;
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const ctx = c.getContext('2d');
      ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, w, h).data;
      const n = w * h, mean = [0, 0, 0], varr = [0, 0, 0];
      for (let i = 0; i < d.length; i += 4) { mean[0] += d[i]; mean[1] += d[i + 1]; mean[2] += d[i + 2]; }
      mean[0] /= n; mean[1] /= n; mean[2] /= n;
      for (let i = 0; i < d.length; i += 4) {
        varr[0] += (d[i] - mean[0]) ** 2; varr[1] += (d[i + 1] - mean[1]) ** 2; varr[2] += (d[i + 2] - mean[2]) ** 2;
      }
      const std = varr.map(v => Math.sqrt(v / n));
      if (mean.every(v => v === 0) && std.every(v => v === 0)) throw new Error('canvas readback returned all-zero pixels');
      return { w, h, png: c.toDataURL('image/png'), mean: mean.map(x => Math.round(x * 100) / 100), std: std.map(x => Math.round(x * 100) / 100) };
    }, url);
    const b64 = result.png.split(',', 2)[1];
    if (!b64) throw new Error('canvas toDataURL failed');
    writeFileSync(join(outDir, `${n}.png`), Buffer.from(b64, 'base64'));
    Object.assign(json, { status: 'ok', w: result.w, h: result.h, mean: result.mean, std: result.std });
  } catch (e) {
    json.error_head = String(e && e.message || e).replace(/\s+/g, ' ').slice(0, 300);
    if (/Target (page, context or browser )?(has been )?closed|Browser has been closed|crash/i.test(json.error_head)) {
      try { await br?.close(); } catch { /* already gone */ }
      br = null;
    }
  } finally {
    try { await page?.close(); } catch { /* ignore */ }
  }
  json.ms = Date.now() - t0;
  writeFileSync(join(outDir, `${n}.json`), JSON.stringify(json) + '\n');
}
try { await br?.close(); } catch { /* ignore */ }
