import type { Page } from '@playwright/test';
import type { CaseFixtureSet } from './fixtures';

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
  /** Widths at which the region is hidden in both pages (compared as visibility, not pixels). */
  hiddenWidths?: readonly number[];
  /** Puts the prototype into this state through window.__vera (optional). */
  setupPrototype?: (page: Page) => Promise<void>;
  /** Captured CHG-1042 state the app's case reads return (default `intake`). */
  fixtures?: CaseFixtureSet;
  /**
   * Fixed browser clock for the app page (local time), for regions that print a time the prototype prints from its
   * own simulated clock (e.g. the queue's "Updated 9:08 AM").
   */
  appClock?: () => Date;
  /** Puts the app into the same state through the UI (runs after the shell has loaded its session). */
  setupApp?: (page: Page) => Promise<void>;
};

/** Offset of a region from the page root must match on both axes (document coordinates). */
const FROM_PAGE_ROOT = { prototypeAnchor: 'body', appAnchor: 'body', axes: ['x', 'y'] } as const;

const ALL = VIEWPORTS.map((v) => v.width);
const WIDE = ALL.filter((w) => w > 760);
const MOBILE = [390];

// Prototype drivers (window.__vera, Main.dc.html).
const proto = {
  navWidth: (w: number) => async (page: Page) => {
    await page.evaluate((n) => {
      const v = (window as unknown as { __vera: { lay(): { navW: number }; laySave(b: boolean): void } }).__vera;
      v.lay().navW = n;
      v.laySave(true);
    }, w);
  },
  upd: (field: string) => async (page: Page) => {
    await page.evaluate((f) => {
      const v = (window as unknown as { __vera: { upd(fn: (d: Record<string, unknown>) => void): void } }).__vera;
      v.upd((d) => {
        d[f] = true;
      });
    }, field);
  },
  view: (view: string) => async (page: Page) => {
    await page.evaluate((x) => (window as unknown as { __vera: { setView(v: string): void } }).__vera.setView(x), view);
  },
  openCase: async (page: Page) => {
    await page.evaluate(() => (window as unknown as { __vera: { openCase(): void } }).__vera.openCase());
    await page.locator('#task').waitFor();
  },
  // The reviewer view also shows the Vera rail toggle below 1280px; the rail is F9's.
  hideVeraToggle: async (page: Page) => {
    await page.addStyleTag({ content: '.vera-b{display:none !important}' });
  },
};

// App drivers: the same states reached through the UI.
const app = {
  roleMenu: async (page: Page) => {
    await page.getByRole('button', { name: /viewing as/i }).click();
    await page.getByRole('menu', { name: 'Demo role' }).waitFor();
  },
  role: (name: RegExp, then: RegExp) => async (page: Page) => {
    await app.roleMenu(page);
    await page.getByRole('menuitemradio', { name }).click();
    await page.getByRole('button', { name: then }).waitFor();
  },
  collapse: async (page: Page) => {
    await page.getByRole('button', { name: 'Collapse navigation' }).click();
    await page.getByRole('button', { name: 'Expand navigation' }).waitFor();
  },
  // Keyboard-driven (the splitter's own contract), then blurred so no focus ring is in the screenshot.
  width320: async (page: Page) => {
    await page.getByRole('separator', { name: 'Resize navigation' }).focus();
    await page.keyboard.press('End');
    await page.getByRole('separator', { name: 'Resize navigation' }).evaluate((el) => (el as HTMLElement).blur());
  },
  openDrawer: async (page: Page) => {
    await page.getByRole('button', { name: 'Open navigation' }).click();
    await page.getByRole('dialog', { name: 'Product navigation' }).waitFor();
  },
};

type ShellOptions = {
  name: string;
  widths: readonly number[];
  /** Widths at which the sidebar region is compared (absent: not compared, e.g. the prototype has no sidebar for that role). */
  sidebarWidths?: readonly number[];
  menu?: boolean;
  setupPrototype?: ParityState['setupPrototype'];
  setupApp?: ParityState['setupApp'];
};

