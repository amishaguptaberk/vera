import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiGet, apiPost } from '@/api/client';
import { caseKey } from '@/api/queries';
import type { CardholderRequest, CardholderRequestList, CommunicationDetail, CommunicationItem, ResponseIn, ResponseOut } from './contract';

// Keys live under caseKey(id) so runCommand's invalidation refreshes them after every command.
export const communicationsKey = (caseId: string) => [...caseKey(caseId), 'communications'] as const;
export const communicationKey = (caseId: string, itemId: string) => [...communicationsKey(caseId), itemId] as const;
export const requestKey = (requestId: string) => ['request', requestId] as const;
export const myRequestsKey = ['requests', 'mine'] as const;

export const communicationsQuery = (caseId: string) =>
  queryOptions({
    queryKey: communicationsKey(caseId),
    queryFn: ({ signal }) => apiGet<CommunicationItem[]>(`/cases/${encodeURIComponent(caseId)}/communications`, signal),
  });

export const communicationQuery = (caseId: string, itemId: string) =>
  queryOptions({
    queryKey: communicationKey(caseId, itemId),
    queryFn: ({ signal }) => apiGet<CommunicationDetail>(`/cases/${encodeURIComponent(caseId)}/communications/${encodeURIComponent(itemId)}`, signal),
  });

export const cardholderRequestQuery = (requestId: string) =>
  queryOptions({
    queryKey: requestKey(requestId),
    queryFn: ({ signal }) => apiGet<CardholderRequest>(`/requests/${encodeURIComponent(requestId)}`, signal),
  });

export const myRequestsQuery = queryOptions({
  queryKey: myRequestsKey,
  queryFn: ({ signal }) => apiGet<CardholderRequestList>('/requests?mine=true', signal),
});

export const useCommunications = (caseId: string) => useQuery(communicationsQuery(caseId));
// Polls while the Response Reviewer is still working on the reply.
export const useCommunication = (caseId: string, itemId: string | null) =>
  useQuery({ ...communicationQuery(caseId, itemId ?? ''), enabled: !!itemId, refetchInterval: (q) => (q.state.data?.review_suggestion?.status === 'pending' ? 2000 : false) });
export const useCardholderRequest = (requestId: string) => useQuery(cardholderRequestQuery(requestId));
export const useMyRequests = () => useQuery(myRequestsQuery);

export function useSubmitResponse(requestId: string) {
  const qc = useQueryClient();
  return useMutation<ResponseOut, ApiError, ResponseIn>({
    mutationFn: (body) => apiPost<ResponseOut>(`/requests/${encodeURIComponent(requestId)}/responses`, body),
    retry: false,
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: requestKey(requestId) }), qc.invalidateQueries({ queryKey: myRequestsKey })]),
  });
}

/** A 404 without a typed error body means the route is not deployed yet (FastAPI's default {"detail": "Not Found"}). */
export const isNotDeployed = (e: unknown) => e instanceof ApiError && e.status === 404 && e.code === 'unknown_error';
