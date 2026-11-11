import { act as rtlAct, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CallPanel, CardholderVerifyPanel, IdentityPanel } from '@/features/verify';
import type { CallbackDetail, IdentityStatus } from '@/features/verify/contract';
import { act, call, caseWith, CODE, outbox, verification } from '../fixtures/verify/fixtures';
import { mockFetch, renderWithProviders, session, type Call } from './helpers';

afterEach(() => vi.unstubAllGlobals());

const notFound = () => new Response(JSON.stringify({ code: 'not_found', message: 'nope' }), { status: 404 });

const STATUSES: [IdentityStatus, string][] = [
  ['requested', 'Awaiting cardholder'],
  ['verified', 'Identity verified'],
  ['failed', 'Verification failed'],
  ['expired', 'Verification expired'],
  ['declined', 'Verification denied'],
  ['cancelled', 'Request cancelled'],
];

describe('Analyst identity verification', () => {
  it.each(STATUSES)('never renders a code or code field for a %s payload, even when the payload carries one', async (status, label) => {
    const calls = mockFetch((c) => {
      if (c.url === '/api/session') return session('analyst');
      if (c.url.endsWith('/verifications')) return [{ ...verification(status, { attempts: 1, attempts_left: 2 }), code: CODE, otp: CODE }];
      if (c.url === '/api/cases/CHG-1042') return caseWith([act('resend_verification_request'), act('cancel_verification_request')]);
      return notFound();
    });
    renderWithProviders(<IdentityPanel caseId="CHG-1042" />);
    const detail = await screen.findByTestId('identity-detail');
    expect((await within(detail).findAllByText(new RegExp(label))).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toContain(CODE);
    expect(document.querySelector('input')).toBeNull();
    expect(screen.queryByLabelText(/code/i)).toBeNull();
    expect(calls.some((x) => x.url.includes('/outbox'))).toBe(false);
  });

  it('shows the resend cooldown countdown while a request is waiting', async () => {
    const sent = new Date(Date.now() - 15_000).toISOString();
    mockFetch((c) => {
      if (c.url === '/api/session') return session('analyst');
      if (c.url.endsWith('/verifications')) return [verification('requested', { last_sent_at: sent, sent_at: sent })];
      if (c.url === '/api/cases/CHG-1042') return caseWith([act('resend_verification_request', { enabled: false, blocked_reason: 'Wait a moment before resending.' })]);
      return notFound();
    });
    renderWithProviders(<IdentityPanel caseId="CHG-1042" />);
    expect(await screen.findByText(/Resend available in (4[5-6])s/)).toBeTruthy();
  });

  it('says "not available yet" when the route is not deployed', async () => {
    mockFetch((c) => (c.url === '/api/session' ? session('analyst') : c.url === '/api/cases/CHG-1042' ? caseWith([]) : new Response('{"detail":"Not Found"}', { status: 404 })));
    renderWithProviders(<IdentityPanel caseId="CHG-1042" />);
    expect(await screen.findByText('Identity verification is not available yet.')).toBeTruthy();
  });
});

describe('Cardholder verification (synthetic demo control)', () => {
  it('shows the code only inside the labelled demo box and submits through the server action key', async () => {
    const calls: Call[] = mockFetch((c) => {
      if (c.url === '/api/session') return session('cardholder');
      if (c.url === '/api/verifications/IDV-0001/outbox') return outbox;
      if (c.url === '/api/cases/CHG-1042') return caseWith([act('submit_otp', { payload_defaults: { verification_id: 'IDV-0001' } })]);
      if (c.method === 'POST') return { status: 'applied', result: { status: 'verified' }, event_ids: [], case: caseWith([]) };
      return notFound();
    });
    renderWithProviders(<CardholderVerifyPanel caseId="CHG-1042" />);
    const box = await screen.findByTestId('cardholder-demo-outbox');
    expect(within(box).getByText(CODE)).toBeTruthy();
    expect(within(box).getByText(/Synthetic demo/)).toBeTruthy();
    const u = userEvent.setup();
    await u.type(screen.getByLabelText('6-digit code'), CODE);
    await u.click(screen.getByRole('button', { name: 'Verify' }));
    expect(await screen.findByText('Thanks — you’re verified.')).toBeTruthy();
    const post = calls.find((x) => x.method === 'POST')!;
    expect(post.url).toBe('/api/cases/CHG-1042/commands/submit_otp');
    expect(JSON.parse(post.body!)).toMatchObject({ idempotency_key: 'srv:submit_otp:1', payload: { verification_id: 'IDV-0001', code: CODE } });
    expect(calls.every((x) => !x.url.includes(CODE))).toBe(true);
  });

  it('push: approve and deny answer the request', async () => {
    const calls = mockFetch((c) => {
      if (c.url === '/api/session') return session('cardholder');
      if (c.url === '/api/cases/CHG-1042') return caseWith([act('answer_verification_push', { payload_defaults: { verification_id: 'IDV-0001' } })]);
      if (c.method === 'POST') return { status: 'applied', result: { status: 'declined' }, event_ids: [], case: caseWith([]) };
      return notFound();
    });
    renderWithProviders(<CardholderVerifyPanel caseId="CHG-1042" />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Deny' }));
    expect(await screen.findByText('Verification didn’t complete.')).toBeTruthy();
    expect(JSON.parse(calls.find((x) => x.method === 'POST')!.body!).payload).toEqual({ verification_id: 'IDV-0001', approve: false });
    expect(calls.some((x) => x.url.includes('/outbox'))).toBe(false);
  });
});

function mockCall(get: () => CallbackDetail, actions = caseWith([])) {
  return mockFetch((c) => {
    if (c.url === '/api/session') return session('analyst');
    if (c.url === '/api/cases/CHG-1042') return actions;
    if (c.url === '/api/cases/CHG-1042/callbacks') {
      const { transcript: _t, notes: _n, ...row } = get();
      return [row];
    }
    if (c.url === '/api/cases/CHG-1042/callbacks/CB-0001') return get();
    return notFound();
  });
}

describe('Verification call', () => {
  it('preparation shows the exact questions and the target with its source record chip', async () => {
    mockFetch((c) => {
      if (c.url === '/api/session') return session('analyst');
      if (c.url === '/api/cases/CHG-1042/callbacks') return [];
      if (c.url === '/api/cases/CHG-1042')
        return caseWith([act('start_callback', { label: 'Approve and start call', payload_defaults: { questions: [{ id: 'q1', text: 'Did you place the order?' }], target_record_id: 'PRF-4418' } })]);
      return notFound();
    });
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    expect(await screen.findByText('Did you place the order?')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Source record PRF-4418' })).toBeTruthy();
    expect(screen.getByText('Not started.')).toBeTruthy();
  });

  it('appends transcript lines in place without re-mounting the panel', async () => {
    let cur = call({ transcript: [{ seq: 1, speaker: 'agent', text: 'Hi, this is Vera.' }] });
    mockCall(() => cur);
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    await screen.findByText('“Hi, this is Vera.”');
    const panel = screen.getByTestId('call-detail');
    const tr = screen.getByTestId('transcript');
    const first = tr.firstElementChild;
    expect(screen.getByText('Live')).toBeTruthy();
    cur = call({ transcript: [...cur.transcript, { seq: 2, speaker: 'contact', text: 'Hello, this is Priya.' }] });
    await screen.findByText('“Hello, this is Priya.”', undefined, { timeout: 3000 });
    expect(screen.getByTestId('call-detail')).toBe(panel);
    expect(screen.getByTestId('transcript')).toBe(tr);
    expect(tr.firstElementChild).toBe(first);
    expect(tr.children).toHaveLength(2);
  });

  it.each([
    ['confirmed', 'Completed · confirmed'],
    ['contradicted', 'Completed · not confirmed'],
    ['voicemail', 'Unanswered · voicemail'],
    ['no_answer', 'Unanswered · no answer'],
    ['incomplete', 'Incomplete · result not recorded'],
  ] as const)('%s: structured result block is separate from the transcript', async (outcome, label) => {
    mockCall(() =>
      call({
        status: outcome,
        transcript: [{ seq: 1, speaker: 'contact', text: 'Hello, this is Priya.' }],
        result: { result: outcome === 'confirmed' ? 'confirmed' : 'failed', outcome, authorization_answer: outcome === 'confirmed' ? 'unauthorized' : null, answers: [] },
      }),
      caseWith([act('start_callback', { label: 'Retry call' })]),
    );
    renderWithProviders(<CallPanel caseId="CHG-1042" />);
    const res = await screen.findByTestId('structured-result');
    expect(within(res).getAllByText(label).length).toBeGreaterThan(0);
    expect(screen.getAllByText(label, { selector: 'dd' }).some((el) => !res.contains(el))).toBe(true);
    const tr = screen.getByTestId('transcript');
    expect(tr.contains(res)).toBe(false);
    expect(res.contains(tr)).toBe(false);
    expect(screen.queryByText('Live')).toBeNull();
    await rtlAct(async () => {});
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry call' })).toBeTruthy());
  });
});
