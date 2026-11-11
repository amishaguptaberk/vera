import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MoneyTask, type MoneyCaseView } from '@/features/money';
import controlsAnalyst from '../fixtures/money/case-controls_analyst.json';
import waitctlAnalyst from '../fixtures/money/case-waitctl_analyst.json';
import waitctlAdmin from '../fixtures/money/case-waitctl_card_admin.json';
import ctlApplyAdmin from '../fixtures/money/case-ctl_apply_card_admin.json';
import creditCheck from '../fixtures/money/case-credit_check.json';
import issue from '../fixtures/money/case-issue.json';
import dspPrepare from '../fixtures/money/case-dsp_prepare.json';
import close from '../fixtures/money/case-close.json';
import monitoring from '../fixtures/money/case-monitoring.json';
import closed from '../fixtures/money/case-closed.json';
import finalStep from '../fixtures/money/case-final.json';
import checklist from '../fixtures/money/closure-checklist.json';
import remediation from '../fixtures/money/remediation.json';
import finalMessage from '../fixtures/money/final-message.json';
import { mockFetch, renderWithProviders, type Call } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const asCase = (c: unknown) => c as MoneyCaseView;

function api(extra?: (c: Call) => Response | undefined) {
  return mockFetch((c) => {
    const r = extra?.(c);
    if (r) return r;
    if (c.url === '/api/cases/CHG-1042/closure-checklist') return json(checklist);
    if (c.url === '/api/cases/CHG-1042/executions') return json({ executions: [] });
    return json({ code: 'not_found', message: 'Not found' }, 404);
  });
}

describe('MoneyTask · card controls by role', () => {
  it('the analyst view never renders an apply-controls button', async () => {
    api();
    for (const c of [controlsAnalyst, waitctlAnalyst]) {
      const { unmount } = renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(c)} />);
      expect(screen.queryByRole('button', { name: /apply/i })).toBeNull();
      expect(screen.queryByRole('button', { name: /approve/i })).toBeNull();
      unmount();
    }
  });

  it('analyst control plan offers exactly the server actions (send / skip) and sends the selected controls', async () => {
    const calls = api((c) => (c.method === 'POST' ? json({ status: 'recorded', result: {}, case: controlsAnalyst }) : undefined));
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(controlsAnalyst)} />);
    expect(screen.getByText('Recommended controls for this case')).toBeTruthy();
    const group = screen.getByRole('group', { name: 'Case actions' });
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(['Send control plan to Dana', 'No controls needed']);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Monitor Bayline Industrial Supply for 30 days' }));
    await userEvent.click(screen.getByRole('button', { name: 'Send control plan to Dana' }));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/cases/CHG-1042/commands/propose_card_controls');
    const body = JSON.parse(post.body!) as { idempotency_key: string; payload: { controls: string[] } };
    expect(body.idempotency_key).toBe('propose_card_controls:CHG-1042');
    expect(body.payload.controls).toEqual(['lock']);
  });

  it('card-admin view shows approve / decline, then apply, only as the server offers them', () => {
    api();
    const { unmount } = renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(waitctlAdmin)} />);
    expect(screen.getByRole('button', { name: 'Approve controls' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Decline controls' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /apply/i })).toBeNull();
    unmount();
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(ctlApplyAdmin)} />);
    expect(screen.getByRole('button', { name: 'Apply approved controls — simulated' })).toBeTruthy();
  });
});

describe('MoneyTask · credit', () => {
  it('the checking state offers only the lookup action', () => {
    api();
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(creditCheck)} />);
    const btns = within(screen.getByRole('group', { name: 'Case actions' })).getAllByRole('button');
    expect(btns.map((b) => b.textContent)).toEqual(['Look up existing result']);
    expect(screen.getByText(/looks up the existing request before anything is retried/)).toBeTruthy();
  });

  it('Simulated / No funds moved appears on money and control actions only', () => {
    api();
    const { unmount } = renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(issue)} />);
    expect(screen.getByTestId('money-sim').textContent).toBe('Simulated · No funds moved');
    unmount();
    const r2 = renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(dspPrepare)} />);
    expect(screen.queryByTestId('money-sim')).toBeNull();
    r2.unmount();
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(ctlApplyAdmin)} />);
    expect(screen.getByTestId('money-sim')).toBeTruthy();
  });
});

