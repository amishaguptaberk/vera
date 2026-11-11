import { queryOptions, useQuery } from '@tanstack/react-query';
import { CASE_POLL_MS, apiGet, caseKey } from '@/api';
import type { ClosureChecklistBody, ExecutionsBody, FinalMessageBody, RemediationBody } from './contract';

// Keys live under caseKey(id), so runCommand's invalidation refreshes them after every command.
export const closureChecklistQuery = (id: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'closure-checklist'] as const,
    queryFn: ({ signal }) => apiGet<ClosureChecklistBody>(`/cases/${encodeURIComponent(id)}/closure-checklist`, signal),
    retry: false,
  });

export const executionsQuery = (id: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'executions'] as const,
    queryFn: ({ signal }) => apiGet<ExecutionsBody>(`/cases/${encodeURIComponent(id)}/executions`, signal),
    retry: false,
  });

export const remediationQuery = (id: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'remediation'] as const,
    queryFn: ({ signal }) => apiGet<RemediationBody>(`/cases/${encodeURIComponent(id)}/remediation`, signal),
    retry: false,
    // The dispute narrative is prepared by a worker job: refresh until it is ready or failed.
    refetchInterval: (q) => (q.state.data?.dispute.narrative_status === 'pending' ? CASE_POLL_MS : false),
  });

export const finalMessageQuery = (id: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'final-message'] as const,
    queryFn: ({ signal }) => apiGet<FinalMessageBody>(`/cases/${encodeURIComponent(id)}/final-message`, signal),
    retry: false,
  });

export const useRemediation = (id: string, enabled = true) => useQuery({ ...remediationQuery(id), enabled });
export const useFinalMessage = (id: string, enabled = true) => useQuery({ ...finalMessageQuery(id), enabled });
export const useClosureChecklist = (id: string, enabled = true) => useQuery({ ...closureChecklistQuery(id), enabled });
export const useExecutions = (id: string, enabled = true) => useQuery({ ...executionsQuery(id), enabled });
