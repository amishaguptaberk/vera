// Typed contract for identity verification (VER-006, services/api/vera_api/identity.py) and verification
// callbacks (VER-007, services/api/vera_api/callbacks.py). Written from the backend pydantic models.

/** vera_domain.identity.IdentityStatus */
export type IdentityStatus =
  "requested" | "verified" | "failed" | "expired" | "declined" | "cancelled";
export type IdentityChannel = "otp" | "push";

/** Staff view (`GET /api/cases/{id}/verifications`): status, channel, attempts, timestamps. Never the code. */
export type VerificationView = {
  id: string;
  case_id: string;
  channel: IdentityChannel;
  status: IdentityStatus;
  attempts: number;
  max_attempts: number;
  attempts_left: number;
  sends: number;
  sent_at: string;
  last_sent_at: string;
  expires_at: string;
  resolved_at: string | null;
};

/** Synthetic demo control acting as the cardholder (`GET /api/verifications/{id}/outbox`, cardholder role only). */
export type OutboxView = {
  synthetic: true;
  label: string;
  verification_id: string;
  channel: IdentityChannel;
  code: string | null;
  attempts_left: number;
  next_attempt_no: number;
};

/** vera_domain.identity.RESEND_COOLDOWN_SECONDS — display-only countdown; the server enforces the cooldown. */
export const RESEND_COOLDOWN_SECONDS = 60;

/** vera_domain.callbacks.Outcome */
export type CallOutcome =
  "confirmed" | "contradicted" | "voicemail" | "no_answer" | "incomplete";
/** Voice call lifecycle (vera_api.voice). Active = queued | ringing | in_progress. */
export type VoiceStatus =
  | "queued"
  | "ringing"
  | "in_progress"
  | "completed"
  | "failed"
  | "no_answer"
  | "busy"
  | "timed_out";
export type CallStatus = VoiceStatus | CallOutcome;
export const ACTIVE_CALL_STATUSES: readonly string[] = [
  "queued",
  "ringing",
  "in_progress",
];
export const isActiveCall = (s: string) => ACTIVE_CALL_STATUSES.includes(s);
export type CallProvider = "elevenlabs" | "simulated";

export type CallAnswer = {
  question_id: string;
  answer: string;
  /** Legacy single citation (VER-007). */
  line_seq?: number;
  /** Transcript line seqs the answer is grounded in. */
  cited_lines?: number[];
};
export type StructuredResult = {
  result: "confirmed" | "failed" | string;
  outcome?: CallOutcome;
  authorization_answer?: "authorized" | "unauthorized" | null;
  /** Displayed exactly as the server sends it. */
  confidence?: number | string | null;
  answers: CallAnswer[];
};
export type CallQuestion = { id: string; text: string };

/** `GET /api/cases/{id}/callbacks` row. */
export type CallbackView = {
  id: string;
  attempt: number;
  status: CallStatus | string;
  target_record_id: string;
  target_field: string;
  target_version: number;
  questions: CallQuestion[];
  result: StructuredResult | null;
  approved_by: string;
  created_at: string;
  /** Server-masked destination; the full number is never sent to or shown by this screen. */
  masked_number?: string | null;
  purpose?: string | null;
  approval_state?: string | null;
  provider?: CallProvider | string | null;
  started_at?: string | null;
  confidence?: number | string | null;
};

export type CallLine = {
  seq: number;
  speaker: "agent" | "contact" | string;
  text: string;
};
/** `CallbackDetail.voice` (vera_api.voice.voice_view): provider call state, masked number only. */
export type VoiceAnswer = {
  question_id: string;
  answer: string;
  /** Cited transcript line. */
  line_index: number;
};
export type VoiceView = {
  provider: CallProvider | string;
  simulated: boolean;
  provider_call_id?: string;
  masked_number: string;
  purpose: string;
  call_status: VoiceStatus | string;
  started_at: string;
  ended_at: string | null;
  transcript_version: number;
  structured_answers: VoiceAnswer[];
  rejected?: string[];
  confidence: number | null;
};
export type CallNote = { author: string; text: string; created_at: string };

/** `GET /api/cases/{id}/callbacks/{callback_id}` */
export type CallbackDetail = CallbackView & {
  transcript: CallLine[];
  notes: CallNote[];
  transcript_version?: number;
  voice?: VoiceView | null;
};

/** Effective call status: the provider call state when a voice call exists, else the callback status. */
export const callStatusOf = (k: CallbackView & { voice?: VoiceView | null }) =>
  k.voice?.call_status ?? k.status;

/** Command names (vera_domain CommandSpec). Used only to place server-offered actions in these panels. */
export const IDENTITY_COMMANDS = [
  "send_verification_request",
  "resend_verification_request",
  "cancel_verification_request",
] as const;
export const CARDHOLDER_COMMANDS = {
  submitOtp: "submit_otp",
  answerPush: "answer_verification_push",
} as const;
export const CALLBACK_COMMANDS = [
  "start_callback",
  "end_callback",
  "escalate_callback",
  "add_callback_note",
] as const;
