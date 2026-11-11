import { Suspense } from 'react';
import { CasesQueue } from '@/features/cases';
import { PageMain } from '@/features/shell';

export default function CasesPage() {
  return (
    <Suspense>
      <PageMain>
        <CasesQueue />
      </PageMain>
    </Suspense>
  );
}
