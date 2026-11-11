// Typed contract for the money / remediation / closure screens (VER-012-F8).
// Aligned (00:22) with the VER-010 worktree (services/api/vera_api/money.py: ExecutionView, ExecutionList,
// MoneyView / CreditSummary / DisputeSummary / ControlsSummary, GET /remediation, GET /executions) and the VER-011
// worktree (packages/domain/vera_domain/closure.py ChecklistItem / ClosureChecklist; closure.py FinalMessageView,
// GET /closure-checklist, GET /final-message). CaseView extensions from Handoff §3.2 stay OPTIONAL (not served yet).
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
/** GAP: Handoff §2 ControlPlan data ("recommended controls with reason, scope, reversibility, permission, evidence"). */
export type ControlPlanView = { plan_id: string; items: ControlPlanItem[]; requested?: string[]; approved?: string[] };

/** CaseView plus the Handoff §3.2 money facts not yet in the generated schema. */
export type MoneyCaseView = CaseView & {
  credit?: CreditFact | null;
  dispute?: DisputeFact | null;
  controls?: ControlsFact | null;
  control_plan?: ControlPlanView | null;
  /** GAP: final message draft (communication id + body) for the `final` step. */
  final_message?: { communication_id: string; to: string; body: string } | null;
};

/** GET /api/cases/{id}/closure-checklist (VER-011 ChecklistItem). `owner` / `next_action` are GAPS (not served yet). */
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

/** GET /api/cases/{id}/remediation (VER-010 MoneyView). */
export type RemediationBody = {
  case_id: string;
  credit: { status: string; credit_id?: string | null; amount_cents?: number | null; currency?: string | null; issued_at?: string | null; simulated: boolean };
  dispute: { status: string; dispute_id?: string | null; submission_id?: string | null; submitted_at?: string | null; simulated: boolean };
  controls: { status: string; plan_id?: number | null; controls: string[]; applied: string[]; reason?: string | null; simulated: boolean };
};

/** GET /api/cases/{id}/executions (VER-010 ExecutionView). */
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

/** GET /api/cases/{id}/final-message (VER-011 FinalMessageView; null when none drafted). */
export type FinalMessageBody = { message_id: string; status: string; body: string; created_at: string; updated_at: string; sent_at: string | null; execution_id: number | null } | null;
