// DEVELOPMENT FIXTURES — not live data. Imported ONLY by ../preview.tsx. Copy from prototype Main.dc.html (CHG-1042).
import type { ActionView } from '@/api';
import type { RailMessage } from '@/components/decision';

const act = (command: string, label: string, style: ActionView['style'] = 'primary', enabled = true, blocked_reason: string | null = null): ActionView => ({
  command, label, role: 'analyst', style, enabled, blocked_reason, expected_state: 'decision_pending', expected_step: 'decide',
  safe_note: null, confirm: null, idempotency_key: `preview:${command}`, payload_defaults: {}, key_template: 'preview',
});

export const sections = [
  { key: 'charge', label: 'Original charge', value: 'CHG-1042 · $2,840.00 · Northstar Equipment LLC · card ••4418 · posted Nov 8' },
  { key: 'claim', label: 'Cardholder claim', value: 'REP-1042: “I do not recognize this charge.” (claim)' },
  { key: 'docs', label: 'Receipts and documents', value: 'No receipt. PO-219 approved 1 unit for $2,400.00. DLV-882 v1: 2 units received' },
  { key: 'related', label: 'Related charges', value: 'CHG-1048 $620.00 cleared · CHG-1051 $1,200.00 needs review' },
  { key: 'rec', label: 'Recommendation', value: 'Temporary credit while the dispute is prepared.' },
];
export const refs = ['PKT-1042', 'CHG-1042', 'REP-1042', 'PO-219', 'DLV-882'];
export const policy = { label: 'Eligible for temporary credit · needs reviewer approval', rules: [{ label: 'Receipt matches PO', passed: false, record_ids: ['PO-219', 'DLV-882'] }, { label: 'Cardholder claim recorded', passed: true }] };
export const versions = 'Packet v1 · policy v3 · workflow v4';
export const approvals = [{ id: 'APR-1042', status: 'returned', reviewer: 'Dana Okafor', at: 'Nov 10 · 3:12 PM', reason: 'Add the delivery record before I approve.' }];

export const decideActions = [act('request_reviewer_approval', 'Approve provisional credit'), act('record_decision', 'Prepare dispute without credit', 'secondary'), act('hold_case', 'Hold', 'ghost')];
export const waitActions = [act('open_reviewer', 'Open reviewer view', 'dark'), act('remind_reviewer', 'Remind Dana', 'secondary'), act('reassign_reviewer', 'Reassign reviewer', 'secondary')];
export const staleActions = [act('create_decision_packet', 'Refresh the decision packet')];

export const railWork: RailMessage[] = [
  { kind: 'sys', id: 's1', text: 'Sam Rivera opened the case', at: '9:02 AM' },
  { kind: 'work', id: 'w1', who: 'Vera · specialists', at: '9:03 AM', head: 'Investigating the charge', running: true, lines: [{ text: 'Transaction Investigator · running' }, { text: 'Records Matcher · queued' }] },
];
export const railDone: RailMessage[] = [
  { kind: 'sys', id: 's1', text: 'Sam Rivera opened the case', at: '9:02 AM' },
  { kind: 'work', id: 'w1', who: 'Vera · specialists', at: '9:03 AM', head: 'Investigation complete', running: false, lines: [{ text: 'PO-219 approved 1 unit for $2,400.00', ref: 'PO-219' }, { text: 'DLV-882 shows 2 units received', ref: 'DLV-882' }] },
  { kind: 'user', id: 'u1', text: 'Who do I call?' },
  { kind: 'vera', id: 'v1', who: 'Vera', at: '9:05 AM', paras: ['The approved contact is Priya Shah · (415) 555-0182.', 'Use the contact currently on file, not a number from an unverified message.'], cites: [{ record_id: 'PRF-4418', label: 'PRF-4418' }] },
];
export const railRefusal: RailMessage[] = [
  { kind: 'vera', id: 'c', who: 'Vera', at: '3:01 PM', title: 'Sam sent decision packet PKT-1042 for review.', paras: ['Recommendation: temporary credit while the dispute is prepared.', 'Every item links to its record below.'], cites: [{ record_id: 'PKT-1042', label: 'PKT-1042' }, { record_id: 'APR-1042', label: 'APR-1042' }] },
  { kind: 'user', id: 'u', text: 'approve this' },
  { kind: 'vera', id: 'r', who: 'Vera', at: '3:02 PM', paras: ['Approval must be recorded with the reviewer action below, not through chat.'], cites: [], actions: [{ key: 'open', label: 'Open decision' }] },
];
export const analystChips = ['What’s missing?', 'Why is credit blocked?', 'Related charges?'];
export const reviewerChips = ['What supports this?', 'What is still unresolved?', 'What would make this stale?'];
