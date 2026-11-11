import type { ActionView, CaseView } from '@/api';
import type { AskResponse, DecisionPacket } from '@/features/decision';
import intake from '../../parity/fixtures/case-CHG-1042-intake.json';

const action = (command: string, label: string, enabled = true): ActionView => ({
  command,
  label,
  role: 'reviewer',
  style: 'primary',
  enabled,
  blocked_reason: null,
  expected_state: 'decision_pending',
  expected_step: 'waitrv',
  safe_note: null,
  confirm: null,
  idempotency_key: `${command}:CHG-1042:3`,
  payload_defaults: command === 'return_decision' ? { next_step: 'refresh_packet', owner: 'usr-sam-rivera' } : {},
  key_template: `${command}:{case_id}:{packet_version}`,
});

export const reviewerCase = (step: string): CaseView =>
  ({
    ...(intake as unknown as CaseView),
    case_version: 7,
    step,
    state_label: 'Awaiting approval',
    next_action: 'Approve a temporary credit of $2,840.00?',
    available_actions: [action('approve_decision', 'Approve temporary credit'), action('return_decision', 'Return to Sam', true)],
    blocked_actions: [],
  }) as CaseView;

export const analystCase = (step: string, actions: ActionView[] = []): CaseView =>
  ({ ...(intake as unknown as CaseView), case_version: 7, step, state_label: 'Decision', next_action: 'Revise the packet Dana returned', available_actions: actions, blocked_actions: [] }) as CaseView;

export const packet = (over: Partial<DecisionPacket> = {}): DecisionPacket => ({
  case_id: 'CHG-1042',
  version: 2,
  latest_version: 2,
  current: true,
  snapshot_hash: 'snap-2',
  workflow_version: 4,
  policy_version: 3,
  policy_evaluation_id: 11,
  statements: [
    { text: 'CHG-1042 · $2,840.00 · Northstar Equipment LLC', citations: [{ record_id: 'CHG-1042', version: 1, field: 'amount' }] },
    { text: '“I do not recognize this charge.” (claim)', citations: [{ record_id: 'REP-1042', version: 1, field: 'statement' }] },
  ],
  open_conflicts: [],
  missing: [],
  policy: { label: 'Eligible for temporary credit', status: 'eligible', policy_version: 3, rules_failed: ['Receipt matches PO'], evidence_used: ['PO-219'] },
  recommendation: 'Temporary credit while the dispute is prepared.',
  decision: null,
  approval: null,
  created_by: 'usr-sam-rivera',
  created_at: '2026-11-10T15:00:00Z',
  ...over,
});

export const approval = (status: string, return_reason: string | null = null) => ({
  approval_id: 'APR-1042', case_id: 'CHG-1042', packet_version: 2, policy_version: 3, workflow_version: 4, status, reviewer_id: 'usr-dana-okafor', return_reason,
});

export const askContact: AskResponse = {
  answer: 'The approved contact is Priya Shah · (415) 555-0182.',
  citations: [{ record_id: 'PRF-4418', version: 1, field: 'phone' }],
  refused: false,
};
export const askRefusal: AskResponse = {
  answer: 'Approval must be recorded with the reviewer action below, not through chat.',
  citations: [],
  refused: true,
};
