import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ActionBar } from '@/components/case';
import { CaseWorkspace } from '@/features/case';
import intake from '../parity/fixtures/case-CHG-1042-intake.json';
import { mockFetch, renderWithProviders } from './helpers';

const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
vi.mock('next/navigation', () => ({
  useSearchParams: () => nav.params,
  usePathname: () => '/cases/CHG-1042',
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
}));
beforeEach(() => {
  nav.params = new URLSearchParams();
  nav.replace.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

import type { ActionView } from '@/api';
const actions = intake.available_actions as ActionView[];
const json = (body: unknown, status: number) => new Response(JSON.stringify(body), { status });

describe('ActionBar', () => {
  it('renders exactly available_actions in order, index 0 the only primary, blocked reasons inline', () => {
    const blocked = [{ command: 'resume_case', label: 'Resume', reason: 'r', blocked_reason: 'Resume is not available while the case is ‘New report’.' }];
    const disabled = { ...actions[2], enabled: false, blocked_reason: 'Only the owner can reassign.' };
    render(<ActionBar actions={[actions[0], actions[1], disabled]} blocked={blocked} onAction={() => {}} />);
    const btns = screen.getAllByRole('button');
    expect(btns.map((b) => b.textContent)).toEqual(['Open case', 'Hold for more information', 'Reassign']);
    expect(btns.map((b) => b.getAttribute('data-primary'))).toEqual(['true', null, null]);
    expect((btns[2] as HTMLButtonElement).disabled).toBe(true);
    const list = screen.getByRole('list', { name: 'Unavailable actions' });
    expect(list.textContent).toContain('Only the owner can reassign.');
    expect(list.textContent).toContain('Resume is not available');
  });
});

describe('CaseWorkspace', () => {
  it('tab comes from the URL and changing it writes the URL', async () => {
    nav.params = new URLSearchParams('tab=decision');
    mockFetch(() => intake);
    renderWithProviders(<CaseWorkspace caseId="CHG-1042" />);
    expect((await screen.findByTestId('policy-block')).textContent).toContain('Not evaluated yet');
    await userEvent.setup().click(screen.getByRole('tab', { name: 'Run details' }));
    expect(nav.replace).toHaveBeenCalledWith('/cases/CHG-1042?tab=trace', { scroll: false });
  });

  it('hold opens a Field form; a 422 shows inline; nothing builds its own key', async () => {
    const calls = mockFetch((c) => (c.method === 'POST' ? json({ code: 'schema_invalid', message: 'reason: String should have at least 5 characters' }, 422) : intake));
    renderWithProviders(<CaseWorkspace caseId="CHG-1042" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Hold for more information' }));
    await user.type(screen.getByLabelText('Reason'), 'x');
    await user.type(screen.getByLabelText('Next owner (user id)'), 'usr-dana-okafor');
    await user.click(screen.getByRole('button', { name: 'Hold for more information' }));
    expect((await screen.findByRole('alert')).textContent).toContain('at least 5 characters');
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/cases/CHG-1042/commands/hold_case');
    expect(JSON.parse(post.body!)).toEqual({ expected_case_version: 1, idempotency_key: 'hold:CHG-1042:1', payload: { reason: 'x', next_owner: 'usr-dana-okafor' } });
  });

  it('a 409 stale_case_version refetches, tells the user, and does not retry', async () => {
    let gets = 0;
    const calls = mockFetch((c) => {
      if (c.method === 'POST') return json({ code: 'stale_case_version', message: 'stale', case_version: 2 }, 409);
      gets += 1;
      return gets === 1 ? intake : { ...intake, case_version: 2, state_label: 'Investigating' };
    });
    renderWithProviders(<CaseWorkspace caseId="CHG-1042" />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Open case' }));
    expect(await screen.findByText(/nothing was retried/)).toBeTruthy();
    expect((await screen.findByText('Investigating')).textContent).toBe('Investigating');
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
  });

  it('a 403 shows the typed message, not a blank page', async () => {
    mockFetch(() => json({ code: 'forbidden', message: 'Cardholders can only see their own cases.' }, 403));
    renderWithProviders(<CaseWorkspace caseId="CHG-1042" />);
    expect((await screen.findByText('Cardholders can only see their own cases.')).textContent).toBeTruthy();
    expect(screen.getByText('Not available for this role')).toBeTruthy();
  });
});
