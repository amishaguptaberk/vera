import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ActionView, EvidenceRegister, RunOut, StepOut } from '@/api';
import { CaseWorkspace } from '@/features/case';
import { EvidenceRegisterView } from '@/features/case/EvidencePanel';
import { RunList } from '@/features/case/RunDetails';
import evidence from '../parity/fixtures/evidence-CHG-1042-intake.json';
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

const ev = evidence as EvidenceRegister;
const withConflict: EvidenceRegister = {
  ...ev,
  open_conflicts: [{ finding_id: 'F-1', record_ids: ['DLV-882', 'PO-219'], field: 'quantity', values: [{ record_id: 'DLV-882', version: 1, value: 2 }, { record_id: 'PO-219', version: 1, value: 1 }] }],
  findings: [{ finding_id: 'F-1', kind: 'conflict', statement: 'Delivered quantity exceeds the PO.', status: 'open', resolved_by: null, links: [{ record_id: 'PO-219', version: 1, field: 'approved_quantity' }] }],
};

describe('Evidence register', () => {
  it('renders missing and conflicting distinctly from records and findings', () => {
    render(<EvidenceRegisterView ev={withConflict} onSelect={() => {}} />);
    const missing = screen.getByRole('list', { name: 'Missing evidence' });
    expect(within(missing).getByText('Receipt')).toBeTruthy();
    expect(missing.querySelector('[data-status="missing"]')).toBeTruthy();
    const conflicts = screen.getByRole('list', { name: 'Open conflicts' });
    expect(conflicts.querySelector('[data-status="conflicting"]')).toBeTruthy();
    const missingTag = within(missing).getByText('Missing');
    const conflictTag = within(conflicts).getByText('Conflicting');
    expect(missingTag.className).not.toBe(conflictTag.className);
    expect(document.querySelectorAll('[data-kind="record"]')).toHaveLength(ev.records.length);
    expect(document.querySelectorAll('[data-kind="finding"]')).toHaveLength(1);
  });

  it('a finding citation selects the record in the URL', async () => {
    nav.params = new URLSearchParams('tab=evidence');
    mockFetch((c) => (c.url.endsWith('/evidence') ? withConflict : c.url === '/api/session' ? { user: { id: 'u', name: 'U' }, active_role: 'analyst', roles: ['analyst'], environment: 'synthetic' } : c.url.includes('/activity') || c.url.includes('/runs') ? new Response('{}', { status: 404 }) : intake));
    renderWithProviders(<CaseWorkspace caseId="CHG-1042" />);
    await userEvent.setup().click(await screen.findByRole('button', { name: 'PO-219 · v1 · approved_quantity' }));
    expect(nav.replace).toHaveBeenCalledWith('/cases/CHG-1042?tab=evidence&sel=PO-219', { scroll: false });
  });
});

const step = (o: Partial<StepOut>): StepOut => ({ step_key: 'read', specialist: 'Records reader', status: 'succeeded', execution_mode: 'live', model_id: 'model-x', prompt_version: 'p1', usage: { input_tokens: 10 }, attempts: 1, failure_reason: null, started_at: null, finished_at: null, replayed: false, ...o });
const runOf = (steps: StepOut[]): RunOut => ({ id: 'RUN-1', case_id: 'CHG-1042', workflow_version: 3, policy_version: 1, status: 'completed', mode: 'live', created_at: '2026-11-10T00:00:00Z', steps });

describe('Run details', () => {
  it('labels live, replay, replayed, authored-reference and failed steps', () => {
    const retry = { ...(intake.available_actions[0] as ActionView), command: 'retry_specialist_step', label: 'Retry step', idempotency_key: 'retry:x', payload_defaults: { step_key: 'fail', mode: 'live' } };
    render(
      <RunList
        runs={[
          runOf([
            step({ step_key: 'live' }),
            step({ step_key: 'rep', execution_mode: 'replay', model_id: 'authored-reference' }),
            step({ step_key: 'again', execution_mode: 'replay', replayed: true }),
            step({ step_key: 'fail', status: 'failed', failure_reason: 'timeout' }),
          ]),
        ]}
        recovery={[retry]}
        onRecovery={() => {}}
      />,
    );
    expect(screen.getByTestId('step-live').textContent).toContain('LIVE');
    expect(screen.getByTestId('step-live').textContent).not.toContain('Replayed result');
    expect(screen.getByTestId('step-rep').textContent).toContain('REPLAY');
    expect(screen.getByTestId('step-rep').textContent).toContain('authored-reference');
    expect(screen.getByTestId('step-rep').textContent).toContain('not a live model');
    expect(screen.getByTestId('step-again').textContent).toContain('Replayed result');
    const failed = screen.getByTestId('step-fail');
    expect(failed.textContent).toContain('timeout');
    expect(within(failed).getByRole('button', { name: 'Retry step' })).toBeTruthy();
    expect(within(screen.getByTestId('step-live')).queryByRole('button')).toBeNull();
  });

  it('shows the model id exactly as sent and marks every replay step as a reference recording', () => {
    render(
      <RunList
        runs={[runOf([step({ step_key: 'rr', execution_mode: 'replay', model_id: 'reference-recording' }), step({ step_key: 'lv', model_id: 'meta/llama-3.3-70b-instruct' })])]}
        recovery={[]}
        onRecovery={() => {}}
      />,
    );
    const rr = screen.getByTestId('step-rr');
    expect(within(rr).getByText('reference-recording')).toBeTruthy();
    expect(rr.textContent).toContain('Reference recording (not a live model)');
    const lv = screen.getByTestId('step-lv');
    expect(within(lv).getByText('meta/llama-3.3-70b-instruct')).toBeTruthy();
    expect(lv.textContent).not.toContain('not a live model');
  });
});
