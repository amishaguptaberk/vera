import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CardholderRequestCard } from '@/components/comms';

const request = {
  questions: ['Please upload the receipt or invoice for the Bayline Industrial Supply charge.', 'Did you receive the items on this order?'],
  dueLabel: 'Please respond by Nov 13',
  responded: false,
};

describe('CardholderRequestCard', () => {
  it('keeps Send disabled until an answer is chosen', () => {
    render(<CardholderRequestCard request={request} onSubmit={vi.fn()} />);
    const send = screen.getByRole('button', { name: 'Send response' });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Choose an answer first')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('I did'));
    expect((send as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText('No file attached')).toBeTruthy();
  });

  it('rejects a file over 10 MB inline and keeps the draft', () => {
    render(<CardholderRequestCard request={request} onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByLabelText('Someone else did'));
    fireEvent.change(screen.getByLabelText(/Note to Finance/), { target: { value: 'My manager ordered it.' } });
    const big = new File(['x'], 'scan.pdf', { type: 'application/pdf' });
    Object.defineProperty(big, 'size', { value: 11 * 1024 * 1024 });
    fireEvent.change(screen.getByLabelText('Attach file'), { target: { files: [big] } });
    expect(screen.getByText('scan.pdf is over 10 MB.')).toBeTruthy();
    expect((screen.getByLabelText(/Note to Finance/) as HTMLTextAreaElement).value).toBe('My manager ordered it.');
    expect((screen.getByLabelText('Someone else did') as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByText(/ready to send/)).toBeNull();
  });

  it('rejects a disallowed file type inline', () => {
    render(<CardholderRequestCard request={request} onSubmit={vi.fn()} />);
    const exe = new File(['x'], 'tool.exe', { type: 'application/octet-stream' });
    fireEvent.change(screen.getByLabelText('Attach file'), { target: { files: [exe] } });
    expect(screen.getByText('tool.exe isn’t a PDF, JPG or PNG.')).toBeTruthy();
  });

  it('lists an accepted file as ready to send', () => {
    render(<CardholderRequestCard request={request} onSubmit={vi.fn()} />);
    const ok = new File(['abc'], 'receipt.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByLabelText('Attach file'), { target: { files: [ok] } });
    expect(screen.getByText('receipt.pdf')).toBeTruthy();
    expect(screen.getByText(/PDF · 1 KB · ready to send/)).toBeTruthy();
  });

  it('shows the submitted state with no internal ids or staff names', () => {
    const { container } = render(<CardholderRequestCard request={{ ...request, responded: true }} onSubmit={vi.fn()} />);
    expect(screen.getByRole('heading', { name: 'Response sent' })).toBeTruthy();
    expect(container.textContent).not.toMatch(/MSG-|CASE-|RSP-|Sam Rivera/);
  });
});
