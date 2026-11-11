import type { Page } from '@playwright/test';
import pixelmatch from 'pixelmatch';
import { PNG } from 'pngjs';
import type { ParityState } from './states';

/**
 * Maximum number of differing pixels allowed in an element screenshot.
 * Single source of truth. 0 for the text-only pill; loosen only if antialiasing forces it.
 */
export const MAX_DIFF_PIXELS = 0;

/**
 * Per-pixel colour tolerance (pixelmatch YIQ delta, 0-1). Strict 0 leaves ~127 pixels differing,
 * all on the dashed-border/corner antialiasing and <5% in YIQ distance, even with identical
 * computed styles and identical placement. 0.05 absorbs exactly that (0 differing pixels) while
 * any real colour, glyph or geometry change still fails. This is the only loosening.
 */
export const PIXEL_THRESHOLD = 0.05;

/** Pixels of top-edge / anchor-relative position drift tolerated (sub-pixel layout rounding only). */
export const POSITION_TOLERANCE = 0.5;

export const STYLE_PROPERTIES = [
  'display',
  'fontFamily',
  'fontSize',
  'fontWeight',
  'fontStyle',
  'lineHeight',
  'letterSpacing',
  'textTransform',
  'whiteSpace',
  'color',
  'backgroundColor',
  'borderTopStyle',
  'borderRightStyle',
  'borderBottomStyle',
  'borderLeftStyle',
  'borderTopWidth',
  'borderRightWidth',
  'borderBottomWidth',
  'borderLeftWidth',
  'borderTopColor',
  'borderRightColor',
  'borderBottomColor',
  'borderLeftColor',
  'borderTopLeftRadius',
  'borderTopRightRadius',
  'borderBottomRightRadius',
  'borderBottomLeftRadius',
  'paddingTop',
  'paddingRight',
  'paddingBottom',
  'paddingLeft',
  'fontVariantNumeric',
  'fontFeatureSettings',
  'position',
] as const;

type Box = { x: number; y: number; width: number; height: number };

type Snapshot = {
  visible: boolean;
  styles: Record<string, string>;
  /** Product of opacity over the element and all its ancestors. */
  effectiveOpacity: number;
  /** Bounding box in document coordinates (scroll-independent). */
  box: Box;
  /** Bounding box of the anchor element, when the state asserts position. */
  anchor: Box | null;
  png: Buffer | null;
};

async function snapshot(page: Page, selector: string, anchorSelector: string | undefined, isolate: boolean): Promise<Snapshot> {
  const el = page.locator(selector).first();
  await el.waitFor({ state: 'attached' });
  const { styles, box, effectiveOpacity } = await el.evaluate((node, props) => {
    const cs = getComputedStyle(node);
    const r = node.getBoundingClientRect();
    const out: Record<string, string> = {};
    for (const p of props) out[p] = (cs as unknown as Record<string, string>)[p];
    let opacity = 1;
    for (let n: Element | null = node; n; n = n.parentElement) opacity *= parseFloat(getComputedStyle(n).opacity);
    return {
      styles: out,
      effectiveOpacity: opacity,
      box: { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height },
    };
  }, [...STYLE_PROPERTIES]);
  let anchor: Box | null = null;
  if (anchorSelector) {
    anchor = await page.locator(anchorSelector).first().evaluate((node) => {
      const r = node.getBoundingClientRect();
      return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height };
    });
  }
  const visible = styles.display !== 'none';
  // Default: screenshot the element in place, in its real context.
  if (visible && isolate) {
    // Opt-in (state.isolate): pin the element to a fixed, whole-pixel spot on an opaque white
    // background so neighbours cannot change rasterisation. This hides context regressions, so
    // layout/opacity/position are read above, before the element is moved. The move is undone
    // afterwards so compareState can be called repeatedly on the same page.
    await el.evaluate((node) => {
      const h = node as HTMLElement;
      const w = window as unknown as { __parityRestore?: () => void };
      const parent = h.parentNode!;
      const next = h.nextSibling;
      const style = h.getAttribute('style');
      w.__parityRestore = () => {
        parent.insertBefore(h, next);
        if (style === null) h.removeAttribute('style');
        else h.setAttribute('style', style);
      };
      document.body.appendChild(h);
      h.style.cssText += ';position:fixed;left:8px;top:8px;margin:0;z-index:2147483647;background:#fff';
    });
  }
  let png: Buffer | null = null;
  try {
    png = visible ? await el.screenshot({ animations: 'disabled' }) : null;
  } finally {
    // Always put the element back, even when the screenshot throws, so the page stays comparable.
    if (visible && isolate) {
      await page.evaluate(() => (window as unknown as { __parityRestore?: () => void }).__parityRestore?.());
    }
  }
  return { visible, styles, effectiveOpacity, box, anchor, png };
}

