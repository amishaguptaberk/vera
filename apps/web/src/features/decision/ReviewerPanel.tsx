'use client';

import { useQuery } from '@tanstack/react-query';
import { useRunCommand, type ActionView, type CaseView } from '@/api';
import { ApprovalHistory, DecisionFocus, PacketView, ReviewerControls } from '@/components/decision';
import { decisionPacketQuery, isNotAvailable } from './queries';
import { packetProps } from './DecisionPanel';
import styles from './panel.module.css';

export type ReviewerPanelProps = { c: CaseView; selected?: string | null; onSelectRecord?: (recordId: string) => void };

const find = (c: CaseView, command: string): ActionView | null => c.available_actions.find((a) => a.command === command) ?? null;

/** Reviewer "Approvals" view (prototype isReviewer #rv-decision): packet read view, approve, return with a required reason. */
export function ReviewerPanel({ c, selected, onSelectRecord }: ReviewerPanelProps) {
  const packet = useQuery(decisionPacketQuery(c.case_id));
  const run = useRunCommand(c.case_id);
  const p = packet.data;
  const approve = find(c, 'approve_decision');
  const ret = find(c, 'return_decision');
  const stale = (!!p && (!p.current || p.approval?.status === 'stale')) || c.step === 'stale';
  return (
    <DecisionFocus id="rv-decision" label="Reviewer decision" eyebrow={c.state_label} title={c.next_action}>
      {packet.isError ? (
        <p className={styles.rd} data-testid="packet-unavailable">
          {isNotAvailable(packet.error) ? 'Decision packet: not available yet.' : 'The decision packet could not be loaded.'}
        </p>
      ) : null}
      {p ? <PacketView {...packetProps(p)} selected={selected} onSelectRecord={onSelectRecord} /> : null}
      {p ? <ApprovalHistory items={packetProps(p).approvals} /> : null}
      <ReviewerControls
        approve={approve}
        ret={ret}
        stale={stale}
        staleWhat={p && !p.current ? `packet v${p.version}, latest v${p.latest_version}` : null}
        analystName={c.owner?.name ?? undefined}
        busy={run.isPending}
        error={run.error?.message ?? null}
        onApprove={() => approve && run.mutate({ action: approve, caseVersion: c.case_version })}
        onReturn={(reason) => ret && run.mutate({ action: ret, caseVersion: c.case_version, payload: { reason } })}
      />
    </DecisionFocus>
  );
}
