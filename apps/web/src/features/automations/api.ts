import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiGet, apiPost } from '@/api/client';
import { paths, type AutomationAction, type PolicyDetail, type SpecialistsView, type WorkflowDetail } from './contract';

export const automationsKey = ['automations'] as const;
const retryTransient = (n: number, e: unknown) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;

export const useWorkflow = (id: string) =>
  useQuery({ queryKey: [...automationsKey, 'workflow', id], queryFn: ({ signal }) => apiGet<WorkflowDetail>(paths.workflow(id), signal), retry: retryTransient });

export const useSpecialists = () =>
  useQuery({ queryKey: [...automationsKey, 'specialists'], queryFn: ({ signal }) => apiGet<SpecialistsView>(paths.specialists(), signal), retry: retryTransient });

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
      apiPost(paths.command(action.command), { idempotency_key: action.idempotency_key, payload: { ...(action.payload_defaults ?? {}), ...(payload ?? {}) } }),
    retry: false,
    onSettled: () => qc.invalidateQueries({ queryKey: automationsKey }),
  });
}
