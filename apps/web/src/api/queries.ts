import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query';
import { ApiError, apiGet } from './client';
import type { components } from './schema';

type S = components['schemas'];
export type QueueRow = S['QueueRow'];
export type CaseView = S['CaseView'];
export type ActionView = S['ActionView'];
export type BlockedAction = S['BlockedAction'];
export type PolicyView = S['PolicyView'];
/** Summary: named metrics `{amount_cents, currency, count, basis, definition}`; read via features/cases/summary.ts. */
export type SummaryBody = S['Summary'] | Record<string, unknown>;

export const casesKey = ['cases'] as const;
/** Client errors (403 role_forbidden, 404) are final; only transient failures retry. */
const retryTransient = (n: number, e: unknown) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;
export const caseKey = (id: string) => ['case', id] as const;

export const casesListQuery = queryOptions({
  queryKey: [...casesKey, 'list'],
  queryFn: ({ signal }) => apiGet<QueueRow[]>('/cases', signal),
  placeholderData: keepPreviousData,
  retry: retryTransient,
});

export const casesSummaryQuery = queryOptions({
  queryKey: [...casesKey, 'summary'],
  queryFn: ({ signal }) => apiGet<SummaryBody>('/cases/summary', signal),
  placeholderData: keepPreviousData,
  retry: retryTransient,
});

/** Polling interval for case freshness: there is no SSE endpoint yet. Paused while the tab is hidden (TanStack default). */
export const CASE_POLL_MS = 3000;

export const caseViewQuery = (id: string) =>
  queryOptions({
    queryKey: caseKey(id),
    queryFn: ({ signal }) => apiGet<CaseView>(`/cases/${encodeURIComponent(id)}`, signal),
    refetchInterval: CASE_POLL_MS,
    retry: false,
  });

export const availableActionsQuery = (id: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'available-actions'],
    queryFn: ({ signal }) => apiGet<ActionView[]>(`/cases/${encodeURIComponent(id)}/available-actions`, signal),
  });

export const policyQuery = (policyId: string) =>
  queryOptions({
    queryKey: ['policy', policyId],
    queryFn: ({ signal }) => apiGet<Record<string, unknown>>(`/policies/${encodeURIComponent(policyId)}`, signal),
  });

export const useCases = () => useQuery(casesListQuery);
export const useCasesSummary = () => useQuery(casesSummaryQuery);
export const useCaseView = (id: string) => useQuery(caseViewQuery(id));

export type EvidenceRegister = S['EvidenceRegister'];
export type RecordDetail = S['RecordDetail'];
export type RunOut = S['RunOut'];
export type StepOut = S['StepOut'];
export type FindingView = S['FindingView'];

export const evidenceQuery = (id: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'evidence'],
    queryFn: ({ signal }) => apiGet<EvidenceRegister>(`/cases/${encodeURIComponent(id)}/evidence`, signal),
    refetchInterval: CASE_POLL_MS,
    placeholderData: keepPreviousData,
  });

export const evidenceRecordQuery = (id: string, recordId: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'evidence', recordId],
    queryFn: ({ signal }) => apiGet<RecordDetail>(`/cases/${encodeURIComponent(id)}/evidence/${encodeURIComponent(recordId)}`, signal),
    retry: false,
  });

/** Runs poll every 2s while any step is queued or running, else at the case cadence. */
export const RUNS_ACTIVE_POLL_MS = 2000;
const ACTIVE = new Set(['queued', 'running', 'pending']);
export const runsActive = (runs: readonly RunOut[] | undefined) =>
  !!runs?.some((r) => ACTIVE.has(r.status) || r.steps.some((s) => ACTIVE.has(s.status)));
export const runsQuery = (id: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'runs'],
    queryFn: ({ signal }) => apiGet<RunOut[]>(`/cases/${encodeURIComponent(id)}/runs`, signal),
    refetchInterval: (q) => (runsActive(q.state.data) ? RUNS_ACTIVE_POLL_MS : CASE_POLL_MS),
    placeholderData: keepPreviousData,
  });

export type ActivityEvent = S['ActivityEvent'];
export type ActivityBody = S['ActivityFeed'];
export type UsersBody = S['AssignableUsers'];
export type FilterCounts = S['FilterCounts'];
export const activityQuery = (id: string) =>
  queryOptions({
    queryKey: [...caseKey(id), 'activity'],
    queryFn: ({ signal }) => apiGet<ActivityBody>(`/cases/${encodeURIComponent(id)}/activity`, signal),
    refetchInterval: CASE_POLL_MS,
    placeholderData: keepPreviousData,
    retry: false,
  });
export const usersQuery = queryOptions({
  queryKey: ['users'],
  queryFn: ({ signal }) => apiGet<UsersBody>('/users?assignable=true', signal),
  retry: false,
  staleTime: 60_000,
});

/** GET /api/cases/filter-counts → {all, due_today, overdue, mine, cardholder, reviewer} (staff only). */
export const filterCountsQuery = queryOptions({
  queryKey: [...casesKey, 'filter-counts'],
  queryFn: ({ signal }) => apiGet<FilterCounts>('/cases/filter-counts', signal),
  placeholderData: keepPreviousData,
  retry: retryTransient,
});
