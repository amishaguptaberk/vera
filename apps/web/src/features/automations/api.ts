import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiGet, apiPost } from '@/api/client';
import { paths, type AutomationAction, type PolicyDetail, type SpecialistOut, type SpecialistsView, type WorkflowDetail, type WorkflowOut } from './contract';

export const automationsKey = ['automations'] as const;
const retryTransient = (n: number, e: unknown) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;

export const useWorkflow = (id: string) =>
  useQuery({ queryKey: [...automationsKey, 'workflow', id], queryFn: async ({ signal }) => fromWorkflowOut(await apiGet<WorkflowOut | WorkflowDetail>(paths.workflow(id), signal)), retry: retryTransient });

export const useSpecialists = () =>
  useQuery({ queryKey: [...automationsKey, 'specialists'], queryFn: async ({ signal }) => fromSpecialistsOut(await apiGet<SpecialistOut[] | SpecialistsView>(paths.specialists(), signal)), retry: retryTransient });

export const usePolicy = (id: string, version: number | null) =>
  useQuery({
    queryKey: [...automationsKey, 'policy', id, version],
    queryFn: ({ signal }) => apiGet<PolicyDetail>(version == null ? paths.policy(id) : paths.policyVersion(id, version), signal),
    retry: retryTransient,
  });

/** 404 from a not-yet-deployed endpoint: the screen shows its layout with "Not available yet". */
export const isNotAvailable = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 405);

export type AutomationCommandVars = { action: AutomationAction; payload?: Record<string, unknown> };

/**
 * Run one server-offered automation command. The idempotency key is echoed from the action; the client never
 * builds one. No retries. All automation reads are refetched afterwards (validation and checks come from the server).
 */
export function useAutomationCommand() {
  const qc = useQueryClient();
  return useMutation<unknown, ApiError, AutomationCommandVars>({
    mutationFn: ({ action, payload }) =>
      apiPost(paths.command(action.command), { idempotency_key: action.idempotency_key, expected_version: action.expected_version, payload: { ...(action.payload_defaults ?? {}), ...(payload ?? {}) } }),
    retry: false,
    onSettled: () => qc.invalidateQueries({ queryKey: automationsKey }),
  });
}

/** Map the API wire shape onto the screen contract. Only the active version's graph is served. */
export function fromWorkflowOut(raw: WorkflowOut | WorkflowDetail): WorkflowDetail {
  if ('pinned_cases' in raw) return raw;
  return {
    workflow_id: raw.workflow_id,
    name: raw.name,
    active_version: raw.active_version,
    versions: raw.versions.map((v) => ({
      version: v.version,
      status: 'published' as const,
      revision: 0,
      based_on: null,
      graph: v.version === raw.active_version ? raw.graph : { nodes: [], edges: [] },
      violations: [],
      checks: null,
      published_at: v.created_at,
    })),
    draft: raw.draft
      ? {
          version: raw.draft.version,
          status: 'draft',
          revision: raw.draft.revision,
          based_on: raw.draft.from_version,
          graph: raw.draft.graph,
          violations: raw.draft.validation,
          checks: raw.draft.latest_check ? { ...raw.draft.latest_check, run_id: String(raw.draft.latest_check.run_id) } : null,
        }
      : null,
    pinned_cases: raw.used_by.map((c) => ({ case_id: c.case_id, version: c.workflow_version })),
    rules: raw.rules ?? {},
    available_actions: raw.available_actions ?? [],
  };
}

const str = (v: unknown) => (typeof v === 'string' ? v : '');
const strs = (v: unknown) => (Array.isArray(v) ? v.map(String) : []);

export function fromSpecialistsOut(raw: SpecialistOut[] | SpecialistsView): SpecialistsView {
  if (!Array.isArray(raw)) return raw;
  return {
    available_actions: [],
    specialists: raw.map((r) => ({
      specialist_id: r.specialist_id,
      name: str(r.fields.name) || r.specialist_id,
      kind_label: 'Finance specialist',
      purpose: str(r.fields.purpose),
      records: strs(r.fields.records),
      tools: strs(r.fields.tools),
      output_type: str(r.fields.output_type),
      handoff: str(r.fields.handoff),
      execution_mode: r.fields.execution_mode === 'live' ? 'live' : 'replay',
      status: r.status === 'draft' ? 'draft' : 'published',
      required_control: false,
      used_in: [],
      prohibitions: [],
      can_configure: [],
      revision: r.revision,
      available_actions: [],
    })),
  };
}
