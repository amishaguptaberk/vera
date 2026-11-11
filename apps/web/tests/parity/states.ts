import type { Page } from '@playwright/test';

export const VIEWPORTS = [
  { width: 1440, height: 1000 },
  { width: 1200, height: 900 },
  { width: 900, height: 900 },
  { width: 390, height: 844 },
] as const;

export type ParityState = {
  name: string;
  /** Selector of the region in the prototype. */
  prototypeSelector: string;
  /** Selector of the same region in the Next app. */
  appSelector: string;
  /** Route in the Next app. */
  appPath: string;
  widths: readonly number[];
  /** Puts the prototype into this state through window.__vera (optional). */
  /**
   * Default false: the element is screenshotted in place, so context (margins, parent opacity,
   * backgrounds) is part of the comparison. true relocates the element to a fixed spot on white
   * before the screenshot; only for regions whose surroundings legitimately differ.
   */
  isolate?: boolean;
  /**
   * Optional position assertion that later slices turn on: the offset of the region from a named
   * anchor element must match in both pages within `tolerance` px (default POSITION_TOLERANCE).
   */
  position?: {
    prototypeAnchor: string;
    appAnchor: string;
    axes: readonly ('x' | 'y')[];
    tolerance?: number;
  };
  setupPrototype?: (page: Page) => Promise<void>;
};

export const STATES: ParityState[] = [
  {
    name: 'shell/environment-pill',
    prototypeSelector: '.envpill',
    appSelector: '[data-parity="envpill"]',
    appPath: '/',
    // Isolated because the pill's x differs by a fractional amount until F1 adds the role selector
    // (prototype 963.2 vs app 1247.7 at 1440), which changes sub-pixel rasterisation and the crop
    // size (170 vs 169 px) of an in-place screenshot. y, size and effective opacity are still
    // compared before the element is moved. See ACCEPTED.md. F1 should drop this flag.
    isolate: true,
    widths: VIEWPORTS.map((v) => v.width),
  },
];
