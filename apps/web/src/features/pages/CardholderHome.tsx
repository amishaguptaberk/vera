'use client';

import { Banner, Skeleton } from '@/design-system/primitives';
import { RequestPage, useMyRequests } from '@/features/comms';
import { isNotDeployed } from '@/features/comms/queries';
import { NotAvailableYet } from './NotAvailableYet';

/** The cardholder's landing: their own open request, resolved by the server (GET /api/requests?mine=true). */
export function CardholderHome() {
  const mine = useMyRequests();
  if (mine.isError) {
    if (isNotDeployed(mine.error)) return <NotAvailableYet>Requests from Finance will appear here once the service is available.</NotAvailableYet>;
    return <Banner tone="bad" title="Could not load your requests">{mine.error.message}</Banner>;
  }
  if (!mine.data) {
    return (
      <div style={{ padding: 24 }} aria-busy="true">
        <Skeleton height={28} width={320} />
      </div>
    );
  }
  const open = mine.data.requests.find((r) => !r.responded) ?? mine.data.requests[0];
  if (!open) return <NotAvailableYet title="Nothing needs your attention.">Requests from Finance will appear here.</NotAvailableYet>;
  return <RequestPage requestId={open.request_id} />;
}
