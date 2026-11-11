import { Suspense } from 'react';
import { ApprovalsPage } from '@/features/pages';

export default function Approvals() {
  return (
    <Suspense>
      <ApprovalsPage />
    </Suspense>
  );
}
