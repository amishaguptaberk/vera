'use client';

import { useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { useSession } from '@/api';
import { Banner, Skeleton } from '@/design-system/primitives';
import { viewForRole } from './role-view';

/** Where a role lands (prototype `setView`): analyst → queue, reviewer / card admin → Approvals. */
export const LANDING: Record<'analyst' | 'reviewer', string> = { analyst: '/cases', reviewer: '/approvals' };

/**
 * Role-specific landing. The cardholder lands on their own request page; which request that is comes from the
 * server (`cardholder` slot resolves it) — there is no hardcoded case or request id.
 */
export function Landing({ cardholder }: { cardholder: ReactNode }) {
  const router = useRouter();
  const session = useSession();
  const view = session.data ? viewForRole(session.data.active_role) : null;
  const target = view === 'analyst' || view === 'reviewer' ? LANDING[view] : null;
  useEffect(() => {
    if (target) router.replace(target);
  }, [target, router]);
  if (session.isError) return null; // the shell shows the session error
  if (view === 'cardholder') return <>{cardholder}</>;
  if (session.data && view === null) return <Banner tone="warn">No view is available for this role.</Banner>;
  return (
    <div style={{ padding: 24 }} aria-busy="true">
      <Skeleton height={28} width={320} />
    </div>
  );
}
