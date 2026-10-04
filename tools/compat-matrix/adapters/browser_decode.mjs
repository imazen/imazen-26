// Decode an image through a browser engine.
// Usage: node browser_decode.mjs <in> <out.png> <chromium|firefox|webkit> [screenshot|canvas]
//
// Modes (round-2 split — they measure different paths):
//   screenshot: <img> element screenshot via locator('img').screenshot() at
//     deviceScaleFactor 1 — the composited display path. Chromium is launched
//     with --force-color-profile=srgb so the display target is known.
//   canvas: drawImage + getImageData readback — the script-visible decode path.
//
// Gates (round 7):
//   - the <img> must reach `complete && naturalWidth > 0` before we capture —
//     a broken image screenshot is NOT a decode.
//   - prints VERSION: + PREFS: lines for the harness; PREFS includes the
//     *effective* Firefox colour prefs when readable, else the override set.
import { execSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import { join } from 'node:path';
import { chromium, firefox, webkit } from 'playwright';

const [input, outPng, engineName = 'chromium', mode = 'screenshot'] =
  process.argv.slice(2);
const engines = { chromium, firefox, webkit };
const engine = engines[engineName];
if (!engine) throw new Error(`unknown engine ${engineName}`);

const data = readFileSync(input);
const mime =
  input.endsWith('.png') ? 'image/png' :
  input.endsWith('.webp') ? 'image/webp' :
  input.endsWith('.avif') ? 'image/avif' :
  /\.(jxl)$/i.test(input) ? 'image/jxl' :
  /\.(heic|heif)$/i.test(input) ? 'image/heic' : 'image/jpeg';
const url = `data:${mime};base64,${data.toString('base64')}`;

const launchOpts = {};
if (engineName === 'chromium') {
  // `chromium` channel = full Chromium with the new headless mode (not the
  // separate chromium_headless_shell binary) — the CM pipeline matches
  // shipping Chrome.
  launchOpts.channel = 'chromium';
  if (mode === 'screenshot') {
    launchOpts.args = ['--force-color-profile=srgb'];
  }
}
let prefs = {};
if (engineName === 'firefox') {
  // FF_MODE sets gfx.color_management.mode explicitly (e.g. "2" for the
  // round-2 cm2 run); unset = no override -> shipped default applies.
  if (process.env.FF_MODE !== undefined && process.env.FF_MODE !== '') {
    prefs['gfx.color_management.mode'] = parseInt(process.env.FF_MODE, 10);
  }
  if (process.env.FF_FORCE_SRGB !== undefined && process.env.FF_FORCE_SRGB !== '') {
    prefs['gfx.color_management.force_srgb'] = process.env.FF_FORCE_SRGB === '1';
  }
  if (Object.keys(prefs).length) launchOpts.firefoxUserPrefs = prefs;
}
let browser, version, ffProfileDir = null;
if (engineName === 'firefox') {
  // Persistent context = a real profile dir on disk, so the prefs.js /
  // user.js the browser resolved can be read back after the run — the
  // *effective* gfx.color_management.mode instead of an assumed default.
  // Context options (deviceScaleFactor) go to launchPersistentContext, not
  // newPage.
  // NB: juggler rejects a pre-created empty dir ("Could not find profile
  // folder"); give it a path it creates itself.
  ffProfileDir = join(
    mkdtempSync(join(os.tmpdir(), 'cm-ffprof-')), 'profile');
  browser = await firefox.launchPersistentContext(
    ffProfileDir, { deviceScaleFactor: 1, ...launchOpts });
  version = execSync(`${firefox.executablePath()} --version`).toString()
    .match(/(\d+\.\d+[\w.]*)/)?.[1] ?? 'unknown';
} else {
  browser = await engine.launch(launchOpts);
  version = browser.version();
}
console.log('VERSION:' + version);

try {
  const page = engineName === 'firefox'
    ? await browser.newPage()
    : await browser.newPage({ deviceScaleFactor: 1 });

  // Load the image as an <img> FIRST and require a real decode: a broken
  // image (naturalWidth==0) fails loudly instead of screenshotting the
  // broken-image icon.
  await page.setContent(
    `<body style="margin:0"><img id="t" src="${url}" style="display:block"></body>`);
  const decoded = await page
    .waitForFunction(
      () => {
        const im = document.getElementById('t');
        return im && im.complete ? im.naturalWidth > 0 : null;
      },
      { timeout: 30000 },
    )
    .then(() => true)
    .catch(() => false);
  if (!decoded) {
    throw new Error(
      `image failed to decode in ${engineName} (naturalWidth=0 or load timeout)`);
  }

  if (mode === 'screenshot') {
    const buf = await page.locator('img').screenshot({ type: 'png' });
    writeFileSync(outPng, buf);
    // Channel stats of the screenshot pixels, via canvas readback of the PNG.
    const stats = await page.evaluate(async (b64) => {
      const img = new Image();
      const loaded = new Promise((res, rej) => {
        img.onload = res;
        img.onerror = () => rej(new Error('img.onerror'));
      });
      img.src = 'data:image/png;base64,' + b64;
      await loaded;
      const w = img.naturalWidth, h = img.naturalHeight;
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const ctx = c.getContext('2d');
      ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, w, h).data;
      const n = w * h, mean = [0, 0, 0], varr = [0, 0, 0];
      for (let i = 0; i < d.length; i += 4) {
        mean[0] += d[i]; mean[1] += d[i + 1]; mean[2] += d[i + 2];
      }
      mean[0] /= n; mean[1] /= n; mean[2] /= n;
      for (let i = 0; i < d.length; i += 4) {
        varr[0] += (d[i] - mean[0]) ** 2;
        varr[1] += (d[i + 1] - mean[1]) ** 2;
        varr[2] += (d[i + 2] - mean[2]) ** 2;
      }
      const std = varr.map(v => Math.sqrt(v / n));
      return { w, h,
        mean: mean.map(x => Math.round(x * 100) / 100),
        std: std.map(x => Math.round(x * 100) / 100) };
    }, buf.toString('base64'));
    console.log('STATS:' + JSON.stringify({ mean: stats.mean, std: stats.std }));
  } else {
    const result = await page.evaluate(async (url) => {
      const img = new Image();
      const loaded = new Promise((res, rej) => {
        img.onload = res;
        img.onerror = () => rej(new Error('img.onerror'));
      });
      img.src = url;
      await loaded;
      const w = img.naturalWidth, h = img.naturalHeight;
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const ctx = c.getContext('2d');
      ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, w, h).data;
      const n = w * h, mean = [0, 0, 0], varr = [0, 0, 0];
      for (let i = 0; i < d.length; i += 4) {
        mean[0] += d[i]; mean[1] += d[i + 1]; mean[2] += d[i + 2];
      }
      mean[0] /= n; mean[1] /= n; mean[2] /= n;
      for (let i = 0; i < d.length; i += 4) {
        varr[0] += (d[i] - mean[0]) ** 2;
        varr[1] += (d[i + 1] - mean[1]) ** 2;
        varr[2] += (d[i + 2] - mean[2]) ** 2;
      }
      const std = varr.map(v => Math.sqrt(v / n));
      // A uniform-zero canvas after a successful load is a readback
      // failure (WebKit surfaces that can't snapshot), not a decode.
      if (mean.every(v => v === 0) && std.every(v => v === 0)) {
        throw new Error('canvas readback returned all-zero pixels');
      }
      return { w, h, png: c.toDataURL('image/png'),
        mean: mean.map(x => Math.round(x * 100) / 100),
        std: std.map(x => Math.round(x * 100) / 100) };
    }, url);
    const b64 = result.png.split(',', 2)[1];
    if (!b64) throw new Error('canvas toDataURL failed');
    writeFileSync(outPng, Buffer.from(b64, 'base64'));
    console.log('STATS:' + JSON.stringify({ mean: result.mean, std: result.std }));
  }
} finally {
  await browser.close();
  // Effective prefs: read back the profile's prefs.js/user.js — overrides
  // land there verbatim (source marked), and a colour-management pref that
  // is absent resolves to the engine's shipped default (recorded with its
  // provenance, not silently).
  let effective = { ...prefs };
  if (engineName === 'firefox' && ffProfileDir) {
    const filePrefs = {};
    for (const f of ['user.js', 'prefs.js']) {
      const p = join(ffProfileDir, f);
      if (!existsSync(p)) continue;
      for (const m of readFileSync(p, 'utf8')
        .matchAll(/user_pref\("([^"]+)",\s*([^;]+)\);/g)) {
        try { filePrefs[m[1]] = JSON.parse(m[2]); } catch { /* ignore */ }
      }
    }
    const cmKeys = ['gfx.color_management.mode',
      'gfx.color_management.force_srgb', 'gfx.color_management.display_p3'];
    effective = {};
    for (const k of cmKeys) {
      if (k in filePrefs) {
        effective[k] = filePrefs[k];
      } else if (k in prefs) {
        effective[k] = prefs[k]; // applied via firefoxUserPrefs
      } else if (k === 'gfx.color_management.mode') {
        // pref absent in prefs.js/user.js -> shipped default applies.
        // Firefox >= 98 ships mode 2 (manage tagged content only).
        effective[k] = 'shipped-default(2)';
      }
    }
  }
  console.log('PREFS:' + JSON.stringify(effective));
  if (ffProfileDir) {
    rmSync(join(ffProfileDir, '..'), { recursive: true, force: true });
  }
}
