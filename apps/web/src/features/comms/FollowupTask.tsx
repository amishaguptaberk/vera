'use client';

import { useState } from 'react';
import { useRunCommand } from '@/api';
import { useCaseView } from '@/api/queries';
import { Button } from '@/design-system/primitives';
import { FollowupTaskBlock, type FollowupStep } from '@/components/comms';
import { CommsDraft } from './CommsPanel';
import type { ReviewSuggestion } from './contract';
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
  const run = useRunCommand(caseId);
  const [error, setError] = useState<string | null>(null);
  if (!view.data || !isFollowupStep(view.data.step)) return null;
  const c = detail.data;
  const v = view.data;
  // Draft step before a message exists: the server's "Draft follow-up" is the one main action (it is left out
  // of the ActionBar in this step, see mounts.tsx).
  const draftAction = v.step === 'draft' && list.isSuccess && !list.data.some((x) => x.status === 'drafted') ? (v.available_actions.find((a) => a.command === 'draft_follow_up') ?? null) : null;
  return (
    <FollowupTaskBlock
      step={view.data.step}
      cardholderName={view.data.cardholder.name}
      followUp={(list.data?.length ?? 0) > 1}
      reminders={c?.reminders ?? 0}
      responseText={c?.response?.text ?? null}
      responseAttached={!!c?.response?.evidence_record_id}
      drafted={v.step === 'draft' ? !draftAction : undefined}
    >
      {draftAction ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginTop: 16 }}>
          <Button
            variant="go"
            disabled={!draftAction.enabled || run.isPending}
            aria-busy={run.isPending || undefined}
            onClick={() => {
              setError(null);
              run.mutate({ action: draftAction, caseVersion: v.case_version }, { onError: (e) => setError(e.blockedReason ?? e.message) });
            }}
          >
            {draftAction.label}
          </Button>
          {error ? <span role="alert" style={{ color: 'var(--bad)', fontSize: 12.5 }}>{error}</span> : null}
        </div>
      ) : null}
      {view.data.step === 'response' && c?.review_suggestion ? <Suggestion s={c.review_suggestion} /> : null}
      {view.data.step === 'draft' && c && c.status === 'drafted' ? <CommsDraft caseId={caseId} item={c} view={view.data} /> : null}
    </FollowupTaskBlock>
  );
}

const CLASS_LABEL: Record<string, string> = { complete: 'Complete', incomplete: 'Incomplete', conflicting: 'Conflicting' };

/** The Response Reviewer's suggestion, as a quiet note: the analyst's review decides in every case. */
function Suggestion({ s }: { s: ReviewSuggestion }) {
  const note = { margin: '8px 0 0', fontSize: 13, color: 'var(--ink2)' } as const;
  if (s.status === 'pending')
    return (
      <p data-testid="review-suggestion" role="status" style={note}>
        Vera is reviewing the reply…
      </p>
    );
  if (s.status === 'unavailable')
    return (
      <p data-testid="review-suggestion" role="status" style={note}>
        Review suggestion unavailable — review the reply yourself.
      </p>
    );
  const statements = s.citations.map((x) => (typeof x.statement === 'string' ? x.statement : '')).filter(Boolean);
  return (
    <div data-testid="review-suggestion" role="status" style={note}>
      <b style={{ fontWeight: 550 }}>Suggested review: {CLASS_LABEL[s.classification ?? ''] ?? s.classification}</b> · you decide.
      {statements.length ? (
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
          {statements.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
