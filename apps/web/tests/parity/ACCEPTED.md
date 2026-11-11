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

## `shell/environment-pill`: x position (until F1)

The pill's x is not asserted: the prototype places it at x=963.2 and the app at x=1247.7 at 1440 px,
because the app placeholder has no role selector beside it yet. Its y, size, computed styles and
effective opacity are asserted. The state runs with `isolate: true` because the fractional x offset
changes the in-place screenshot crop (170 vs 169 px). When F1 lands the role selector, remove
`isolate` and add a `position` assertion (x relative to the role selector) in `states.ts`.

## Fonts

The prototype's Google Fonts Inter request is served from the app's self-hosted woff2 files
(`pill.spec.ts`), so Inter renders identically on both sides. No accepted difference.
