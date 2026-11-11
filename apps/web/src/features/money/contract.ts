// Typed contract for the money / remediation / closure screens.
// Mirrors services/api/vera_api/money.py (ExecutionView, ExecutionList, MoneyView / CreditSummary /
// DisputeSummary / ControlsSummary, GET /remediation, GET /executions) and the closure feature
// (packages/domain/vera_domain/closure.py ChecklistItem / ClosureChecklist; services/api/vera_api/closure.py
// FinalMessageView, GET /closure-checklist, GET /final-message). The CaseView extensions below are OPTIONAL:
// the API does not serve them, and they are rendered only when present.
import type { CaseView } from '@/api';

export type CreditStatus = 'not_eligible' | 'eligible' | 'awaiting_approval' | 'approved' | 'issued' | 'checking' | 'finalized' | 'reversed';
export type DisputeStatus = 'not_prepared' | 'prepared' | 'ready_for_review' | 'ready_to_submit' | 'submitted' | 'failed' | 'accepted' | 'denied';
export type ControlsStatus = 'not_recommended' | 'recommended' | 'awaiting_approval' | 'approved' | 'applied' | 'declined';

export type CreditFact = { status: CreditStatus; label: string; why?: string; credit_id?: string | null; issued_at?: string | null };
export type DisputeFact = { status: DisputeStatus; label: string; applicable: boolean };
export type ControlsFact = { status: ControlsStatus; label: string; not_needed: boolean };

export type ControlPlanItem = {
  key: string;
  label: string;
  why: string;
  affects: string;
  effect: string;
  reversible: string;
  permission: string;
  record_id?: string | null;
};
/** Control plan: recommended controls with reason, scope, reversibility, permission and evidence. Not served by the API; rendered only when present. */
export type ControlPlanView = { plan_id: string; items: ControlPlanItem[]; requested?: string[]; approved?: string[] };

/** CaseView plus the money facts that are not in the generated schema. Rendered only when present. */
export type MoneyCaseView = CaseView & {
  credit?: CreditFact | null;
  dispute?: DisputeFact | null;
  controls?: ControlsFact | null;
  control_plan?: ControlPlanView | null;
  /** Final message draft (communication id + body) for the `final` step. Not served by the API; rendered only when present. */
  final_message?: { communication_id: string; to: string; body: string } | null;
};

/** GET /api/cases/{id}/closure-checklist (ChecklistItem). `owner` and `next_action` are rendered only when present. */
export type ClosureItem = {
  name: string;
  label: string;
  status: 'met' | 'unmet' | 'unknown';
  record_ids: string[];
  detail: string;
  owner?: { id: string; name: string } | null;
  next_action?: string | null;
};
export type ClosureChecklistBody = { case_id: string; ready: boolean; items: ClosureItem[] };

/** GET /api/cases/{id}/remediation (MoneyView). */
export type RemediationBody = {
  case_id: string;
  credit: { status: string; credit_id?: string | null; amount_cents?: number | null; currency?: string | null; issued_at?: string | null; simulated: boolean };
  dispute: {
    status: string;
    dispute_id?: string | null;
    submission_id?: string | null;
    submitted_at?: string | null;
    simulated: boolean;
    /** Dispute Packet Preparer output stored on the packet; never gates the track. */
    reason_code?: string | null;
    narrative?: { text: string; record_id: string; version: number; field: string }[];
    narrative_status?: 'pending' | 'ready' | 'failed' | null;
  };
  controls: { status: string; plan_id?: number | null; controls: string[]; applied: string[]; reason?: string | null; simulated: boolean };
};

/** GET /api/cases/{id}/executions (ExecutionView). */
export type ExecutionView = {
  id: number;
  adapter: string;
  operation: string;
  idempotency_key: string;
  status: string;
  attempts: number;
  error: string | null;
  simulated: boolean;
  created_at: string;
  updated_at: string;
};
export type ExecutionsBody = { case_id: string; executions: ExecutionView[] };

/** GET /api/cases/{id}/final-message (FinalMessageView; null when none drafted). */
export type FinalMessageBody = { message_id: string; status: string; body: string; created_at: string; updated_at: string; sent_at: string | null; execution_id: number | null } | null;
