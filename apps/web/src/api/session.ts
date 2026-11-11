import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost } from './client';

import type { components } from './schema';

// Generated from the backend OpenAPI (npm run dump:api && npm run gen:api).
export type Role = components['schemas']['Role'];
export type SessionUser = components['schemas']['Person'];
export type Session = components['schemas']['SessionOut'];

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
 * Only the session endpoint is called: the session is refetched afterwards, nothing else is.
 */
export function useSwitchRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (role: Role) => apiPost<Session>('/session/role', { role }),
    onSuccess: async (session) => {
      queryClient.setQueryData(sessionKey, session);
      await queryClient.invalidateQueries({ queryKey: sessionKey });
      // Case views and available actions are scoped to the active role by the server.
      await queryClient.invalidateQueries({ queryKey: ['case'] });
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
