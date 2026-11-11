import type { Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';

// Network-boundary fixture for the parity suite: the backend is not part of this harness, so the
// session endpoints are fulfilled here with the real response shape (services/api/vera_api/app.py SessionOut).
// This is test code only; the product has no hardcoded session.

const USERS: Record<string, { id: string; name: string }> = {
  analyst: { id: 'u-analyst', name: 'Alex Rivera' },
  cardholder: { id: 'u-cardholder', name: 'Sam Lee' },
  reviewer: { id: 'u-reviewer', name: 'Dana Okafor' },
};

export type SessionFixtureOptions = { role?: string; environment?: string };

export async function installSessionRoutes(page: Page, { role = 'analyst', environment = 'synthetic' }: SessionFixtureOptions = {}) {
  let active = role;
  const body = () => ({ user: USERS[active] ?? USERS.analyst, active_role: active, roles: [active], environment });
  await page.route(/\/api\/session\/role$/, async (route) => {
    const req = route.request();
    if (req.method() !== 'POST') return route.fulfill({ status: 405, json: { code: 'method_not_allowed', message: 'POST only' } });
    active = (JSON.parse(req.postData() ?? '{}') as { role: string }).role;
    return route.fulfill({ json: body() });
  });
  await page.route(/\/api\/session$/, (route) => route.fulfill({ json: body() }));
  await page.route(/\/api\/demo\/reset$/, (route) => route.fulfill({ json: { ok: true } }));
}

// Case API bodies captured from the REAL backend (tests/parity/fixtures/README.md); GETs only.

const FIX = path.join(__dirname, 'fixtures');
const json = (f: string) => JSON.parse(readFileSync(path.join(FIX, f), 'utf8')) as unknown;

export async function installCaseRoutes(page: Page) {
  const table: [RegExp, string][] = [
    [/\/api\/cases$/, 'cases.json'],
    [/\/api\/cases\/summary$/, 'summary.json'],
    [/\/api\/cases\/filter-counts$/, 'filter-counts.json'],
    [/\/api\/cases\/CHG-1042$/, 'case-CHG-1042-intake.json'],
    [/\/api\/cases\/CHG-1042\/evidence$/, 'evidence-CHG-1042-intake.json'],
    [/\/api\/cases\/CHG-1042\/runs$/, 'runs-CHG-1042-intake.json'],
    [/\/api\/cases\/CHG-1042\/activity$/, 'activity-CHG-1042-intake.json'],
    [/\/api\/users\?assignable=true$/, 'users.json'],
  ];
  for (const [re, file] of table) await page.route(re, (route) => route.fulfill({ json: json(file) }));
}
