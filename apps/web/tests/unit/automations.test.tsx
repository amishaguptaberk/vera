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
