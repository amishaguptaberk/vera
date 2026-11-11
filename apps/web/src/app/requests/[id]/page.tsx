import { RequestRoute } from '@/features/pages';
import { PageMain } from '@/features/shell';

export default async function RequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <PageMain>
      <RequestRoute requestId={decodeURIComponent(id)} />
    </PageMain>
  );
}
