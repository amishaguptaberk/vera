import { QueryClient } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { vi } from 'vitest';
import { AppProviders } from '@/features/shell/AppProviders';

export type Call = { method: string; url: string; body: string | undefined };

export type SessionFixture = { user: { id: string; name: string }; active_role: string; roles: string[]; environment: string };

export const session = (active_role = 'analyst', environment = 'synthetic'): SessionFixture => ({
  user: { id: 'u1', name: 'Test User' },
  active_role,
  roles: [active_role],
  environment,
});

/** Mocks fetch at the network boundary and records every request. Handlers return a JSON body (or a Response). */
export function mockFetch(handler: (call: Call) => unknown | Response) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const call: Call = { method: init?.method ?? 'GET', url: String(input), body: init?.body as string | undefined };
    calls.push(call);
    const out = handler(call);
    return out instanceof Response ? out : new Response(JSON.stringify(out), { status: 200, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fn);
  return calls;
}

/** A stateful session API: GET returns the current session, POST /api/session/role switches it. */
export function mockSessionApi(initial: SessionFixture) {
  let current = initial;
  const calls = mockFetch((c) => {
    if (c.method === 'POST' && c.url === '/api/session/role') {
      current = { ...current, active_role: (JSON.parse(c.body!) as { role: string }).role };
      return current;
    }
    if (c.method === 'GET' && c.url === '/api/session') return current;
    if (c.method === 'POST' && c.url === '/api/demo/reset') return { ok: true };
    return new Response(JSON.stringify({ code: 'not_found', message: 'nope' }), { status: 404 });
  });
  return calls;
}

export function mockMatchMedia(matches: (query: string) => boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: matches(query),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
    onchange: null,
  }));
}

export function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  return render(<AppProviders client={client}>{ui}</AppProviders>);
}
