'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { ApiError } from '@/api';

/** Client errors (403 role_forbidden, 404 route not deployed) are final; only transient failures retry. */
export const retryTransient = (n: number, e: Error) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;

/** TanStack Query provider. One client per browser session; created lazily so each request on the server gets its own. */
export function AppProviders({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [own] = useState(() => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: retryTransient } } }));
  return <QueryClientProvider client={client ?? own}>{children}</QueryClientProvider>;
}
