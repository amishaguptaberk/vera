import { Suspense } from 'react';
import { CasesQueue } from '@/features/cases';

export default function CasesPage() {
  return (
    <Suspense>
      <CasesQueue />
    </Suspense>
  );
}
