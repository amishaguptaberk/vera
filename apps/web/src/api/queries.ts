import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query';
import { apiGet } from './client';
import type { components } from './schema';

type S = components['schemas'];
export type QueueRow = S['QueueRow'];
export type CaseView = S['CaseView'];
export type ActionView = S['ActionView'];
export type BlockedAction = S['BlockedAction'];
export type PolicyView = S['PolicyView'];
/**
 * The summary body. The generated type is the shape on this base; the endpoint is moving to named metrics
 * `{amount_cents, currency, count, basis, definition}`, so the body is read as an open record and
 * interpreted by the feature-layer adapter (features/cases/summary.ts).
 */
export type SummaryBody = Record<string, unknown>;

export const casesKey = ['cases'] as const;
export const caseKey = (id: string) => ['case', id] as const;

export const casesListQuery = queryOptions({
  queryKey: [...casesKey, 'list'],
  queryFn: ({ signal }) => apiGet<QueueRow[]>('/cases', signal),
  placeholderData: keepPreviousData,
});

export const casesSummaryQuery = queryOptions({
  queryKey: [...casesKey, 'summary'],
  queryFn: ({ signal }) => apiGet<SummaryBody>('/cases/summary', signal),
  placeholderData: keepPreviousData,
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
