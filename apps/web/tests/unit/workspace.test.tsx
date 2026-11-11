import { render, screen, within } from '@testing-library/react';
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

describe('ActionBar emphasis', () => {
  it('no yellow button when the first offered action is not server-styled primary (a block owns the main action)', () => {
    const hold = { ...actions[1], style: 'secondary' } as ActionView;
    const reassign = { ...actions[2], style: 'ghost' } as ActionView;
    render(<ActionBar actions={[hold, reassign]} blocked={[]} onAction={() => {}} />);
    expect(screen.getAllByRole('button').map((b) => b.getAttribute('data-primary'))).toEqual([null, null]);
  });

  it('the step’s server-primary action (the last one offered) leads the row', () => {
    const hold = { ...actions[1], style: 'secondary' } as ActionView;
    const prepare = { ...actions[0], command: 'create_decision_packet', label: 'Prepare decision packet', style: 'primary' } as ActionView;
    const record = { ...actions[0], command: 'record_decision', label: 'Record decision', style: 'primary' } as ActionView;
    render(<ActionBar actions={[hold, prepare, record]} blocked={[]} onAction={() => {}} />);
    const btns = screen.getAllByRole('button');
    expect(btns.map((b) => b.textContent)).toEqual(['Record decision', 'Hold for more information', 'Prepare decision packet']);
    expect(btns.map((b) => b.getAttribute('data-primary'))).toEqual(['true', null, null]);
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

  it('review related charge picks the record from the server targets, never a typed id', async () => {
    const review = { ...actions[0]!, command: 'review_related_charge', label: 'Review related charge', style: 'secondary', idempotency_key: 'related:CHG-1042:1', payload_defaults: {}, targets: ['CHG-1048', 'CHG-1051'] };
    const withReview = { ...intake, available_actions: [...actions, review] };
    const calls = mockFetch((c) => (c.method === 'POST' ? json({ status: 'recorded', result: {}, case: withReview }, 200) : withReview));
    renderWithProviders(<CaseWorkspace caseId="CHG-1042" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Review related charge' }));
    const form = within(screen.getByRole('form', { name: 'Review related charge' }));
    const record = form.getByLabelText('Related charge') as HTMLSelectElement;
    expect([...record.options].map((o) => o.value)).toEqual(['CHG-1048', 'CHG-1051']);
    await user.selectOptions(record, 'CHG-1051');
    await user.selectOptions(form.getByLabelText('Decision'), 'not_related');
    await user.type(form.getByLabelText('Reason'), 'Separate order.');
    await user.click(screen.getByRole('form', { name: 'Review related charge' }).querySelector('button[type="submit"]')!);
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/cases/CHG-1042/commands/review_related_charge');
    expect(JSON.parse(post.body!).payload).toEqual({ record_id: 'CHG-1051', decision: 'not_related', reason: 'Separate order.' });
  });

  it('review response picks an outcome and can accept the attached receipt (a boolean, not text)', async () => {
    const review = { ...actions[0]!, command: 'review_cardholder_response', label: 'Review response', style: 'primary', idempotency_key: 'review:CHG-1042:1', payload_defaults: {} };
    const withReview = { ...intake, available_actions: [review] };
    const calls = mockFetch((c) => (c.method === 'POST' ? json({ status: 'recorded', result: {}, case: withReview }, 200) : withReview));
    renderWithProviders(<CaseWorkspace caseId="CHG-1042" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Review response' }));
    const form = within(screen.getByRole('form', { name: 'Review response' }));
    await user.selectOptions(form.getByLabelText('Outcome'), 'conflicting');
    await user.click(form.getByLabelText('Accept the attached receipt as evidence'));
    await user.click(form.getByRole('button', { name: 'Review response' }));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(JSON.parse(post.body!).payload).toEqual({ outcome: 'conflicting', receipt_accepted: true });
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
