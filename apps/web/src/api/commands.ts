import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { ApiError, apiPost } from './client';
import { caseKey, casesKey, type ActionView, type CaseView } from './queries';
import type { components } from './schema';

export type CommandOut = components['schemas']['vera_api__app__CommandOut'];
export type UserPayload = Record<string, unknown>;

/**
 * Run one server-offered action (docs/frontend-architecture.md `runCommand`).
 * The idempotency key is ECHOED from the action; the client never builds one. The expected version is the
 * version of the case view the action came from. No retries: on 409 `stale_case_version` the case is
 * refetched and the typed error is rethrown for the UI.
 */
export async function runCommand(
  queryClient: QueryClient,
  caseId: string,
  caseVersion: number,
  action: Pick<ActionView, 'command' | 'idempotency_key' | 'payload_defaults'>,
  userPayload: UserPayload = {},
): Promise<CommandOut> {
  try {
    const out = await apiPost<CommandOut>(`/cases/${encodeURIComponent(caseId)}/commands/${encodeURIComponent(action.command)}`, {
      expected_case_version: caseVersion,
      idempotency_key: action.idempotency_key,
      payload: { ...action.payload_defaults, ...userPayload },
    });
    queryClient.setQueryData<CaseView>(caseKey(caseId), out.case);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: caseKey(caseId) }),
      queryClient.invalidateQueries({ queryKey: casesKey }),
    ]);
    return out;
  } catch (err) {
    if (err instanceof ApiError && err.code === 'stale_case_version') {
      await queryClient.invalidateQueries({ queryKey: caseKey(caseId) });
    }
    throw err;
  }
}

export type RunCommandVars = { action: ActionView; caseVersion: number; payload?: UserPayload };

export function useRunCommand(caseId: string) {
  const queryClient = useQueryClient();
  return useMutation<CommandOut, ApiError, RunCommandVars>({
    mutationFn: ({ action, caseVersion, payload }) => runCommand(queryClient, caseId, caseVersion, action, payload),
    retry: false,
  });
}

export type MaterialChangeOut = components['schemas']['MaterialChangeOut'];

/** Demo only (synthetic env): the server applies a new version of a source record. Refreshes the case. */
export function useMaterialChange(caseId: string) {
  const queryClient = useQueryClient();
  return useMutation<MaterialChangeOut, ApiError, void>({
    mutationFn: () => apiPost<MaterialChangeOut>('/demo/material-change', { case_id: caseId }),
    retry: false,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: caseKey(caseId) }),
  });
}
