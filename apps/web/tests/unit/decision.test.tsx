import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReviewerControls } from '@/components/decision';
import { DecisionPanel, ReviewerPanel, VeraRailPanel } from '@/features/decision';
import { analystCase, approval, askContact, askRefusal, packet, reviewerCase } from '../fixtures/decision/fixtures';
import { mockFetch, renderWithProviders } from './helpers';

afterEach(() => vi.unstubAllGlobals());
const json = (body: unknown, status: number) => new Response(JSON.stringify(body), { status });
const btn = { label: 'Approve temporary credit', enabled: true };
const retBtn = { label: 'Return to Sam', enabled: true };

describe('reviewer stale state', () => {
  it('shows the stale banner and disables approve when the packet is out of date', () => {
    render(<ReviewerControls approve={btn} ret={retBtn} stale staleWhat="DLV-882 v2" analystName="Sam" onApprove={() => {}} onReturn={() => {}} />);
    expect(screen.getByRole('alert').textContent).toBe(
      'Evidence changed after this packet was sent (DLV-882 v2). Approval is blocked until Sam refreshes the packet. You can return it with a note.',
    );
    expect((screen.getByRole('button', { name: 'Approve temporary credit' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('reviewer panel: server packet stale → banner, approve disabled', async () => {
    mockFetch(() => packet({ version: 1, latest_version: 2, current: false }));
    renderWithProviders(<ReviewerPanel c={reviewerCase('waitrv')} />);
    expect((await screen.findByRole('alert')).textContent).toContain('(packet v1, latest v2)');
    expect((screen.getByRole('button', { name: 'Approve temporary credit' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('reviewer return', () => {
  it('Return is disabled until a reason is typed, then posts the server key with the reason', async () => {
    const calls = mockFetch((c) => (c.method === 'POST' ? json({ code: 'x', message: 'nope' }, 422) : packet()));
    renderWithProviders(<ReviewerPanel c={reviewerCase('waitrv')} />);
    const user = userEvent.setup();
    const ret = (await screen.findByRole('button', { name: 'Return to Sam' })) as HTMLButtonElement;
    expect(ret.disabled).toBe(true);
    await user.type(screen.getByLabelText('Or return it to Sam Rivera with a note'), 'Receipt missing');
    expect(ret.disabled).toBe(false);
    await user.click(ret);
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/cases/CHG-1042/commands/return_decision');
    expect(JSON.parse(post.body!)).toEqual({
      expected_case_version: 7,
      idempotency_key: 'return_decision:CHG-1042:3',
      payload: { next_step: 'refresh_packet', owner: 'usr-sam-rivera', reason: 'Receipt missing' },
    });
  });
});

describe('analyst decision tab', () => {
  it('policy shows the human label; a failed rule links to its evidence', async () => {
    mockFetch(() => packet());
    const onSelect = vi.fn();
    renderWithProviders(<DecisionPanel c={analystCase('decide')} onSelectRecord={onSelect} />);
    expect(await screen.findByText('Eligible for temporary credit')).toBeTruthy();
    await userEvent.setup().click(screen.getByRole('button', { name: 'PO-219' }));
    expect(onSelect).toHaveBeenCalledWith('PO-219');
  });

  it('returned step shows the reviewer reason', async () => {
    mockFetch(() => packet({ approval: approval('returned', 'Receipt missing') }));
    renderWithProviders(<DecisionPanel c={analystCase('returned')} />);
    expect(await screen.findByText('“Receipt missing” Update the rationale and resend.')).toBeTruthy();
  });

  it('a 404 packet renders an honest not-available state', async () => {
    mockFetch(() => json({ code: 'not_found', message: 'nope' }, 404));
    renderWithProviders(<DecisionPanel c={analystCase('decide')} />);
    expect((await screen.findByTestId('packet-unavailable')).textContent).toBe('Decision packet: not available yet.');
  });
});

describe('Vera rail', () => {
  const routes = (askBodies: unknown[]) =>
    mockFetch((c) => {
      if (c.url.endsWith('/runs')) return [];
      if (c.url.endsWith('/activity')) return { events: [] };
      if (c.url.endsWith('/ask')) return askBodies.shift();
      return json({ code: 'not_found', message: '' }, 404);
    });

  it('sends chip text verbatim, shows the answer with citation chips that select the record, and replaces a repeated pair', async () => {
    const calls = routes([askContact, askContact]);
    const onSelect = vi.fn();
    renderWithProviders(<VeraRailPanel c={analystCase('decide')} role="analyst" open onClose={() => {}} onSelectRecord={onSelect} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Message Vera'), 'Who do I call?{Enter}');
    expect(await screen.findByText('The approved contact is Priya Shah · (415) 555-0182.')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'PRF-4418 v1' }));
    expect(onSelect).toHaveBeenCalledWith('PRF-4418');
    await user.type(screen.getByLabelText('Message Vera'), 'Who do I call?{Enter}');
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/ask'))).toHaveLength(2));
    await waitFor(() => expect(screen.getAllByText('The approved contact is Priya Shah · (415) 555-0182.')).toHaveLength(1));
    expect(JSON.parse(calls.find((c) => c.url.endsWith('/ask'))!.body!)).toEqual({ text: 'Who do I call?' });
  });

  it('"approve this" shows the server refusal and offers no button', async () => {
    routes([askRefusal]);
    renderWithProviders(<VeraRailPanel c={reviewerCase('waitrv')} role="reviewer" open onClose={() => {}} onSelectRecord={() => {}} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Message Vera'), 'approve this{Enter}');
    expect(await screen.findByText('Approval must be recorded with the reviewer action below, not through chat.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull();
  });

  it('composer is disabled only while sending', async () => {
    let release: (r: Response) => void = () => {};
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const u = String(input);
        if (u.endsWith('/ask')) return new Promise<Response>((r) => (release = r));
        return Promise.resolve(new Response(JSON.stringify(u.endsWith('/activity') ? { events: [] } : []), { status: 200 }));
      }),
    );
    renderWithProviders(<VeraRailPanel c={analystCase('decide')} role="analyst" open onClose={() => {}} onSelectRecord={() => {}} />);
    const input = screen.getByLabelText('Message Vera') as HTMLInputElement;
    expect(input.disabled).toBe(false);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Why is credit blocked?' }));
    await waitFor(() => expect(input.disabled).toBe(true));
    release(new Response(JSON.stringify(askContact), { status: 200 }));
    await waitFor(() => expect(input.disabled).toBe(false));
  });
});
