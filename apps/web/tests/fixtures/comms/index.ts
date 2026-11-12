// Contract-conforming fixtures for the communications API (shapes from src/features/comms/contract.ts).
import type { ActionView, CaseView } from '@/api/queries';
import type { CardholderRequest, CommunicationDetail, CommunicationItem } from '@/features/comms';
import intake from '../../parity/fixtures/case-CHG-1042-intake.json';

const action = (command: string, label: string, enabled = true): ActionView =>
  ({ command, label, role: 'analyst', style: 'primary', enabled, blocked_reason: enabled ? null : 'Not available yet.', safe_note: null, idempotency_key: `${command}:CHG-1042:3`, payload_defaults: {} }) as unknown as ActionView;

export const caseDraft = (actions: ActionView[]): CaseView =>
  ({ ...(intake as unknown as CaseView), case_version: 3, step: 'draft', state: 'waiting_on_cardholder', available_actions: actions }) as CaseView;

export const sendAction = action('send_communication', 'Approve and send');
export const saveAction = action('update_communication_draft', 'Save draft');
export const reviewAction = action('review_cardholder_response', 'Review response');

export const draftItem: CommunicationItem = {
  id: 'MSG-2201',
  kind: 'cardholder_request',
  status: 'drafted',
  title: 'Question about your charge on case CHG-1042',
  at: '2026-11-10T15:02:00Z',
  channel: null,
  due_at: null,
  reminders: 0,
  response_review: 'none',
};

export const draftDetail: CommunicationDetail = {
  ...draftItem,
  subject: 'Question about your charge on case CHG-1042',
  body: 'Hello,\n\n- Please upload the receipt or invoice for the Northstar Equipment charge.\n\nThank you.',
  questions: ['Please upload the receipt or invoice for the Northstar Equipment charge.'],
  attachments: [],
  delivery: null,
  draft_versions: 1,
  response: null,
};

export const respondedDetail: CommunicationDetail = {
  ...draftDetail,
  status: 'responded',
  channel: 'email',
  due_at: '2026-11-13T15:02:00Z',
  response: { id: 'RSP-2201', text: 'Someone else did\n\nMy manager ordered it.', evidence_record_id: null, submitted_at: '2026-11-10T16:20:00Z' },
};

export const cardholderRequest: CardholderRequest = {
  request_id: 'MSG-2201',
  status: 'awaiting_reply',
  subject: 'Question about your charge on case CHG-1042',
  questions: ['Please upload the receipt or invoice for the Northstar Equipment charge.', 'Did you receive the items on this order?'],
  due_at: '2026-11-13T15:02:00Z',
  responded: false,
};
