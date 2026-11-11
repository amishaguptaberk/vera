'use client';

import { useCaseView } from '@/api/queries';
import { FollowupTaskBlock, type FollowupStep } from '@/components/comms';
import { CommsDraft } from './CommsPanel';
import { useCommunication, useCommunications } from './queries';

export const FOLLOWUP_STEPS: readonly FollowupStep[] = ['draft', 'waiting', 'noresp1', 'noresp2', 'response'];
export const isFollowupStep = (step: string): step is FollowupStep => (FOLLOWUP_STEPS as readonly string[]).includes(step);

/**
 * Task-card body for the follow-up steps (draft → waiting → noresp1/noresp2 → response). The step comes from
 * the server's case view; the actions stay in the workspace ActionBar, except the draft editor's Send.
 */
export function FollowupTask({ caseId }: { caseId: string }) {
  const view = useCaseView(caseId);
  const list = useCommunications(caseId);
  const latest = list.data?.length ? list.data[list.data.length - 1] : null;
  const detail = useCommunication(caseId, latest?.id ?? null);
  if (!view.data || !isFollowupStep(view.data.step)) return null;
  const c = detail.data;
  return (
    <FollowupTaskBlock
      step={view.data.step}
      cardholderName={view.data.cardholder.name}
      followUp={(list.data?.length ?? 0) > 1}
      reminders={c?.reminders ?? 0}
      responseText={c?.response?.text ?? null}
      responseAttached={!!c?.response?.evidence_record_id}
    >
      {view.data.step === 'draft' && c && c.status === 'drafted' ? <CommsDraft caseId={caseId} item={c} view={view.data} /> : null}
    </FollowupTaskBlock>
  );
}
