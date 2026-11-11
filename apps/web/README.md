# Vera web (Next.js port)

Architecture and layer rules: `../../docs/frontend-architecture.md`. The prototype in `prototype/` is a read-only reference and is never imported from `src/`.

## Commands (run in `apps/web`)

| Command | What it does |
|---|---|
| `npm install` | Install dependencies (lockfile is committed). |
| `npm run dev` | Dev server on :3000. `/api/*` is rewritten to `VERA_API_URL` (default `http://127.0.0.1:8000`). |
| `npm run typecheck` | `tsc --noEmit`, strict. |
| `npm run lint` | ESLint, including the import-boundary rules (`no-restricted-imports` per layer, see `eslint.config.mjs`). |
| `npm test` | Vitest: tokens vs Handoff §9, the boundary rules run against fixture source, and component tests (jsdom, `tests/unit/**/*.test.tsx`). |
| `npm run build` | Runs `npm run lint` first, then `next build`; a boundary violation fails the build. |
| `npm run test:parity` | Playwright parity harness. Needs `npm run build` first. Starts the built app (`VERA_APP_PORT`, default 3100) and serves the prototype with `python3 -m http.server` (`VERA_PROTOTYPE_PORT`, default 3101). |
| `npm run gen:api` | Regenerates `src/api/schema.d.ts` from `${VERA_API_URL}/openapi.json` with openapi-typescript. The backend is not available yet, so `schema.d.ts` is a placeholder. |

## Parity harness (`tests/parity`)

- `states.ts` is the manifest: state name, prototype selector, app selector, route, widths, optional `setupPrototype` (uses `window.__vera`) and `setupApp` (drives the app through its UI). `shell/*` states are compared as regions (top bar, sidebar, role menu) with an x/y position assertion against the page root.
- `fixtures.ts` fulfils `/api/session`, `/api/session/role` and `/api/demo/reset` with `page.route` (the backend is not part of the harness).
- Ports: `VERA_APP_PORT` (default 3100) and `VERA_PROTOTYPE_PORT` (default 3101), read in `playwright.config.ts`, so checkouts can run side by side.
- `slot.spec.ts` measures `StatusSlot` for layout shift in a real browser (no dev-only route).
- `compare.ts` compares computed styles and element screenshots. Thresholds live there (`MAX_DIFF_PIXELS`, `PIXEL_THRESHOLD`).
- `pill.spec.ts` runs every state at 1440, 1200, 900 and 390 px in fresh browser contexts, plus a self-test that overrides `--mute` and expects a mismatch.
- Set `VERA_PARITY_SHOTS=<dir>` to save the element crops and route screenshots.
- Browser: system Chrome at `$VERA_CHROME_PATH` (default `/usr/bin/google-chrome`) when it exists, otherwise Playwright's bundled chromium (`npx playwright install chromium` in CI).

## Notes

- Fonts: Inter variable is self-hosted from `@fontsource-variable/inter` and aliased to the family name `Inter` in `src/design-system/base.css` (weights 400-650). No Google Fonts requests.
- The root layout renders `AppProviders` (TanStack Query) and `AppShell` from `src/features/shell`; `src/app` imports features only.
- The generated API schema is still a placeholder: the session types in `src/api/session.ts` are hand-written until F2.
- Unit tests mock `fetch` at the network boundary; they never need the backend.
