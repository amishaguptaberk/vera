import { Suspense } from 'react';
import { CaseWorkspace } from '@/features/case';

export default async function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <CaseWorkspace caseId={decodeURIComponent(id)} />
    </Suspense>
  );
}
