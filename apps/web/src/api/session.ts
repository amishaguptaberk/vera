import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';

// Hand-written for now: src/api/schema.d.ts is still a placeholder. F2 replaces these with the generated
// types (SessionOut, RoleIn, Role in services/api/vera_api/app.py).
export type Role = 'analyst' | 'ops_admin' | 'reviewer' | 'card_admin' | 'cardholder';
export type SessionUser = { id: string; name: string };
export type Session = {
  user: SessionUser;
  active_role: Role;
  roles: Role[];
  environment: string;
};

export const sessionKey = ['session'] as const;

export const sessionQuery = queryOptions({
  queryKey: sessionKey,
  queryFn: ({ signal }) => apiGet<Session>('/session', signal),
  retry: false,
});

export function useSession() {
  return useQuery(sessionQuery);
}

/**
 * Switch the demo role view. The server picks the user and sets the cookie; the client never sends a user.
 * Only the session endpoint is called (US-K02): the session is refetched afterwards, nothing else is.
 */
export function useSwitchRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (role: Role) => apiPost<Session>('/session/role', { role }),
    onSuccess: async (session) => {
      queryClient.setQueryData(sessionKey, session);
      await queryClient.invalidateQueries({ queryKey: sessionKey });
    },
  });
}

/** Demo-only reset of the synthetic environment. */
export function useResetDemo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<unknown>('/demo/reset'),
    onSuccess: () => queryClient.invalidateQueries(),
  });
}
