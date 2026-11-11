import { describe, expect, it } from 'vitest';
import { actorLabel, dayLabel, roleLabel } from '@/lib';

describe('actor labels', () => {
  it('keeps a person’s name and titles service and specialist identifiers', () => {
    expect(actorLabel('Sam Rivera')).toBe('Sam Rivera');
    expect(actorLabel('specialist:related_transaction_investigator')).toBe('Related Transaction Investigator');
    expect(actorLabel('specialist:receipt_document_reviewer')).toBe('Receipt Document Reviewer');
    expect(actorLabel('policy_controller')).toBe('Policy Controller');
    expect(actorLabel('svc-orchestrator')).toBe('Orchestrator');
  });
  it('shows a role only after a person’s name', () => {
    expect(roleLabel('card_admin', 'Dana Okafor')).toBe('card admin');
    expect(roleLabel('specialist', 'specialist:charge_investigator')).toBe('');
    expect(roleLabel('system', 'svc-orchestrator')).toBe('');
  });
  it('labels a day by its date, never relative to the browser clock', () => {
    expect(dayLabel(new Date(2026, 10, 10, 9, 5).toISOString())).toBe('Nov 10');
    expect(dayLabel(new Date(2026, 10, 8, 12, 0).toISOString())).toBe('Nov 8');
  });
});
