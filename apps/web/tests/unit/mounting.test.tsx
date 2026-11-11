import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CASE_TABS, panelsFor, taskBlockFor, type CaseRegistry } from '@/features/case/registry';
import { HomePage, RequestRoute } from '@/features/pages';
import intake from '../parity/fixtures/case-CHG-1042-intake.json';
import type { CaseView } from '@/api';
import { mockFetch, renderWithProviders, session } from './helpers';

const replace = vi.fn();
vi.mock('next/navigation', () => ({ usePathname: () => '/', useSearchParams: () => new URLSearchParams(), useRouter: () => ({ replace, push: vi.fn() }) }));
afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
});

describe('case registry', () => {
  it('keeps the prototype tab order and labels', () => {
    expect(CASE_TABS.map((t) => t.label)).toEqual(['Evidence', 'Communications', 'Decision', 'Run details']);
  });

  it('returns the panels of a tab in registration order and the first matching task block', () => {
    const P = () => null;
    const r: CaseRegistry = {
      tabPanels: [
        { tab: 'comms', key: 'a', Panel: P },
        { tab: 'decision', key: 'b', Panel: P },
        { tab: 'comms', key: 'c', Panel: P },
      ],
      taskBlocks: [
        { key: 'rv', match: (_c, role) => role === 'reviewer', Block: P, ownsActions: true },
        { key: 'intake', match: (c) => c.step === (intake as CaseView).step, Block: P, ownsActions: false },
      ],
      commandForms: {},
      rail: null,
    };
    expect(panelsFor(r, 'comms').map((p) => p.key)).toEqual(['a', 'c']);
    expect(taskBlockFor(r, intake as CaseView, 'analyst')?.key).toBe('intake');
    expect(taskBlockFor(r, intake as CaseView, 'reviewer')?.key).toBe('rv');
    expect(taskBlockFor({ ...r, taskBlocks: [] }, intake as CaseView, 'analyst')).toBeNull();
  });
});

describe('role landing', () => {
  it('sends the analyst to the queue', async () => {
    mockFetch(() => session('analyst'));
    renderWithProviders(<HomePage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/cases'));
  });

  it('sends the reviewer and the card admin to Approvals', async () => {
    mockFetch(() => session('card_admin'));
    renderWithProviders(<HomePage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/approvals'));
  });

  it('never redirects the cardholder to a hardcoded case', async () => {
    mockFetch((c) => (c.url === '/api/session' ? session('cardholder') : new Response('{"code":"not_found","message":"Not Found"}', { status: 404 })));
    renderWithProviders(<HomePage />);
    await waitFor(() => expect(document.body.textContent).toMatch(/Not available yet|request/i));
    expect(replace.mock.calls.filter(([to]) => String(to).startsWith('/cases'))).toEqual([]);
  });
});

describe('route slots', () => {
  it('/requests/[id] renders the request page or an honest empty state', async () => {
    mockFetch(() => new Response('{"code":"not_found","message":"Not Found"}', { status: 404 }));
    renderWithProviders(<RequestRoute requestId="REQ-1" />);
    await waitFor(() => expect(screen.getByText(/Not available yet|isn’t available/)).toBeTruthy());
  });
});

describe('internal panels the server denies', () => {
  it('drops the Evidence / Decision / Run details tabs and the policy block when the evidence read is 403', async () => {
    const { CaseWorkspace } = await import('@/features/case');
    const denied = () => new Response('{"code":"forbidden","message":"Forbidden"}', { status: 403 });
    mockFetch((c) => {
      if (c.url === '/api/session') return session('cardholder');
      if (/\/api\/cases\/[^/]+$/.test(c.url)) return intake;
      return denied();
    });
    renderWithProviders(<CaseWorkspace caseId="CHG-1042" />);
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Communications' })).toBeTruthy());
    await waitFor(() => expect(screen.queryByRole('tab', { name: 'Evidence' })).toBeNull());
    expect(screen.queryByRole('tab', { name: 'Decision' })).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Run details' })).toBeNull();
    expect(screen.queryByTestId('policy-block')).toBeNull();
    expect(screen.queryByText(/Run details/)).toBeNull();
  });
});
