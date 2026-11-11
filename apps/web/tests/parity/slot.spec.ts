import { chromium, expect, test, type Browser } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { launchOptions } from './browser';
import { SLOT_STATE_NAMES, slotMarkup } from '../support/slot-markup';

// "Status changes in StatusSlot cause no layout shift", measured for real: the built design-system CSS
// (tokens.css + StatusSlot.module.css, whose class names are plain) is loaded into a blank page with the
// exact markup <StatusSlot/> renders (tests/unit/status-slot.test.tsx proves the component renders that
// markup). Text sits on both sides of the slot, inline and in a flex row; for every state, and for every
// transition between states, the slot is 20x20 and nothing around it moves by a single pixel.
// No dev-only route is involved.

const src = path.resolve(__dirname, '../../src/design-system');
const css = ['tokens.css', 'primitives/StatusSlot.module.css'].map((f) => readFileSync(path.join(src, f), 'utf8')).join('\n');

const page = (state: string) => `<!doctype html><style>${css}
body{margin:20px;font:14px/1.5 sans-serif}.row{display:flex;align-items:center;gap:8px}</style>
<p id="inline">before <span id="inlineWrap">${slotMarkup(state as never)}</span> after</p>
<div class="row" id="flex"><b id="lead">Lead</b>${slotMarkup(state as never)}<b id="tail">Tail</b></div>
<p id="below">below</p>`;

let browser: Browser;
test.beforeAll(async () => {
  browser = await chromium.launch(launchOptions);
});
test.afterAll(async () => {
  await browser.close();
});

type Box = { x: number; y: number; width: number; height: number };
const measure = (p: import('@playwright/test').Page) =>
  p.evaluate(() => {
    const box = (el: Element): Box => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    };
    const slots = [...document.querySelectorAll('.slot')];
    return {
      slots: slots.map(box),
      around: ['inline', 'flex', 'lead', 'tail', 'below'].map((id) => box(document.getElementById(id)!)),
    };
  });

test.describe('StatusSlot occupies a fixed 20x20 slot', () => {
  for (const state of SLOT_STATE_NAMES) {
    test(`${state}: the slot box is 20x20`, async () => {
      const p = await browser.newPage();
      await p.setContent(page(state));
      const m = await measure(p);
      for (const s of m.slots) {
        expect(s.width).toBe(20);
        expect(s.height).toBe(20);
      }
      await p.close();
    });
  }

  test('switching between every pair of states moves nothing', async () => {
    const p = await browser.newPage();
    await p.setContent(page('idle'));
    const base = await measure(p);
    for (const from of SLOT_STATE_NAMES) {
      for (const to of SLOT_STATE_NAMES) {
        await p.setContent(page(from));
        const before = await measure(p);
        // The component keeps all marks mounted and moves the `on` class: do the same here.
        await p.evaluate((next) => {
          for (const slot of document.querySelectorAll('.slot')) {
            slot.setAttribute('data-state', next);
            slot.querySelectorAll('.mark').forEach((m) => m.classList.toggle('on', m.classList.contains(next)));
          }
        }, to);
        await p.waitForTimeout(260); // past the 200ms crossfade
        const after = await measure(p);
        expect(after, `${from} -> ${to}`).toEqual(before);
        expect(after.slots.every((s) => s.width === 20 && s.height === 20)).toBe(true);
        expect(after.around).toEqual(base.around);
      }
    }
    await p.close();
  });

  test('the crossfade is real: the outgoing mark fades while the incoming one fades in', async () => {
    const p = await browser.newPage();
    await p.setContent(page('idle'));
    const opacities = await p.evaluate(async () => {
      const slot = document.querySelector('.slot')!;
      const o = (c: string) => Number(getComputedStyle(slot.querySelector(`.${c}`)!).opacity);
      const start = { idle: o('idle'), done: o('done') };
      slot.querySelector('.idle')!.classList.remove('on');
      slot.querySelector('.done')!.classList.add('on');
      await new Promise((r) => setTimeout(r, 100));
      const mid = { idle: o('idle'), done: o('done') };
      await new Promise((r) => setTimeout(r, 250));
      return { start, mid, end: { idle: o('idle'), done: o('done') } };
    });
    expect(opacities.start).toEqual({ idle: 1, done: 0 });
    expect(opacities.mid.idle).toBeGreaterThan(0);
    expect(opacities.mid.idle).toBeLessThan(1);
    expect(opacities.mid.done).toBeGreaterThan(0);
    expect(opacities.mid.done).toBeLessThan(1);
    expect(opacities.end).toEqual({ idle: 0, done: 1 });
    await p.close();
  });
});
