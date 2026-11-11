import type { Metadata } from 'next';
import { AppProviders, AppShell } from '@/features/shell';
import '@/design-system/tokens.css';
import '@/design-system/base.css';

export const metadata: Metadata = { title: 'Vera' };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppProviders>
          <AppShell>{children}</AppShell>
        </AppProviders>
      </body>
    </html>
  );
}
