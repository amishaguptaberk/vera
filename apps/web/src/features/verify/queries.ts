import { queryOptions } from '@tanstack/react-query';
import { ApiError, apiGet, apiPost, caseKey } from '@/api';
import type { CallbackDetail, CallbackView, OutboxView, VerificationView } from './contract';

const noRetry4xx = (n: number, e: unknown) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;
const enc = encodeURIComponent;

/** Polling while a request or call is live (no SSE yet). */
export const LIVE_POLL_MS = 1000;

/** Staff list. Keys sit under caseKey(id) so runCommand's invalidation refreshes them. */
export const verificationsQuery = (caseId: string) =>
  queryOptions({
    queryKey: [...caseKey(caseId), 'verifications'],
    queryFn: ({ signal }) => apiGet<VerificationView[]>(`/cases/${enc(caseId)}/verifications`, signal),
    retry: noRetry4xx,
    refetchInterval: (q) => (q.state.data?.some((v) => v.status === 'requested') ? LIVE_POLL_MS * 3 : false),
  });

export const callbacksQuery = (caseId: string) =>
  queryOptions({
    queryKey: [...caseKey(caseId), 'callbacks'],
    queryFn: ({ signal }) => apiGet<CallbackView[]>(`/cases/${enc(caseId)}/callbacks`, signal),
    retry: noRetry4xx,
    refetchInterval: (q) => (q.state.data?.some((c) => c.status === 'in_progress') ? LIVE_POLL_MS : false),
  });

export const callbackDetailQuery = (caseId: string, callbackId: string) =>
  queryOptions({
    queryKey: [...caseKey(caseId), 'callbacks', callbackId],
    queryFn: ({ signal }) => apiGet<CallbackDetail>(`/cases/${enc(caseId)}/callbacks/${enc(callbackId)}`, signal),
    retry: noRetry4xx,
    refetchInterval: (q) => (q.state.data?.status === 'in_progress' ? LIVE_POLL_MS : false),
  });

/** Cardholder role only: the simulated message for the synthetic demo control. Never used by staff views. */
export const outboxQuery = (caseId: string, verificationId: string) =>
  queryOptions({
    queryKey: [...caseKey(caseId), 'outbox', verificationId],
    queryFn: ({ signal }) => apiGet<OutboxView>(`/verifications/${enc(verificationId)}/outbox`, signal),
    retry: false,
  });

/** Synthetic demo: choose the next simulated call outcome. */
export const setNextCallOutcome = (outcome: string) => apiPost<{ outcome: string }>('/demo/callback-outcome', { outcome });

/** A 404 without a domain error code means the route is not deployed yet. */
export const notDeployed = (e: unknown) => e instanceof ApiError && e.status === 404 && e.code === 'unknown_error';

/** Honest error copy: a not-yet-deployed route says so; anything else shows the server's message. */
export const errorText = (e: unknown, notYet: string) => (notDeployed(e) ? notYet : e instanceof Error ? e.message : 'Something went wrong.');