/** A shell state is compared as regions: top bar, sidebar (when the prototype shows one) and the open role menu. */
function shell(o: ShellOptions): ParityState[] {
  // The app root counts as the Cases queue's landing route in the sidebar (the prototype's default screen).
  const common = { appPath: '/', position: FROM_PAGE_ROOT, setupPrototype: o.setupPrototype, setupApp: o.setupApp };
  const out: ParityState[] = [
    { ...common, name: `${o.name} (top bar)`, prototypeSelector: '.top', appSelector: '[data-parity="top"]', widths: o.widths },
  ];
  if (o.sidebarWidths) {
    out.push({ ...common, name: `${o.name} (sidebar)`, prototypeSelector: '.side', appSelector: '[data-parity="side"]', widths: o.sidebarWidths });
  }
  if (o.menu) {
    // The queue now renders behind the menu in both pages, so the F1 hideMain override is gone.
    out.push({ ...common, name: `${o.name} (role menu)`, prototypeSelector: '.rsel-m', appSelector: '[role="menu"]', widths: o.widths });
  }
  return out;
}

export const STATES: ParityState[] = [
  {
    name: 'shell/environment-pill',
    prototypeSelector: '.envpill',
    appSelector: '[data-parity="envpill"]',
    appPath: '/',
    widths: ALL,
    hiddenWidths: MOBILE,
    // The role selector now sits beside the pill, so its position is asserted against the page root.
    position: FROM_PAGE_ROOT,
  },
  ...shell({ name: 'shell/default', widths: ALL, sidebarWidths: WIDE }),
  ...shell({ name: 'shell/sidebar-320', widths: WIDE, sidebarWidths: WIDE, setupPrototype: proto.navWidth(320), setupApp: app.width320 }),
  ...shell({ name: 'shell/sidebar-collapsed', widths: WIDE, sidebarWidths: WIDE, setupPrototype: proto.upd('navCol'), setupApp: app.collapse }),
  ...shell({ name: 'shell/role-menu-open', widths: ALL, sidebarWidths: WIDE, menu: true, setupPrototype: proto.upd('roleOpen'), setupApp: app.roleMenu }),
  ...shell({ name: 'shell/role-cardholder', widths: ALL, setupPrototype: proto.view('cardholder'), setupApp: app.role(/Cardholder/, /viewing as cardholder/i) }),
  ...shell({ name: 'shell/role-reviewer', widths: ALL, setupPrototype: async (page) => {
      await proto.view('reviewer')(page);
      await proto.hideVeraToggle(page);
    }, setupApp: app.role(/Reviewer · card admin/, /viewing as reviewer/i) }),
  ...shell({ name: 'shell/mobile-drawer-open', widths: MOBILE, sidebarWidths: MOBILE, setupPrototype: proto.upd('navOpen'), setupApp: app.openDrawer }),
  ...shell({ name: 'shell/mobile-closed', widths: MOBILE }),
  // F2 queue (data: real captured API bodies, tests/parity/fixtures). The server reports six exposure metrics where
  // the prototype shows four, and its rows carry no avatars, so the strip and the rows are not pixel-comparable;
  // the page head and the queue bar above the rows are, and their position proves the strip has the prototype's height.
  { name: 'cases/queue (page head)', prototypeSelector: '.pg-h', appSelector: '[data-parity="page-head"]', appPath: '/cases', widths: [1440, 1200], position: FROM_PAGE_ROOT, appClock: () => new Date(2026, 10, 10, 9, 8) },
  { name: 'cases/queue (queue bar)', prototypeSelector: '.tcard-h', appSelector: '[data-parity="queue-bar"]', appPath: '/cases', widths: [1440, 1200], position: FROM_PAGE_ROOT },
  // F3 workspace once the case is opened (fixtures captured right after open_case; prototype: openCase()). At 390 the
  // prototype's cardholder line wraps (it adds a department the API does not have), so regions below it compare at 1440.
  { name: 'case/opened (amount)', prototypeSelector: '.chd-t', appSelector: '[data-parity="case-amount"]', appPath: '/cases/CHG-1042', fixtures: 'opened', widths: [1440, 390], position: FROM_PAGE_ROOT, setupPrototype: proto.openCase },
  { name: 'case/opened (progress)', prototypeSelector: '.prog-wrap', appSelector: '[data-parity="progress"]', appPath: '/cases/CHG-1042', fixtures: 'opened', widths: [1440], position: FROM_PAGE_ROOT, setupPrototype: proto.openCase },
  { name: 'case/opened (tabs)', prototypeSelector: '.colR .tabs', appSelector: '[data-parity="case-tabs"]', appPath: '/cases/CHG-1042', fixtures: 'opened', widths: [1440], position: FROM_PAGE_ROOT, setupPrototype: proto.openCase },
  { name: 'case/opened (Vera rail head)', prototypeSelector: '.rail-h', appSelector: '[data-parity="rail-head"]', appPath: '/cases/CHG-1042', fixtures: 'opened', widths: [1440], position: FROM_PAGE_ROOT, setupPrototype: proto.openCase },
];
