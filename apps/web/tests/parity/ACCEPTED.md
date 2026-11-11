# Accepted parity differences

Per docs/frontend-architecture.md section 7.4. Every entry names the reason and when it should be removed.

## Pixel threshold 0.05 (pixelmatch YIQ delta)

`PIXEL_THRESHOLD = 0.05` in `compare.ts`, with `MAX_DIFF_PIXELS = 0`.
Strict 0 leaves about 127 differing pixels on the pill's dashed border and rounded-corner antialiasing
even with identical computed styles and placement; every one is below 5% YIQ distance.
What the threshold absorbs is covered elsewhere, so it cannot hide a token change: the computed-style
comparison (`STYLE_PROPERTIES`: font, colour, background, border style/width/colour, radii, padding,
font-variant-numeric, font-feature-settings, position), the effective ancestor opacity, and the
size and top-edge (`y`) comparison all use exact equality (position within 0.5 px). A real colour, glyph
or geometry change fails on those regardless of the threshold. Self-tests in `pill.spec.ts` prove it.

## `shell/environment-pill`: position (F1)

With the role selector and Reset button in the top bar, the pill's x and y are asserted against the page root
(`position` with `axes: ['x', 'y']`, tolerance 0.5 px) and the state is screenshotted in place (the F0 `isolate`
flag is gone). Hidden in both pages at 390 px.

## Shell states (F1)

`shell/*` states are compared as regions: top bar (`.top` vs `[data-parity="top"]`), sidebar (`.side` vs
`[data-parity="side"]`, where the prototype shows one) and, for `shell/role-menu-open`, the menu (`.rsel-m` vs
`[role="menu"]`). Each asserts x and y against the page root. The main content area is never compared: the
prototype's differs from an empty app page. The app route is `/`: the sidebar treats the app root as the Cases queue's landing
route (as the prototype's default screen is Cases), so Cases is active, as in the prototype.

The app is driven through its UI (click, keyboard); the prototype through `window.__vera`. The role views map to the
prototype's `analyst`, `cardholder`, `reviewer`. The cardholder and reviewer views have no sidebar in the prototype
(it is `showSide: view === 'analyst'`), so only their top bars are compared.

- `shell/role-menu-open (role menu)`: the menu's rounded corners show what lies behind them (the prototype's cards
  vs the empty app canvas, 11 pixels), so the prototype setup hides its main content (`.frame-c > :not(header)`
  gets `visibility:hidden`) for this region only. Remove when F2 renders the queue in the app.
- `shell/role-reviewer`: the prototype also draws the `Vera` rail toggle (`.vera-b`, `showRail`) in the reviewer
  top bar below 1280 px. The Vera rail is F9's, and a toggle without a rail would be a dead control, so the
  prototype setup hides `.vera-b` for this state. Remove the override when F9 lands.
- `shell/mobile-closed`: the closed drawer is off-canvas, so its pixels cannot be screenshotted. A dedicated test
  compares both pages' sidebar boxes (x, y, 248 x height) instead.
- The prototype's unseen-update dot (`.ndot`, "Another role has an update") is demo bookkeeping with no backend
  source and is not ported; it does not appear in any compared state.

## Differences kept on purpose (not parity regressions)

- **Disabled opacity is 45%** (`--opacity-disabled`, Handoff §9.4); the prototype CSS has `.4`. No parity state
  renders a disabled button.
- **`Button` `sm` is 34px high**, not Handoff §9.4's 30px: the prototype's cascade applies `.btn.sm{min-height:34px}`
  (Main.dc.html:873, after the 30px rule). The Reset button is `btn sm ghost`, so 34px is what the top bar shows.
  Both values are tokens (`--control-h-sm`, `--control-h-sm-proto`).
- **`FilterTabs`** copies the prototype's `.fb.on` (white bordered chip). Handoff §9.4 says ink text with a 2px
  underline. The primitive follows the prototype; F2 decides when the queue state is compared.
- **Collapsed rail on mobile.** The prototype's `.side.col` also shrinks the mobile drawer to 64px (a side effect of
  rule order). The collapse styles apply above 760px only, and the splitter is hidden at 760px and below
  (Handoff §8.1 "splitters hidden"). A closed off-canvas drawer is `inert`.
- **Tooltip** (collapsed rail, Handoff §8.1) replaces the prototype's `title`; the tooltip is not rendered at rest.
- **Reviewer description** in the role menu is the prototype's demo copy, verbatim (including the person's name).
- **Automations link** goes to `/automations/workflows`; the prototype remembers the last automations screen.

## Primitives without a parity state

`Tooltip`, `Skeleton` and `Banner` have no prototype reference; they are built from tokens and Handoff
§8.1/§8.3/§9 and covered by unit tests (`tests/unit/primitives.test.tsx`, `tests/unit/sidebar.test.tsx`), not parity
states. `StatusSlot` is measured in a real browser by `tests/parity/slot.spec.ts` (fixed 20x20 box, no layout shift
across every state pair) rather than compared with the prototype pixel by pixel.

## Fonts

The prototype's Google Fonts Inter request is served from the app's self-hosted woff2 files
(`pill.spec.ts`), so Inter renders identically on both sides. No accepted difference.
