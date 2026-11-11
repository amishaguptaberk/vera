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
  policy_version: 3,
  workflow_version: 4,
  status: 'sent',
  stale: false,
  sections: [
    { key: 'charge', label: 'Original charge', value: 'CHG-1042 · $2,840.00 · Northstar Equipment LLC' },
    { key: 'claim', label: 'Cardholder claim', value: 'REP-1042: “I do not recognize this charge.” (claim)' },
  ],
  citations: ['CHG-1042', 'REP-1042'],
  policy: { label: 'Eligible for temporary credit', rules: [{ label: 'Receipt matches PO', passed: false, record_ids: ['PO-219'] }] },
  approvals: [],
  ...over,
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
