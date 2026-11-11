import { keepPreviousData, queryOptions, useMutation } from '@tanstack/react-query';
import { ApiError, apiGet, apiPost, caseKey } from '@/api';
import type { AskRequest, AskResponse, DecisionPacket } from './contract';

/** GET /api/cases/{id}/decision-packet?version= — under caseKey so runCommand refreshes it. 404 = no packet / not deployed. */
export const decisionPacketQuery = (id: string, version?: number) =>
  queryOptions({
    queryKey: [...caseKey(id), 'decision-packet', version ?? 'current'],
    queryFn: ({ signal }) =>
      apiGet<DecisionPacket>(`/cases/${encodeURIComponent(id)}/decision-packet${version != null ? `?version=${version}` : ''}`, signal),
    placeholderData: keepPreviousData,
    retry: false,
  });

/** POST /api/cases/{id}/ask — read-only; nothing is invalidated because nothing changes. */
export function useAsk(caseId: string) {
  return useMutation<AskResponse, ApiError, AskRequest>({
    mutationFn: (body) => apiPost<AskResponse>(`/cases/${encodeURIComponent(caseId)}/ask`, body),
    retry: false,
  });
}

export const isNotAvailable = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 405);
