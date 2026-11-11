'use client';

import { useState } from 'react';

import { useQuery } from '@tanstack/react-query';
import { caseViewQuery } from '@/api';
import { Banner, Skeleton } from '@/design-system/primitives';
import { RequestPage, useMyRequests } from '@/features/comms';
import { CardholderVerifyPanel } from '@/features/verify';
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
  return <CardholderTasks requestId={open.request_id} caseId={open.case_id ?? null} />;
}

const VERIFY_COMMANDS = new Set(['submit_otp', 'answer_push']);

/** A verification step the server offers the cardholder on their case comes first; otherwise their request. */
function CardholderTasks({ requestId, caseId }: { requestId: string; caseId: string | null }) {
  const view = useQuery({ ...caseViewQuery(caseId ?? ''), enabled: !!caseId });
  const verifying = !!caseId && !!view.data?.available_actions.some((a) => VERIFY_COMMANDS.has(a.command));
  const [seen, setSeen] = useState(false);
  // Keep the panel mounted after the code is accepted, so its "you're verified" confirmation stays visible.
  if (verifying && !seen) setSeen(true);
  if (caseId && view.isPending) {
    return (
      <div style={{ padding: 24 }} aria-busy="true">
        <Skeleton height={28} width={320} />
      </div>
    );
  }
  if (caseId && (verifying || seen)) {
    return (
      <div style={{ padding: 24 }}>
        <CardholderVerifyPanel caseId={caseId} />
      </div>
    );
  }
  return <RequestPage requestId={requestId} />;
}
