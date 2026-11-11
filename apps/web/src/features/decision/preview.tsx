// Development preview only. Real presentational components + dev-fixtures; no-op handlers.
import type { ReactNode } from 'react';
import { ActionBar } from '@/components/case';
import { ApprovalHistory, DecisionFocus, PacketView, ReviewerControls, VeraRail, type RailMessage } from '@/components/decision';
import * as F from './dev-fixtures/chg-1042';

const noop = () => {};
const packet = <PacketView sections={F.sections} refs={F.refs} policy={F.policy} versions={F.versions} onSelectRecord={noop} />;
const rail = (messages: RailMessage[], chips: readonly string[], placeholder = 'Ask about this case', sending = false) => (
  <VeraRail open messages={messages} sub="Decision" emptyText="Vera’s work on this case appears here." chips={chips} input={sending ? 'Why is credit blocked?' : ''} placeholder={placeholder} sending={sending} onInput={noop} onAsk={noop} onClose={noop} onSelectRecord={noop} onAction={noop} />
);

export const previewStates: { name: string; render: () => ReactNode }[] = [
  {
    name: 'Decision · analyst decides',
    render: () => (
      <DecisionFocus id="task" label="Decision" eyebrow="Decision" title="Recommended: temporary credit while the dispute is prepared." paras={['Priya confirmed she didn’t place or approve the order. Credit is eligible and needs Dana’s approval.']}>
        {packet}
        <ActionBar actions={F.decideActions} blocked={[]} onAction={noop} />
      </DecisionFocus>
    ),
  },
  {
    name: 'Decision · waiting on reviewer',
    render: () => (
      <DecisionFocus id="task" label="Decision" eyebrow="Waiting on reviewer" title="Decision packet sent for approval" paras={['Dana’s approval will apply to this exact evidence. Run details has the snapshot.']}>
        {packet}
        <ActionBar actions={F.waitActions} blocked={[]} onAction={noop} />
      </DecisionFocus>
    ),
  },
  {
    name: 'Decision · returned by reviewer',
    render: () => (
      <DecisionFocus id="task" label="Decision" eyebrow="Returned" title="Revise the packet Dana returned" paras={['“Add the delivery record before I approve.” Update the rationale and resend.']}>
        {packet}
        <ApprovalHistory items={F.approvals} />
        <ActionBar actions={F.decideActions} blocked={[]} onAction={noop} />
      </DecisionFocus>
    ),
  },
  {
    name: 'Decision · stale (evidence changed while reviewing)',
    render: () => (
      <DecisionFocus id="task" label="Decision" eyebrow="Stale" title="The evidence changed while Dana was reviewing." paras={['Dana can’t approve a packet built on older evidence.']}>
        <ActionBar actions={F.staleActions} blocked={[]} onAction={noop} />
      </DecisionFocus>
    ),
  },
  {
    name: 'Reviewer · approve or return',
    render: () => (
      <DecisionFocus id="rv-decision" label="Reviewer decision" eyebrow="From Sam Rivera · Nov 10 · due today 5:00 PM" title="Approve a temporary credit of $2,840.00?" paras={['For CHG-1042 while the dispute is investigated. The original charge stays visible. Your approval applies to this exact evidence, policy v3 and workflow v4.']}>
        {packet}
        <ReviewerControls approve={{ label: 'Approve temporary credit', enabled: true }} ret={{ label: 'Return to Sam', enabled: true }} stale={false} analystName="Sam" onApprove={noop} onReturn={noop} />
      </DecisionFocus>
    ),
  },
  {
    name: 'Reviewer · stale approval blocked',
    render: () => (
      <DecisionFocus id="rv-decision" label="Reviewer decision" eyebrow="From Sam Rivera · Nov 10 · due today 5:00 PM" title="Approve a temporary credit of $2,840.00?" paras={['For CHG-1042 while the dispute is investigated. The evidence has changed since, so approval is blocked until Sam refreshes the packet.']}>
        {packet}
        <ReviewerControls approve={{ label: 'Approve temporary credit', enabled: true }} ret={{ label: 'Return to Sam', enabled: true }} stale staleWhat="DLV-882 v2" analystName="Sam" onApprove={noop} onReturn={noop} />
      </DecisionFocus>
    ),
  },
  { name: 'Reviewer · nothing waiting', render: () => <DecisionFocus id="rv-decision" label="Reviewer decision" eyebrow="Reviewer" title="Nothing is waiting for you right now." /> },
  { name: 'Vera rail · empty', render: () => rail([], F.analystChips) },
  { name: 'Vera rail · specialists working', render: () => rail(F.railWork, [], 'Ask about this case') },
  { name: 'Vera rail · answer with citations', render: () => rail(F.railDone, F.analystChips) },
  { name: 'Vera rail · sending', render: () => rail(F.railDone, F.analystChips, 'Ask about this case', true) },
  { name: 'Vera rail · reviewer refusal for “approve this”', render: () => rail(F.railRefusal, F.reviewerChips, 'Ask about this packet') },
];
