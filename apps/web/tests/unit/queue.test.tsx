import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CasesQueue } from '@/features/cases';
import { summaryTiles } from '@/features/cases/summary';
import cases from '../parity/fixtures/cases.json';
import summary from '../parity/fixtures/summary.json';
import sessionBody from '../parity/fixtures/session-analyst.json';
import { mockFetch, renderWithProviders } from './helpers';

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({
  useSearchParams: () => nav.params,
  usePathname: () => '/cases',
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
}));

beforeEach(() => {
  nav.params = new URLSearchParams();
  nav.replace.mockReset();
  mockFetch((c) => (c.url === '/api/cases' ? cases : c.url === '/api/cases/summary' ? summary : sessionBody));
});
afterEach(() => vi.unstubAllGlobals());

describe('CasesQueue', () => {
  it('renders five D1 columns with the broad state in the case subtitle', async () => {
    renderWithProviders(<CasesQueue />);
    await screen.findByText('CHG-1042 · Northstar Equipment');
    const heads = screen.getAllByRole('columnheader').map((h) => h.textContent);
    expect(heads).toEqual(['Case', 'What’s blocking it', 'Next action', 'Owner', 'Due']);
    expect(screen.getByText('New report', { exact: false }).textContent).toContain('$2,840');
  });

  it('only openable (live) rows link to the workspace; display rows are plain text', async () => {
    renderWithProviders(<CasesQueue />);
    const link = await screen.findByRole('link', { name: 'CHG-1042 · Northstar Equipment' });
    expect(link.getAttribute('href')).toBe('/cases/CHG-1042');
    const display = screen.getByText('CHG-1029 · Brightline Logistics');
    expect(display.tagName).toBe('SPAN');
    expect(display.closest('a')).toBeNull();
    expect(display.closest('tr')!.getAttribute('data-openable')).toBe('false');
    expect(within(display.closest('tr')!).queryByRole('link')).toBeNull();
    expect(within(display.closest('tr')!).queryByRole('button')).toBeNull();
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });

  it('filter is read from the URL and clicking a filter writes the URL without any POST', async () => {
    nav.params = new URLSearchParams('filter=ch');
    renderWithProviders(<CasesQueue />);
    await screen.findByText('CHG-1029 · Brightline Logistics');
    expect(screen.queryByText('CHG-1042 · Northstar Equipment')).toBeNull();
    await userEvent.setup().click(screen.getByRole('button', { name: /Overdue/ }));
    expect(nav.replace).toHaveBeenCalledWith('/cases?filter=over', { scroll: false });
    const calls = (globalThis.fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls;
    expect(calls.every(([, init]) => (init?.method ?? 'GET') === 'GET')).toBe(true);
  });

  it('sort Amount orders by amount from the URL', async () => {
    nav.params = new URLSearchParams('sort=amount');
    renderWithProviders(<CasesQueue />);
    await screen.findByText('CHG-1042 · Northstar Equipment');
    const first = screen.getAllByRole('row')[1];
    expect(first.textContent).toContain('CHG-1036');
  });
});

describe('summaryTiles', () => {
  it('reads the current (old) shape without inventing metrics', () => {
    const t = summaryTiles(summary);
    expect(t.map((x) => [x.label, x.amountCents, x.count, x.primary])).toEqual([
      ['Open exposure', 726000, 6, true],
      ['Due today', 566000, 3, false],
      ['Overdue', 118000, 1, false],
      ['Temporary credit', 396000, 1, false],
    ]);
  });

  it('reads the new metric shape: gross primary, net beside it, basis and definition passed through', () => {
    const m = (amount_cents: number, count: number, basis: string) => ({ amount_cents, currency: 'USD', count, basis, definition: `${basis} def` });
    const t = summaryTiles({ net_exposure: m(330000, 5, 'net'), gross_exposure: m(726000, 6, 'gross'), overdue: m(118000, 1, 'gross') });
    expect(t.map((x) => x.key)).toEqual(['gross_exposure', 'net_exposure', 'overdue']);
    expect(t[0]).toMatchObject({ primary: true, amountCents: 726000, basis: 'gross', definition: 'gross def' });
    expect(t[1].primary).toBe(false);
  });
});
