import { RequestRoute } from '@/features/pages';

export default async function RequestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RequestRoute requestId={decodeURIComponent(id)} />;
}
