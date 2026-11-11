'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

/** TanStack Query provider. One client per browser session; created lazily so each request on the server gets its own. */
export function AppProviders({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [own] = useState(() => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } }));
  return <QueryClientProvider client={client ?? own}>{children}</QueryClientProvider>;
}
