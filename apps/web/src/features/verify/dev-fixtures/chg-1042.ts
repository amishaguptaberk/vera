// DEVELOPMENT FIXTURES — imported ONLY by ../preview.tsx. Contract-conforming CHG-1042 data taken from the
// prototype's own copy. Staff-view fixtures carry NO OTP code; the one code below feeds the cardholder demo box only.
import type { ActionView } from "@/api";
import type {
  CallbackDetail,
  CallOutcome,
  IdentityStatus,
  OutboxView,
  VerificationView,
} from "../contract";

export const HOLDER = "Priya Shah";
export const PHONE = "(415) 555-0182";

const A = (
  command: string,
  label: string,
  style: ActionView["style"] = "secondary",
  o: Partial<ActionView> = {},
): ActionView => ({
  command,
  label,
  role: "analyst",
  style,
  enabled: true,
  blocked_reason: null,
  expected_state: "callback_pending",
  expected_step: "idv",
  safe_note: null,
  confirm: null,
  idempotency_key: `preview:${command}`,
  payload_defaults: {},
  ...o,
});

export const ACTIONS = {
  send: [
    A("send_verification_request", "Send verification request", "primary"),
    A("draft_followup", "Draft follow-up"),
  ],
  active: [
    A("resend_verification_request", "Resend request", "secondary", {
      enabled: false,
      blocked_reason: "Available in a few seconds",
    }),
    A("cancel_verification_request", "Cancel request"),
  ],
  failed: [
    A("draft_followup", "Draft follow-up", "primary"),
    A("reassign_case", "Reassign"),
  ],
  call: [
    A("start_callback", "Approve and start call", "primary", {
      expected_step: "verify",
    }),
    A("draft_followup", "Draft follow-up"),
    A("hold_case", "Hold", "ghost"),
  ],
  callfail: [
    A("start_callback", "Retry call", "primary", { expected_step: "callfail" }),
    A("reassign_case", "Reassign"),
    A("close_unresolved", "Close unresolved"),
    A("hold_case", "Hold", "ghost"),
  ],
};

export const QUESTIONS = [
  {
    id: "q1",
    text: "Did you place or approve the $2,840 order from Bayline Industrial Supply on Nov 8?",
  },
  {
    id: "q2",
    text: "Receiving logged two units at Dock 2 against PO-219 for one. Do you know who ordered the second unit?",
  },
];

const T0 = "2026-11-10T16:41:00Z";
export const idv = (
  status: IdentityStatus,
  o: Partial<VerificationView> = {},
): VerificationView => ({
  id: "IDV-1",
  case_id: "CHG-1042",
  channel: "otp",
  status,
  attempts: status === "failed" ? 3 : status === "verified" ? 1 : 0,
  max_attempts: 3,
  attempts_left: status === "failed" ? 0 : 3,
  sends: 1,
  sent_at: T0,
  last_sent_at:
    status === "requested" ? new Date(Date.now() - 18_000).toISOString() : T0,
  expires_at: "2026-11-10T16:51:00Z",
  resolved_at: status === "requested" ? null : "2026-11-10T16:43:00Z",
  ...o,
});

/** Cardholder-role demo control only. */
export const OUTBOX: OutboxView = {
  synthetic: true,
  label: "Synthetic phone · text message to ••0182",
  verification_id: "IDV-1",
  channel: "otp",
  code: "318406",
  attempts_left: 3,
  next_attempt_no: 1,
};

const LINES = {
  confirmed: [
    [
      "agent",
      "Hi Priya, this is Vera calling for Halden Finance. You verified your identity a moment ago with a code sent to your phone ending 0182. This call is recorded for the case.",
    ],
    ["agent", QUESTIONS[0].text],
    [
      "contact",
      "No. I didn’t place or approve that order. Luis Moreno handles equipment orders on his own card.",
    ],
    ["agent", QUESTIONS[1].text],
    [
      "contact",
      "Yes, Receiving logged a second unit at Dock 2. I didn’t order it.",
    ],
    ["agent", "Do you still have the card ending 4418?"],
    ["contact", "Yes. It’s in my wallet."],
  ],
  contradicted: [
    [
      "agent",
      "Hi Priya, this is Vera calling for Halden Finance. This call is recorded for the case.",
    ],
    ["agent", QUESTIONS[0].text],
    [
      "contact",
      "I might have approved something for Luis last week… I’m not sure it was this.",
    ],
    ["agent", QUESTIONS[1].text],
    ["contact", "I’m not sure. Receiving would know."],
  ],
  voicemail: [
    [
      "system",
      "Reached voicemail. Vera left a callback request with no case details.",
    ],
  ],
  no_answer: [["system", "No answer after 6 rings."]],
  incomplete: [
    [
      "agent",
      "Hi Priya, this is Vera calling for Halden Finance. This call is recorded for the case.",
    ],
    ["contact", "Hello? … [call dropped]"],
  ],
} satisfies Record<CallOutcome, string[][]>;

export const callFixture = (
  status: CallOutcome | "in_progress",
  shown?: number,
): CallbackDetail => {
  const src = LINES[status === "in_progress" ? "confirmed" : status];
  const lines = src
    .slice(0, shown ?? src.length)
    .map(([speaker, text], i) => ({ seq: i + 1, speaker, text }));
  const outcome = status === "in_progress" ? null : status;
  return {
    id: "CALL-1042",
    attempt: status === "no_answer" ? 2 : 1,
    status,
    target_record_id: "PRF-4418",
    target_field: "phone",
    target_version: 3,
    questions: QUESTIONS,
    result: outcome
      ? {
          result: outcome === "confirmed" ? "confirmed" : "failed",
          outcome,
          authorization_answer: outcome === "confirmed" ? "unauthorized" : null,
          answers:
            outcome === "confirmed"
              ? [
                  {
                    question_id: "q1",
                    answer: "Did not place or approve the order",
                    line_seq: 3,
                  },
                  {
                    question_id: "q2",
                    answer:
                      "Second unit received at Dock 2, not ordered by Priya",
                    line_seq: 5,
                  },
                ]
              : outcome === "contradicted"
                ? [
                    {
                      question_id: "q1",
                      answer: "Unsure whether she approved the order",
                      line_seq: 3,
                    },
                  ]
                : [],
        }
      : null,
    approved_by: "Sam Rivera",
    created_at: "2026-11-10T16:45:00Z",
    transcript: lines,
    notes: [],
  };
};
