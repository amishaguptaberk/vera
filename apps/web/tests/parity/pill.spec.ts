import { chromium, expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { launchOptions } from './browser';
import { compareState } from './compare';
import { installCaseRoutes, installSessionRoutes } from './fixtures';
import { APP_PORT, PROTOTYPE_PORT } from './playwright.config';
import { STATES, VIEWPORTS, type ParityState } from './states';

const SHOTS = process.env.VERA_PARITY_SHOTS; // optional dir to save crops

const FONT_DIR = path.resolve(__dirname, '../../node_modules/@fontsource-variable/inter/files');
const FONT_FACES = [
  {
    file: 'inter-latin-wght-normal.woff2',
    range: 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD',
  },
  {
    file: 'inter-latin-ext-wght-normal.woff2',
    range: 'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF',
  },
];

let browser: Browser;
let contexts: BrowserContext[] = [];
test.afterEach(async () => {
  await Promise.all(contexts.map((c) => c.close()));
  contexts = [];
});
test.beforeAll(async () => {
  browser = await chromium.launch(launchOptions);
});
test.afterAll(async () => {
  await browser.close();
});

async function openPrototype(width: number, height: number, state: ParityState): Promise<Page> {
  // Fresh context: localStorage (key vera-chg1042-v3) is absent by construction.
  const ctx = await browser.newContext({ viewport: { width, height } });
  contexts.push(ctx);
  const page = await ctx.newPage();
  // Offline-safe: block anything that is not the local prototype server...
  await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, (r) => r.abort());
  // ...except Inter: the prototype's Google Fonts request is served from the app's self-hosted
  // woff2 files so Inter regions compare like for like (routes registered later win).
  await page.route('https://fonts.googleapis.com/css2**', (r) =>
    r.fulfill({
      contentType: 'text/css',
      body: FONT_FACES.map(
        (f) =>
          `@font-face{font-family:'Inter';font-style:normal;font-weight:100 900;font-display:swap;` +
          `src:url(https://fonts.gstatic.com/vera-local/${f.file}) format('woff2');unicode-range:${f.range}}`,
      ).join('\n'),
    }),
  );
  await page.route('https://fonts.gstatic.com/vera-local/*', (r) => {
    const file = path.basename(new URL(r.request().url()).pathname);
    if (!FONT_FACES.some((f) => f.file === file)) return r.abort();
    return r.fulfill({ contentType: 'font/woff2', body: readFileSync(path.join(FONT_DIR, file)) });
  });
  // Record the saved-state key before any prototype script runs (the prototype writes it on load).
  await page.addInitScript(() => {
    (window as unknown as { __keyAtStart: string | null }).__keyAtStart = localStorage.getItem('vera-chg1042-v3');
  });
  await page.goto(`http://127.0.0.1:${PROTOTYPE_PORT}/Main.dc.html`, { waitUntil: 'domcontentloaded' });
  expect(await page.evaluate(() => (window as unknown as { __keyAtStart: string | null }).__keyAtStart)).toBeNull();
  await page.waitForFunction(() => !!(window as unknown as { __vera?: unknown }).__vera);
  await page.locator('h1.pg-t').waitFor();
  await state.setupPrototype?.(page);
  await settle(page, width, height);
  return page;
}

/** Images decoded, fonts ready, transitions finished and the pointer parked away from every control. */
async function settle(page: Page, width: number, height: number) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => [...document.images].every((i) => i.complete));
  await page.waitForTimeout(400);
  await page.mouse.move(width - 2, height - 2);
}

async function openApp(width: number, height: number, state: ParityState): Promise<Page> {
  const ctx = await browser.newContext({ viewport: { width, height } });
  contexts.push(ctx);
  const page = await ctx.newPage();
  await installSessionRoutes(page);
  await installCaseRoutes(page);
  await page.goto(`http://127.0.0.1:${APP_PORT}${state.appPath}`, { waitUntil: 'load' });
  // The role selector renders once the session has loaded (a skeleton stands in until then).
  await page.getByRole('button', { name: /viewing as/i }).waitFor();
  await state.setupApp?.(page);
  await settle(page, width, height);
  return page;
}

