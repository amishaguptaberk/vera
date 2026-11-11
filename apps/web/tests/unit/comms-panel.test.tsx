import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CommsPanel, RequestPage } from '@/features/comms';
import { caseDraft, cardholderRequest, draftDetail, draftItem, respondedDetail, saveAction, sendAction } from '../fixtures/comms';
import { mockFetch, renderWithProviders } from './helpers';

const json = (body: unknown, status: number) => new Response(JSON.stringify(body), { status });

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

function staffApi(view: unknown, detail: unknown = draftDetail) {
  return mockFetch((c) => {
    if (c.url === '/api/cases/CHG-1042/communications') return [draftItem];
    if (c.url === '/api/cases/CHG-1042/communications/MSG-2201') return detail;
    if (c.method === 'POST') return json({ code: 'x', message: 'nope' }, 500);
    return view;
  });
}

async function openDraft() {
  fireEvent.click(await screen.findByRole('button', { name: /Question about your charge/ }));
  return (await screen.findByLabelText('Message')) as HTMLTextAreaElement;
}

describe('CommsPanel', () => {
  it('Send is disabled until the backend offers send_communication', async () => {
    staffApi(caseDraft([]));
    renderWithProviders(<CommsPanel caseId="CHG-1042" />);
    await openDraft();
    const send = screen.getByRole('button', { name: 'Approve and send' }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    expect(screen.getByText('Sending isn’t available for this case right now.')).toBeTruthy();
  });

  it('Send is enabled when offered and posts channel, subject and attachments with the echoed key', async () => {
    const calls = staffApi(caseDraft([sendAction]));
    renderWithProviders(<CommsPanel caseId="CHG-1042" />);
    await openDraft();
    const send = screen.getByRole('button', { name: 'Approve and send' }) as HTMLButtonElement;
    await waitFor(() => expect(send.disabled).toBe(false));
    fireEvent.click(screen.getByRole('radio', { name: 'Ramp app' }));
    fireEvent.click(send);
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/cases/CHG-1042/commands/send_communication');
    expect(JSON.parse(post.body!)).toEqual({
      expected_case_version: 3,
      idempotency_key: 'send_communication:CHG-1042:3',
      payload: { channel: 'portal', subject: 'Question about your charge on case CHG-1042', attachments: [] },
    });
  });

  it('draft text survives a refetch and a remount (refresh)', async () => {
    staffApi(caseDraft([sendAction, saveAction]));
    const first = renderWithProviders(<CommsPanel caseId="CHG-1042" />);
    const ta = await openDraft();
    fireEvent.change(ta, { target: { value: 'Hi, please share the receipt for this charge.' } });
    expect(screen.getByText('Edited · not saved')).toBeTruthy();
    first.unmount();
    renderWithProviders(<CommsPanel caseId="CHG-1042" />);
    const again = await openDraft();
    expect(again.value).toBe('Hi, please share the receipt for this charge.');
  });

  it('shows the reply under the original request marked New', async () => {
    staffApi(caseDraft([]), respondedDetail);
    renderWithProviders(<CommsPanel caseId="CHG-1042" />);
    fireEvent.click(await screen.findByRole('button', { name: /Question about your charge/ }));
    expect(await screen.findByText('New')).toBeTruthy();
    expect(screen.getByText(/My manager ordered it/)).toBeTruthy();
    expect(screen.getByText('Original request · show full message')).toBeTruthy();
  });

  it('renders an honest Not available yet state when the route is not deployed', async () => {
    mockFetch(() => json({ detail: 'Not Found' }, 404));
    renderWithProviders(<CommsPanel caseId="CHG-1042" />);
    expect(await screen.findByText(/Not available yet/)).toBeTruthy();
  });
});

describe('RequestPage', () => {
  it('shows only the request’s own data and posts the answer to /api/requests/{id}/responses', async () => {
    let answered = false;
    const calls = mockFetch((c) => {
      if (c.method === 'POST') {
        answered = true;
        return { request_id: 'MSG-2201', status: 'answered', received: true };
      }
      return { ...cardholderRequest, responded: answered, status: answered ? 'answered' : 'awaiting_reply' };
    });
    const { container } = renderWithProviders(<RequestPage requestId="MSG-2201" />);
    await screen.findByText(cardholderRequest.questions[0]);
    expect(container.textContent).not.toMatch(/MSG-|CHG-1042|CASE-|Sam Rivera/);
    fireEvent.click(screen.getByLabelText('I did'));
    fireEvent.change(screen.getByLabelText(/Note to Finance/), { target: { value: 'Ordered for the plant.' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Send response' })));
    expect(await screen.findByRole('heading', { name: 'Response sent' })).toBeTruthy();
    const post = calls.find((c) => c.method === 'POST')!;
    expect(post.url).toBe('/api/requests/MSG-2201/responses');
    expect(JSON.parse(post.body!)).toEqual({ text: 'I did\n\nOrdered for the plant.' });
  });
});
