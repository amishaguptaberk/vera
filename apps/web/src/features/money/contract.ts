// Typed contract for the money / remediation / closure screens (VER-012-F8).
// Written from docs/spec/Vera_Handoff.md §3.2 (CaseView.credit / dispute / controls, ControlPlan, ClosureChecklist)
// and the VER-010 / VER-011 ticket descriptions. Neither backend module (money.py, closure.py) existed in its
// worktree when this was written; every field below that is not yet in src/api/schema.d.ts is OPTIONAL so the
// screens degrade honestly ("Not available yet") instead of inventing data. Align with the generated schema
// once the backends merge.
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

/** GET /api/cases/{id}/closure-checklist (VER-011). */
export type ClosureItem = {
  key: string;
  label: string;
  status: 'met' | 'unmet' | 'unknown';
  detail: string;
  owner: { id: string; name: string } | null;
  next_action: string | null;
  record_ids: string[];
};
export type ClosureChecklistBody = { case_id: string; items: ClosureItem[]; can_close?: boolean; will_monitor?: boolean };

/** GET /api/cases/{id}/executions (VER-010). */
export type ExecutionView = {
  execution_id: string;
  operation: string;
  status: string;
  idempotency_key: string;
  target?: string | null;
  result?: Record<string, unknown> | null;
};
export type ExecutionsBody = { executions: ExecutionView[] };