for (const state of STATES) {
  for (const vp of VIEWPORTS.filter((v) => state.widths.includes(v.width))) {
    test(`${state.name} matches prototype at ${vp.width}px`, async () => {
      const proto = await openPrototype(vp.width, vp.height, state);
      const app = await openApp(vp.width, vp.height, state);
      // Route screenshot first: it must show the real layout, not a relocated element.
      if (SHOTS && (vp.width === 1440 || vp.width === 390)) {
        mkdirSync(SHOTS, { recursive: true });
        await app.screenshot({ path: `${SHOTS}/app-route-${vp.width}x${vp.height}.png` });
      }
      const result = await compareState(proto, app, state);
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true });
        const tag = `${state.name.replace('/', '-')}-${vp.width}`;
        if (result.pngs.prototype) writeFileSync(`${SHOTS}/${tag}-prototype.png`, result.pngs.prototype);
        if (result.pngs.app) writeFileSync(`${SHOTS}/${tag}-app.png`, result.pngs.app);
      }
      expect(result.differences).toEqual([]);
      if (state.hiddenWidths?.includes(vp.width)) {
        // Hidden in both (prototype @media max-width:760px).
        await expect(proto.locator(state.prototypeSelector)).toBeHidden();
        await expect(app.locator(state.appSelector)).toBeHidden();
      } else {
        await expect(app.locator(state.appSelector)).toBeVisible();
      }
    });
  }
}

test('shell/mobile-closed: the sidebar is off-canvas in both pages, with the same box', async () => {
  const state = STATES.find((s) => s.name === 'shell/mobile-closed (top bar)')!;
  const vp = VIEWPORTS[3];
  const proto = await openPrototype(vp.width, vp.height, state);
  const app = await openApp(vp.width, vp.height, state);
  const box = (page: Page, selector: string) => page.locator(selector).first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  });
  const p = await box(proto, '.side');
  const a = await box(app, '[data-parity="side"]');
  expect(p.x + p.width).toBeLessThanOrEqual(0);
  expect(a.x + a.width).toBeLessThanOrEqual(0);
  for (const k of ['x', 'y', 'width', 'height'] as const) expect(Math.abs(p[k] - a[k])).toBeLessThanOrEqual(0.5);
  expect(a.width).toBe(248);
});

test('self-test: changing a token value makes the comparison fail', async () => {
  const state = STATES[0];
  const vp = VIEWPORTS[0];
  const proto = await openPrototype(vp.width, vp.height, state);
  const app = await openApp(vp.width, vp.height, state);
  expect((await compareState(proto, app, state)).ok).toBe(true);
  await app.addStyleTag({ content: ':root{--mute:#ff0000}' });
  const mutated = await compareState(proto, app, state);
  expect(mutated.ok).toBe(false);
  expect(mutated.differences.some((d) => d.startsWith('color:'))).toBe(true);
  expect(mutated.diffPixels).toBeGreaterThan(0);
});

test('self-test: shifting the pill makes the comparison fail on position', async () => {
  const state = STATES[0];
  const vp = VIEWPORTS[0];
  const proto = await openPrototype(vp.width, vp.height, state);
  const app = await openApp(vp.width, vp.height, state);
  expect((await compareState(proto, app, state)).ok).toBe(true);
  await app.addStyleTag({ content: '[data-parity="envpill"]{margin-top:6px}' });
  const mutated = await compareState(proto, app, state);
  expect(mutated.ok).toBe(false);
  expect(mutated.differences.some((d) => d.startsWith('position y:'))).toBe(true);
});

test('self-test: a faded parent makes the comparison fail on effective opacity', async () => {
  const state = STATES[0];
  const vp = VIEWPORTS[0];
  const proto = await openPrototype(vp.width, vp.height, state);
  const app = await openApp(vp.width, vp.height, state);
  await app.evaluate(() => {
    (document.querySelector('[data-parity="envpill"]')!.parentElement as HTMLElement).style.opacity = '.5';
  });
  const mutated = await compareState(proto, app, state);
  expect(mutated.ok).toBe(false);
  expect(mutated.differences.some((d) => d.startsWith('effective opacity:'))).toBe(true);
});
