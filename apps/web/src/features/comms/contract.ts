// Typed contract for the communications API (backend: services/api/vera_api/comms.py, VER-005).
// Written from the pydantic models CommunicationItem / CommunicationDetail / ResponseView / CardholderRequest /
// CardholderRequestList / ResponseIn / ResponseOut and packages/domain/vera_domain/comms.py payloads.
// Replace with generated `components['schemas']` types once src/api/openapi.json includes these routes.

/** Communication.status values written by the backend effects. */
export type CommunicationStatus = 'drafted' | 'sent' | 'reminded' | 'overdue' | 'responded';
export type ResponseReview = 'none' | 'complete' | 'incomplete' | 'conflicting';

/** GET /api/cases/{case_id}/communications → CommunicationItem[] */
export type CommunicationItem = {
  id: string;
  kind: string;
  status: CommunicationStatus | string;
  title: string;
  at: string;
  channel: 'email' | 'portal' | string | null;
  due_at: string | null;
  reminders: number;
  response_review: ResponseReview | string;
};

export type ResponseView = { id: string; text: string; evidence_record_id: string | null; submitted_at: string };

/** GET /api/cases/{case_id}/communications/{item_id} */
export type CommunicationDetail = CommunicationItem & {
  subject: string;
  body: string;
  questions: string[];
  attachments: string[];
  delivery: Record<string, unknown> | null;
  draft_versions: number;
  response: ResponseView | null;
};

/** GET /api/requests/{request_id} (cardholder role). Cardholder-facing: only this request's own data. */
export type CardholderRequest = {
  request_id: string;
  status: 'awaiting_reply' | 'answered' | string;
  subject: string;
  questions: string[];
  due_at: string | null;
  responded: boolean;
};

/** GET /api/requests?mine=true */
export type CardholderRequestList = { requests: CardholderRequest[] };

/** vera_domain.comms.ResponseAttachment */
export type ResponseAttachment = { file_name: string; content_type: string; size_bytes: number; sha256: string };

/** POST /api/requests/{request_id}/responses */
export type ResponseIn = { text: string; attachment?: ResponseAttachment | null };
export type ResponseOut = { request_id: string; status: string; received: boolean };

/** Command payloads (run through POST /api/cases/{id}/commands/{name} via runCommand). */
export type UpdateDraftPayload = { subject: string; body: string };
export type SendPayload = { channel: 'email' | 'portal'; subject: string; attachments: string[] };
export type ReviewResponsePayload = { outcome: 'complete' | 'incomplete' | 'conflicting'; note?: string };

export const COMMS_COMMANDS = {
  draft: 'draft_follow_up',
  update: 'update_communication_draft',
  send: 'send_communication',
  remind: 'send_reminder',
  respond: 'submit_cardholder_response',
  review: 'review_cardholder_response',
} as const;
