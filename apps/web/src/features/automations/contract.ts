// Typed contract for the Automations screens (VER-012-F10 against VER-014).
// Graph, Violation, ScenarioResult and the command payloads mirror the pydantic models in
// packages/domain/vera_domain/automations.py (VER-014 worktree). The read-endpoint envelopes
// (WorkflowDetail, SpecialistsView, PolicyDetail draft fields) are written from Handoff §3.2 because
// services/api/vera_api/automations.py did not exist yet when this was written — align on merge.

export type NodeKind =
  | 'trigger'
  | 'finance_specialist'
  | 'human_checkpoint'
  | 'policy_check'
  | 'communication'
  | 'verification'
  | 'decision'
  | 'remediation'
  | 'close_case';

/** Visual only: never read for behaviour. */
export type Category = 'trigger' | 'agent' | 'policy' | 'checkpoint' | 'action';

export type WorkflowNode = {
  key: string;
  kind: NodeKind;
  label: string;
  category: Category;
  outcomes: string[];
  failure_outcomes: string[];
  analyst_started: boolean;
  money_affecting: boolean;
  parallel: boolean;
  provides: string[];
  specialist_id: string | null;
};

export type WorkflowEdge = { source: string; target: string; outcome: string; max: number | null };

export type Graph = { nodes: WorkflowNode[]; edges: WorkflowEdge[] };

export type Violation = { rule: number; rule_name: string; node_ids: string[]; message: string };

export type TraceStep = { step: number; node: string; kind: string; outcome: string | null };

export type ScenarioResult = {
  scenario: string;
  passed: boolean;
  last_step: string | null;
  steps: number;
  reason: string | null;
  trace: TraceStep[];
};

export type CheckRun = { run_id: string; graph_hash: string; passed: boolean; results: ScenarioResult[] };

/** A server-offered command (same shape as the case ActionView: the key is echoed, never built). */
export type AutomationAction = {
  command: string;
  label: string;
  enabled: boolean;
  blocked_reason?: string | null;
  idempotency_key: string;
  /** Echoed into CommandIn.expected_version (VER-014 envelope). */
  expected_version?: number;
  payload_defaults?: Record<string, unknown>;
};

export type WorkflowVersion = {
  version: number;
  status: 'published' | 'draft' | 'discarded';
  revision: number;
  based_on: number | null;
  graph: Graph;
  /** Validation rules 1-9 as evaluated by the server. Never computed client-side. */
  violations: Violation[];
  /** Latest check run for this graph, or null if checks have not run. */
  checks: CheckRun | null;
  published_at?: string | null;
};

export type WorkflowDetail = {
  workflow_id: string;
  name: string;
  active_version: number;
  versions: WorkflowVersion[];
  draft: WorkflowVersion | null;
  /** Cases pinned to a version, e.g. CHG-1042 → 3. */
  pinned_cases: { case_id: string; version: number }[];
  /** Validation rule names (1-9) for the validation list. */
  rules: Record<string, string>;
  available_actions: AutomationAction[];
};

export type SpecialistView = {
  specialist_id: string;
  name: string;
  kind_label: string;
  purpose: string;
  records: string[];
  tools: string[];
  output_type: string;
  handoff: string;
  execution_mode: 'replay' | 'live';
  status: 'draft' | 'published';
  required_control: boolean;
  used_in: string[];
  prohibitions: string[];
  can_configure: string[];
  revision: number;
  available_actions: AutomationAction[];
};

export type SpecialistsView = {
  specialists: SpecialistView[];
  available_actions: AutomationAction[];
  /** Server-owned option lists for the new-specialist form (approved tool library etc.). */
  options?: { records: string[]; tools: string[]; outputs: string[]; handoffs: string[] };
  /** "Restricted by Vera" list (copy owned by the server). */
  restricted?: string[];
};

export type PolicyRule = {
  id: string;
  group: string;
  label: string;
  predicate: string;
  params: Record<string, unknown>;
  effect: 'ineligible' | 'blocked' | 'needs_evidence';
  code: string;
  fail_label: string;
};

/** GET /api/policies/{id} and /versions/{v} (on main). */
export type PolicyDetail = {
  policy_id: string;
  version: number;
  versions: number[];
  rules: PolicyRule[];
  created_at: string;
  available_actions?: AutomationAction[];
};

export const WORKFLOW_ID = 'card-dispute';
export const POLICY_ID = 'card-charge-investigation';

export const paths = {
  workflow: (id: string) => `/automations/workflows/${encodeURIComponent(id)}`,
  specialists: () => '/automations/specialists',
  policy: (id: string) => `/policies/${encodeURIComponent(id)}`,
  policyVersion: (id: string, v: number) => `/policies/${encodeURIComponent(id)}/versions/${v}`,
  command: (name: string) => `/automations/commands/${encodeURIComponent(name)}`,
};

// ---- Wire shapes of services/api/vera_api/automations.py (VER-014, read at 00:26) ----------------------------

export type WorkflowOut = {
  workflow_id: string;
  name: string;
  active_version: number;
  graph: Graph;
  versions: { version: number; graph_hash: string; published_by: string; reason: string; created_at: string }[];
  draft: {
    version: number;
    from_version: number;
    revision: number;
    graph: Graph;
    graph_hash: string;
    validation: Violation[];
    latest_check: (Omit<CheckRun, 'run_id'> & { run_id: number | string; created_at: string }) | null;
  } | null;
  used_by: { case_id: string; workflow_version: number; policy_version: number }[];
  /** Not in VER-014 yet (GAP): server-offered commands with echoed idempotency key + expected_version. */
  available_actions?: AutomationAction[];
  rules?: Record<string, string>;
};

export type SpecialistOut = { specialist_id: string; status: string; revision: number; fields: Record<string, unknown> };
