import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkflowsPage } from '@/features/automations';
import type { WorkflowDetail } from '@/features/automations/contract';
import workflowJson from '../fixtures/automations/workflow.json';
import { mockFetch, renderWithProviders } from './helpers';

const workflow = workflowJson as unknown as WorkflowDetail;
afterEach(() => vi.unstubAllGlobals());

describe('Workflow builder', () => {
  it('selecting a trace row selects its node', async () => {
    mockFetch(() => workflow);
    renderWithProviders(<WorkflowsPage />);
    const rows = await screen.findAllByTestId('trace-row');
    await userEvent.click(within(rows[3]).getByRole('button', { name: 'Provisional credit' }));
    expect(screen.getByTestId('inspector-name').textContent).toBe('Provisional credit');
    const node = document.querySelector('[data-node="credit_executor"]')!;
    expect(node.getAttribute('aria-pressed')).toBe('true');
  });
});

describe('Workflow builder · server-owned rules', () => {
  it('marks only nodes named by server violations and lists them in validation', async () => {
    mockFetch(() => workflow);
    renderWithProviders(<WorkflowsPage />);
    await screen.findAllByTestId('trace-row');
    expect(document.querySelector('[data-node="credit_executor"] [title="Provisional credit has no failure path."]')).not.toBeNull();
    expect(document.querySelector('[data-node="pc1"] [title]:not([title="Drag to connect"])')).toBeNull();
  });

  it('offers no Remove step for a required control, and shows the server rejection for a removable step', async () => {
    mockFetch((c) =>
      c.method === 'POST'
        ? new Response(JSON.stringify({ code: 'required_control', message: 'Prevention Planner cannot be removed: rejected by server.' }), { status: 422 })
        : workflow,
    );
    renderWithProviders(<WorkflowsPage />);
    await screen.findAllByTestId('trace-row');
    await userEvent.click(document.querySelector('[data-node="analyst_decision"]') as HTMLElement);
    expect(screen.queryByRole('button', { name: 'Remove step' })).toBeNull();
    await userEvent.click(document.querySelector('[data-node="prevention_planner"]') as HTMLElement);
    await userEvent.click(screen.getByRole('button', { name: 'Remove step' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Prevention Planner cannot be removed: rejected by server.');
  });

  it('keeps zoom and the canvas element across selection changes', async () => {
    mockFetch(() => workflow);
    renderWithProviders(<WorkflowsPage />);
    await screen.findAllByTestId('trace-row');
    const canvas = screen.getByTestId('workflow-canvas');
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    const zoom = screen.getByTitle('Reset to 100%').textContent;
    await userEvent.click(document.querySelector('[data-node="pc1"]') as HTMLElement);
    expect(screen.getByTestId('workflow-canvas')).toBe(canvas);
    expect(screen.getByTitle('Reset to 100%').textContent).toBe(zoom);
    expect(zoom).toBe('94%');
  });

  it('shows the layout with "Not available yet" when the endpoint is not deployed', async () => {
    mockFetch(() => new Response(JSON.stringify({ code: 'not_found', message: 'Not Found' }), { status: 404 }));
    renderWithProviders(<WorkflowsPage />);
    expect(await screen.findByText('Not available yet')).toBeTruthy();
  });
});