export type Comparison = {
  ok: boolean;
  differences: string[];
  diffPixels: number;
  sizes: { prototype: Box; app: Box };
  pngs: { prototype: Buffer | null; app: Buffer | null };
};

/** Compare the same region of the prototype and the app at the pages' current viewport. */
export async function compareState(protoPage: Page, appPage: Page, state: ParityState): Promise<Comparison> {
  const isolate = state.isolate === true;
  const pos = state.position;
  const p = await snapshot(protoPage, state.prototypeSelector, pos?.prototypeAnchor, isolate);
  const a = await snapshot(appPage, state.appSelector, pos?.appAnchor, isolate);
  const differences: string[] = [];
  let diffPixels = 0;

  if (p.visible !== a.visible) {
    differences.push(`visibility: prototype=${p.visible} app=${a.visible}`);
  } else if (p.visible && a.visible) {
    for (const prop of STYLE_PROPERTIES) {
      if (p.styles[prop] !== a.styles[prop]) {
        differences.push(`${prop}: prototype=${p.styles[prop]} app=${a.styles[prop]}`);
      }
    }
    if (Math.abs(p.effectiveOpacity - a.effectiveOpacity) > 0.001) {
      differences.push(`effective opacity: prototype=${p.effectiveOpacity} app=${a.effectiveOpacity}`);
    }
    if (p.box.width !== a.box.width || p.box.height !== a.box.height) {
      differences.push(`size: prototype=${p.box.width}x${p.box.height} app=${a.box.width}x${a.box.height}`);
    }
    // Top edge is always compared (document coordinates); x only when the state opts in below.
    if (Math.abs(p.box.y - a.box.y) > POSITION_TOLERANCE) {
      differences.push(`position y: prototype=${p.box.y} app=${a.box.y}`);
    }
    if (pos && p.anchor && a.anchor) {
      for (const axis of pos.axes) {
        const dp = p.box[axis] - p.anchor[axis];
        const da = a.box[axis] - a.anchor[axis];
        if (Math.abs(dp - da) > (pos.tolerance ?? POSITION_TOLERANCE)) {
          differences.push(`position ${axis} relative to anchor: prototype=${dp} app=${da}`);
        }
      }
    }
    const imgP = PNG.sync.read(p.png!);
    const imgA = PNG.sync.read(a.png!);
    if (imgP.width !== imgA.width || imgP.height !== imgA.height) {
      differences.push(`screenshot size: prototype=${imgP.width}x${imgP.height} app=${imgA.width}x${imgA.height}`);
      diffPixels = Math.max(imgP.width * imgP.height, imgA.width * imgA.height);
    } else {
      diffPixels = pixelmatch(imgP.data, imgA.data, null, imgP.width, imgP.height, { threshold: PIXEL_THRESHOLD });
      if (diffPixels > MAX_DIFF_PIXELS) differences.push(`pixels: ${diffPixels} differ (max ${MAX_DIFF_PIXELS})`);
    }
  }
  return {
    ok: differences.length === 0,
    differences,
    diffPixels,
    sizes: { prototype: p.box, app: a.box },
    pngs: { prototype: p.png, app: a.png },
  };
}
