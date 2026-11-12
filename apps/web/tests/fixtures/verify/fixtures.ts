// Contract-conforming fixtures for src/features/verify/contract.ts. Test-only: never imported from src/.
import type { ActionView, CaseView } from "@/api";
import type {
  CallbackDetail,
  IdentityStatus,
  OutboxView,
  VerificationView,
} from "@/features/verify/contract";
import intake from "../../parity/fixtures/case-CHG-1042-intake.json";

export const CODE = "482913";

const base = intake as unknown as CaseView;
export const act = (
  command: string,
  o: Partial<ActionView> = {},
): ActionView => ({
  ...(base.available_actions[0] as ActionView),
  command,
  label: command,
  enabled: true,
  blocked_reason: null,
  idempotency_key: `srv:${command}:1`,
  payload_defaults: {},
  ...o,
});
export const caseWith = (actions: ActionView[]): CaseView => ({
  ...base,
  available_actions: actions,
  blocked_actions: [],
});

export const verification = (
  status: IdentityStatus,
  o: Partial<VerificationView> = {},
): VerificationView => ({
  id: "IDV-0001",
  case_id: "CHG-1042",
  channel: "otp",
  status,
  attempts: 0,
  max_attempts: 3,
  attempts_left: 3,
  sends: 1,
  sent_at: "2026-11-10T15:00:00Z",
  last_sent_at: "2026-11-10T15:00:00Z",
  expires_at: "2026-11-10T15:10:00Z",
  resolved_at: status === "requested" ? null : "2026-11-10T15:02:00Z",
  ...o,
});

export const outbox: OutboxView = {
  synthetic: true,
  label: "Synthetic demo: simulated message to the cardholder's device",
  verification_id: "IDV-0001",
  channel: "otp",
  code: CODE,
  attempts_left: 3,
  next_attempt_no: 1,
};

export const call = (o: Partial<CallbackDetail> = {}): CallbackDetail => ({
  id: "CB-0001",
  attempt: 1,
  status: "in_progress",
  target_record_id: "PRF-4418",
  target_field: "phone",
  target_version: 1,
  questions: [
    { id: "q1", text: "Did you place or approve the Northstar order?" },
  ],
  result: null,
  approved_by: "Sam Rivera",
  created_at: "2026-11-10T15:05:00Z",
  transcript: [],
  notes: [],
  ...o,
});
