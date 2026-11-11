'use client';

// Development preview states. Renders the REAL presentational components with DEVELOPMENT FIXTURES from
// ./dev-fixtures — never imported by panels, hooks or pages.
import type { ReactNode } from 'react';
import type { ActionView } from '@/api';
import { ActionBar } from '@/components/case';
import { ClosureChecklist, ControlPlan, FinalDraft, ParallelTracks, SimulatedNote, TaskFrame, TaskNote, TaskParas } from '@/components/money';
import { actions, checklist, controls, finalBody, tracks } from './dev-fixtures/chg-1042';

const noop = () => {};
const all = new Set(controls.map((c) => c.key));
const Acts = ({ a, sim = false }: { a: readonly ActionView[]; sim?: boolean }) => (
  <>
    <ActionBar actions={a} blocked={[]} onAction={noop} />
    {sim ? <SimulatedNote /> : null}
  </>
);
const S = (name: string, label: string, title: string, body: ReactNode) => ({ name, render: () => <TaskFrame label={label} title={title}>{body}</TaskFrame> });

export const previewStates: { name: string; render: () => ReactNode }[] = [
  S('Credit · issue', 'Ready', 'Issue the provisional credit', <>
    <TaskParas paras={['$2,840.00 against this charge. It can be issued only once, and the original charge stays visible.']} />
    <Acts a={actions.issue} sim />
    <TaskNote text="Reviewer approval is current. Credit can be issued once." />
  </>),
  S('Credit · checking result', 'Blocked', 'Checking the existing credit result', <>
    <TaskParas paras={['The credit service’s response was interrupted after the request went out. Vera looks up the existing request before anything is retried.']} />
    <Acts a={actions.credit_check} sim />
    <TaskNote text="Checking the existing credit result · nothing will be issued twice." />
  </>),
  S('Card controls · analyst (send / skip)', 'Needs review', 'Send control plan to Dana', <>
    <TaskParas paras={['Vera recommends these controls. Dana approves and applies them as card admin; nothing is applied before that.']} />
    <ParallelTracks tracks={tracks('Not prepared', 'Recommended', 'controls', 'idle', 'idle')} onFocus={noop} />
    <ControlPlan items={controls} selected={all} editable onToggle={noop} onOpenRecord={noop} />
    <Acts a={actions.controls} />
  </>),
  S('Dispute · prepare', 'Ready', 'Prepare the dispute packet', <>
    <TaskParas paras={['Vera assembles the charge, the original report, later replies, evidence and the latest verification result. Nothing is submitted.']} />
    <ParallelTracks tracks={tracks('Not prepared', 'Awaiting admin approval', 'dispute', 'idle', 'wait')} onFocus={noop} />
    <Acts a={actions.dsp_prepare} />
  </>),
  S('Dispute · open', 'Ready', 'Dispute packet prepared', <>
    <TaskParas paras={['Open it to start your review. Nothing is submitted yet.']} />
    <ParallelTracks tracks={tracks('Prepared', 'Awaiting admin approval', 'dispute', 'idle', 'wait')} onFocus={noop} />
    <Acts a={actions.dsp_open} />
  </>),
  S('Dispute · review', 'Needs review', 'Review the dispute packet', <>
    <TaskParas paras={['Check the reason, evidence and verification result. Confirming the review marks it ready to submit.']} />
    <ParallelTracks tracks={tracks('Ready for review', 'Awaiting admin approval', 'dispute', 'idle', 'wait')} onFocus={noop} />
    <Acts a={actions.dsp_review} />
  </>),
  S('Dispute · submit', 'Ready', 'Record the dispute submission', <>
    <TaskParas paras={['Reason: cardholder did not authorize. Recording the submission is simulated; no card network is contacted.']} />
    <ParallelTracks tracks={tracks('Ready to submit', 'Awaiting admin approval', 'dispute', 'idle', 'wait')} onFocus={noop} />
    <Acts a={actions.dsp_submit} sim />
  </>),
  S('Dispute · submission failed', 'Blocked', 'Dispute submission failed', <>
    <TaskParas paras={['Nothing was submitted. Retrying records it once.']} />
    <ParallelTracks tracks={tracks('Submission failed', 'Awaiting admin approval', 'dispute', 'block', 'wait')} onFocus={noop} />
    <Acts a={actions.dsp_failed} sim />
  </>),
  S('Waiting on card admin · analyst', 'Waiting', 'Waiting on card admin approval', <>
    <TaskParas paras={['5 controls sent to Dana as card admin. Nothing is applied until she approves and applies them.']} />
    <ParallelTracks tracks={tracks('Submission recorded · simulated', 'Awaiting admin approval', null, 'done', 'wait')} onFocus={noop} />
    <ControlPlan items={controls} selected={all} editable={false} onToggle={noop} />
  </>),
  S('Card admin · approve controls', 'Card admin · from Sam Rivera', 'Approve card controls for ••4418?', <>
    <ControlPlan items={controls} selected={all} editable onToggle={noop} onOpenRecord={noop} />
    <Acts a={actions.waitctl_admin} />
  </>),
  S('Card admin · apply controls', 'Card admin · approved', 'Apply the approved card controls?', <>
    <ControlPlan items={controls} selected={all} editable={false} onToggle={noop} />
    <Acts a={actions.ctl_apply_admin} sim />
  </>),
  S('Final update · needed', 'Ready', 'Send Priya a final update.', <>
    <TaskParas paras={['Vera drafts it from recorded state only.']} />
    <ClosureChecklist items={checklist(false)} onOpenRecord={noop} />
    <Acts a={actions.finalprep} />
  </>),
  S('Final update · draft', 'Needs review', 'Review the final update to Priya.', <>
    <TaskParas paras={['Generated from case state. Vera blocks claims about actions that aren’t recorded.']} />
    <FinalDraft to="Priya Shah · priya.shah@example.com" value={finalBody} error={null} onChange={noop} />
    <Acts a={actions.final} />
  </>),
  S('Final update · content-policy error', 'Needs review', 'Review the final update to Priya.', <>
    <FinalDraft to="Priya Shah · priya.shah@example.com" value={finalBody} error="The message says the card is locked, but no lock has been applied." onChange={noop} />
    <Acts a={actions.final} />
  </>),
  S('Close', 'Complete', 'Ready to close', <>
    <ClosureChecklist items={checklist(true)} onOpenRecord={noop} />
    <Acts a={actions.close} />
  </>),
  S('Monitoring', 'Waiting', 'Waiting for the dispute outcome.', <>
    <TaskParas paras={['The temporary credit stays reversible until the outcome is recorded. Owner: Sam Rivera · due Nov 24.']} />
    <TaskNote text="Simulated outcomes. In practice this arrives from the dispute review." />
  </>),
  S('Closed', 'Complete', 'Closed', <TaskParas paras={['Credit finalized after the dispute outcome. No further actions.']} />),
];