describe('MoneyTask · served remediation and closure', () => {
  it('tracks and control plan come from GET /remediation when served', async () => {
    mockFetch((c) => (c.url === '/api/cases/CHG-1042/remediation' ? json(remediation) : json({ code: 'not_found', message: 'Not found' }, 404)));
    const noPlan = { ...asCase(controlsAnalyst), control_plan: undefined, dispute: undefined, controls: undefined };
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={noPlan} />);
    const list = await screen.findByRole('list', { name: 'Work after the decision' });
    expect(list.textContent).toContain('Ready to submit');
    expect(list.textContent).toContain('Recommended');
    expect(screen.getAllByRole('checkbox')).toHaveLength(5);
  });

  it('final draft starts from the served final message', async () => {
    api((c) => (c.url === '/api/cases/CHG-1042/final-message' ? json(finalMessage) : undefined));
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(finalStep)} />);
    expect(await screen.findByDisplayValue('Hi Priya, we issued a temporary credit.')).toBeTruthy();
  });

  it('close_case asks for reason and outcome before running', async () => {
    const calls = api((c) => (c.method === 'POST' ? json({ status: 'recorded', result: {}, case: close }) : undefined));
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(close)} />);
    await userEvent.click(screen.getByRole('button', { name: 'Close case — monitoring active' }));
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    await userEvent.type(screen.getByLabelText('Reason'), 'Credit issued, dispute submitted');
    await userEvent.type(screen.getByLabelText('Outcome (resolved, no_action or unresolved)'), 'resolved');
    await userEvent.click(screen.getByRole('button', { name: 'Close case — monitoring active' }));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/cases/CHG-1042/commands/close_case');
    expect((JSON.parse(post.body!) as { payload: unknown }).payload).toEqual({ reason: 'Credit issued, dispute submitted', outcome: 'resolved' });
  });
});

describe('MoneyTask · tracks and closure', () => {
  it('ParallelTracks shows both tracks with their server status labels', () => {
    api();
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(dspPrepare)} />);
    const list = screen.getByRole('list', { name: 'Work after the decision' });
    expect(list.textContent).toContain('Running in parallel · close waits for both');
    const rows = within(list).getAllByRole('listitem');
    expect(rows.map((r) => r.textContent?.replace('Work on this next', ''))).toEqual(['Dispute packetNot prepared', 'Card controlsAwaiting admin approval']);
  });

  it('closure checklist lists open items with owner and next action; unknown is not shown as met', async () => {
    api();
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(close)} />);
    expect(await screen.findByText('Card-control decision recorded')).toBeTruthy();
    const items = screen.getAllByTestId('closure-item');
    const ctl = items.find((i) => i.textContent?.includes('Card-control decision recorded'))!;
    expect(ctl.className).not.toMatch(/ok/);
    expect(ctl.textContent).toContain('Not verifiable');
    expect(ctl.textContent).toContain('Dana Okafor');
    expect(ctl.textContent).toContain('Approve or decline CTL-1042');
    const fin = items.find((i) => i.textContent?.includes('Final cardholder communication sent'))!;
    expect(fin.textContent).toContain('Sam Rivera · Send the final update');
    const met = items.find((i) => i.textContent?.includes('Decision recorded'))!;
    expect(met.querySelector('[data-mark]')?.textContent).toBe('✓');
  });

  it('closure checklist 404 renders an honest not-available state', async () => {
    mockFetch(() => json({ code: 'not_found', message: 'Not found' }, 404));
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(close)} />);
    expect(await screen.findByText('Closure checklist · not available yet')).toBeTruthy();
  });

  it('monitoring and closed are read-only: no actions rendered', () => {
    api();
    for (const c of [monitoring, closed]) {
      const { unmount } = renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(c)} />);
      expect(screen.queryAllByRole('button').filter((b) => !b.closest('[data-ref]'))).toEqual([]);
      unmount();
    }
  });

  it('final message content-policy 422 is shown inline', async () => {
    api((c) =>
      c.method === 'POST' ? json({ code: 'content_policy', message: 'The message says the card is locked, but no lock has been applied.' }, 422) : undefined,
    );
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={asCase(finalStep)} />);
    const ta = screen.getByLabelText('Message');
    await userEvent.type(ta, 'Your card is locked.');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByText('The message says the card is locked, but no lock has been applied.')).toBeTruthy();
  });
});

