import { queryOptions, useQuery } from '@tanstack/react-query';
import { apiGet, caseKey } from '@/api';
import type { ClosureChecklistBody, ExecutionsBody } from './contract';

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

export const useClosureChecklist = (id: string, enabled = true) => useQuery({ ...closureChecklistQuery(id), enabled });
export const useExecutions = (id: string, enabled = true) => useQuery({ ...executionsQuery(id), enabled });