describe('MoneyTask · dispute narrative', () => {
  const action = (command: string, label: string, step: string) => ({
    command, label, role: 'analyst', style: 'secondary', enabled: true, blocked_reason: null, expected_state: 'dispute_prepared', expected_step: step,
    safe_note: null, confirm: null, idempotency_key: `${command}:CHG-1042:9`, payload_defaults: {}, key_template: `${command}:{case_id}:{case_version}`,
  });
  const reviewCase = asCase({
    ...dspPrepare,
    state: 'dispute_prepared',
    step: 'dsp_review',
    available_actions: [action('review_dispute_packet', 'Mark reviewed', 'dsp_review'), action('retry_dispute_narrative', 'Retry dispute narrative', 'dsp_review')],
  });
  const withDispute = (dispute: Record<string, unknown>) => ({ ...remediation, dispute: { ...remediation.dispute, status: 'reviewed', ...dispute } });
  const serve = (dispute: Record<string, unknown>) =>
    mockFetch((c) => (c.url === '/api/cases/CHG-1042/remediation' ? json(withDispute(dispute)) : c.method === 'POST' ? json({ status: 'recorded', result: {}, case: reviewCase }) : json({ code: 'not_found', message: 'Not found' }, 404)));

  it('shows the reason code and each statement with its cited record, version and field', async () => {
    serve({
      narrative_status: 'ready',
      reason_code: 'quantity_mismatch',
      narrative: [
        { text: 'Purchase order PO-219 approves 1 unit.', record_id: 'PO-219', version: 1, field: 'approved_quantity' },
        { text: 'Delivery record DLV-882 records 2 units received.', record_id: 'DLV-882', version: 1, field: 'received_quantity' },
      ],
    });
    const open = vi.fn();
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={reviewCase} onOpenRecord={open} />);
    const list = await screen.findByRole('list', { name: 'Dispute narrative' });
    expect(screen.getByText('Quantity mismatch')).toBeTruthy();
    const rows = within(list).getAllByRole('listitem');
    expect(rows.map((r) => r.textContent)).toEqual([
      'Purchase order PO-219 approves 1 unit.PO-219 v1 · approved_quantity',
      'Delivery record DLV-882 records 2 units received.DLV-882 v1 · received_quantity',
    ]);
    await userEvent.click(within(rows[1]!).getByRole('button', { name: 'DLV-882 v1 · received_quantity' }));
    expect(open).toHaveBeenCalledWith('DLV-882');
    // No failure, so the retry is not offered anywhere; the review action still is.
    expect(screen.queryByRole('button', { name: 'Retry dispute narrative' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Mark reviewed' })).toBeTruthy();
  });

  it('says the narrative is being prepared while the server reports pending', async () => {
    serve({ narrative_status: 'pending', reason_code: null, narrative: [] });
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={reviewCase} />);
    expect(await screen.findByText('Preparing dispute narrative…')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Mark reviewed' })).toBeTruthy();
  });

  it('a failed narrative shows an honest line with the server retry; the dispute track still offers review', async () => {
    const calls = serve({ narrative_status: 'failed', reason_code: null, narrative: [] });
    renderWithProviders(<MoneyTask caseId="CHG-1042" c={reviewCase} />);
    expect(await screen.findByText(/The dispute narrative could not be prepared/)).toBeTruthy();
    const bar = screen.getByRole('group', { name: 'Case actions' });
    expect(within(bar).getAllByRole('button').map((b) => b.textContent)).toEqual(['Mark reviewed']);
    await userEvent.click(screen.getByRole('button', { name: 'Retry dispute narrative' }));
    await userEvent.type(screen.getByLabelText('Mode (live or replay)'), 'replay');
    await userEvent.click(within(screen.getByRole('form', { name: 'Retry dispute narrative' })).getByRole('button', { name: 'Retry dispute narrative' }));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/cases/CHG-1042/commands/retry_dispute_narrative');
    expect((JSON.parse(post.body!) as { payload: unknown }).payload).toEqual({ mode: 'replay' });
  });
});
