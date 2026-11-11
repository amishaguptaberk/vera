'use client';

import { useState } from 'react';
import { ApiError, useRunCommand, type ActionView } from '@/api';
import { ActionBar } from '@/components/case';
import { ClosureChecklist, ControlPlan, DisputeNarrative, FinalDraft, ParallelTracks, SimulatedNote, TaskNote, TaskParas, type ClosureItemView, type TrackRow } from '@/components/money';
import { Banner, Button, Field } from '@/design-system/primitives';
import { commandForms } from './command-forms';
import type { ControlPlanItem, ControlsStatus, DisputeStatus, MoneyCaseView, RemediationBody } from './contract';
import { useClosureChecklist, useFinalMessage, useRemediation } from './queries';

type Step = MoneyCaseView['step'];

/** Steps this feature renders the task body for. */
export const MONEY_STEPS: ReadonlySet<Step> = new Set<Step>([
  'issue', 'credit_check', 'controls', 'ctl_prep', 'dsp_prepare', 'dsp_open', 'dsp_review', 'dsp_submit', 'dsp_failed',
  'waitctl', 'ctl_apply', 'finalprep', 'final', 'close', 'monitoring', 'closed',
]);

// Prototype copy (Main.dc.html task builder, lines ~4068-4083), data-free parts only. GAP: the server `task` block.
const COPY: Partial<Record<Step, string>> = {
  issue: 'It can be issued only once, and the original charge stays visible.',
  credit_check: 'The credit service’s response was interrupted after the request went out. Vera looks up the existing request before anything is retried.',
  controls: 'Vera recommends these controls. Dana approves and applies them as card admin; nothing is applied before that.',
  ctl_prep: 'The Prevention Planner recommends controls after the credit or dispute decision.',
  dsp_prepare: 'Vera assembles the charge, the original report, later replies, evidence and the latest verification result. Nothing is submitted.',
  dsp_open: 'Open it to start your review. Nothing is submitted yet.',
  dsp_review: 'Check the reason, evidence and verification result. Confirming the review marks it ready to submit.',
  dsp_submit: 'Recording the submission is simulated; no card network is contacted.',
  dsp_failed: 'Nothing was submitted. Retrying records it once.',
  waitctl: 'Nothing is applied until the card admin approves and applies the controls.',
  ctl_apply: 'Applying is simulated.',
  finalprep: 'Vera drafts it from recorded state only.',
  final: 'Generated from case state. Vera blocks claims about actions that aren’t recorded.',
};

const CREDIT_NOTE: Partial<Record<string, string>> = {
  checking: 'Checking the existing credit result · nothing will be issued twice.',
  issued: 'Credit issued once · safe to retry. Repeating this action will return the existing result and will not issue another credit.',
  reversed: 'Credit reversed · the charge stands.',
  finalized: 'Credit finalized after the dispute outcome.',
};

/** Decision D6: commands that call a simulated adapter (money or card controls). Copy tagging only — never gating. */
const SIMULATED_COMMANDS = new Set(['issue_provisional_credit', 'lookup_execution_result', 'submit_dispute', 'apply_card_controls']);
/** Commands whose payload is the selected control list (Handoff §3.2: `{controls: [...]}`). */
const CONTROL_LIST_COMMANDS = new Set(['propose_card_controls', 'approve_card_controls']);
/** Commands whose payload carries the edited final message body. */
const BODY_COMMANDS = new Set(['update_final_message', 'send_final_message']);

// Prototype DSP_L / CTL_L (Main.dc.html 3754-3755): display copy for the server's status values.
const DSP_L: Record<string, string> = { not_prepared: 'Not prepared', prepared: 'Prepared', ready_for_review: 'Ready for review', ready_to_submit: 'Ready to submit', submitted: 'Submission recorded · simulated', failed: 'Submission failed', accepted: 'Accepted', denied: 'Denied' };
const CTL_L: Record<string, string> = { not_recommended: 'Not recommended', recommended: 'Recommended', awaiting_approval: 'Awaiting admin approval', approved: 'Approved', applied: 'Applied · simulated', declined: 'Declined' };
// Generic names for the server's ControlName values. GAP: per-case reason/scope/reversibility are not served yet.
const CONTROL_LABEL: Record<string, string> = { lock: 'Lock card', replace: 'Replace card', virtual: 'Create replacement virtual card', block: 'Block merchant on this card', monitor: 'Monitor merchant for 30 days' };
const CONTROL_STEPS = new Set<Step>(['controls', 'waitctl', 'ctl_apply']);
/** The server's recovery command for a failed dispute narrative: shown on the failure line, not in the action bar. */
const NARRATIVE_RETRY = 'retry_dispute_narrative';

const TRACK_STEPS = new Set<Step>(['controls', 'ctl_prep', 'dsp_prepare', 'dsp_open', 'dsp_review', 'dsp_submit', 'dsp_failed', 'waitctl', 'ctl_apply']);
const CLOSURE_STEPS = new Set<Step>(['finalprep', 'final', 'close']);

const disputeSlot = (s: DisputeStatus): TrackRow['slot'] =>
  s === 'failed' ? 'block' : s === 'submitted' || s === 'accepted' || s === 'denied' ? 'done' : 'idle';
const controlsSlot = (s: ControlsStatus): TrackRow['slot'] =>
  s === 'applied' || s === 'declined' ? 'done' : s === 'awaiting_approval' || s === 'approved' ? 'wait' : 'idle';

function tracksFor(c: MoneyCaseView, r: RemediationBody | undefined): TrackRow[] {
  const dStatus = r?.dispute.status ?? c.dispute?.status;
  const cStatus = r?.controls.status ?? c.controls?.status;
  if (!TRACK_STEPS.has(c.step) || !dStatus || !cStatus) return [];
  const dsp = c.step.startsWith('dsp_');
  const ctl = c.step === 'controls' || c.step === 'ctl_prep';
  return [
    { key: 'dispute', name: 'Dispute packet', status: DSP_L[dStatus] ?? c.dispute?.label ?? dStatus, slot: dsp ? 'review' : disputeSlot(dStatus as DisputeStatus), on: dsp, canGo: false },
    { key: 'controls', name: 'Card controls', status: CTL_L[cStatus] ?? c.controls?.label ?? cStatus, slot: ctl ? 'review' : controlsSlot(cStatus as ControlsStatus), on: ctl, canGo: false },
  ];
}

export type MoneyTaskProps = { caseId: string; c: MoneyCaseView; onOpenRecord?: (id: string) => void };

/**
 * Task body for credit, parallel tracks, dispute steps, card controls (analyst and card admin), final update,
 * closure checklist, monitoring and closed. Actions are exactly the server's `available_actions` for the active
 * role; nothing here decides which actions exist.
 */
export function MoneyTask({ caseId, c, onOpenRecord }: MoneyTaskProps) {
  const run = useRunCommand(caseId);
  const remediation = useRemediation(caseId, TRACK_STEPS.has(c.step) || CONTROL_STEPS.has(c.step));
  const finalMessage = useFinalMessage(caseId, c.step === 'final');
  const served = remediation.data?.controls.controls ?? [];
  const planItems: ControlPlanItem[] =
    c.control_plan?.items ??
    served.map((k) => ({ key: k, label: CONTROL_LABEL[k] ?? k, why: '', affects: '', effect: '', reversible: '', permission: '', record_id: null }));
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const selected = picked ?? new Set(c.control_plan?.requested ?? planItems.map((i) => i.key));
  const [edited, setEdited] = useState<string | null>(null);
  const body = edited ?? c.final_message?.body ?? finalMessage.data?.body ?? '';
  const [formFor, setFormFor] = useState<ActionView | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [draftError, setDraftError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<ActionView | null>(null);
  const checklist = useClosureChecklist(caseId, CLOSURE_STEPS.has(c.step));

  const narrativeRetry = c.available_actions.find((a) => a.command === NARRATIVE_RETRY) ?? null;
  const actions = c.available_actions.filter((a) => a.command !== NARRATIVE_RETRY);
  const dispute = remediation.data?.dispute;
  const editableControls = actions.some((a) => CONTROL_LIST_COMMANDS.has(a.command));
  const simulated = actions.some((a) => SIMULATED_COMMANDS.has(a.command));
  const paras = COPY[c.step];
  const creditNote = c.credit && (c.step === 'issue' || c.step === 'credit_check') ? CREDIT_NOTE[c.credit.status] : undefined;

  const execute = (action: ActionView, extra: Record<string, unknown> = {}) => {
    setNotice(null);
    setDraftError(null);
    setConfirming(null);
    const payload: Record<string, unknown> = { ...extra };
    if (CONTROL_LIST_COMMANDS.has(action.command)) payload.controls = [...selected];
    if (BODY_COMMANDS.has(action.command)) payload.body = body;
    run.mutate(
      { action, caseVersion: c.case_version, payload },
      {
        onSuccess: () => setFormFor(null),
        onError: (e) => {
          if (e.status === 422 && BODY_COMMANDS.has(action.command)) setDraftError(e.message);
          else if (e.code === 'stale_case_version') setNotice('This case changed while you were viewing it. The latest version is shown; nothing was retried.');
          else setNotice(e.blockedReason ?? e.message);
        },
      },
    );
  };
  const onAction = (a: ActionView) => {
    if (commandForms[a.command]) {
      setFormValues({});
      setFormFor(a);
    } else if (a.confirm) setConfirming(a);
    else execute(a);
  };

  const items: ClosureItemView[] | null = checklist.data
    ? checklist.data.items.map((i) => ({ key: i.name, label: i.label, status: i.status, detail: i.detail, owner_name: i.owner?.name ?? null, next_action: i.next_action ?? null, record_ids: i.record_ids }))
    : null;
  const unavailable = checklist.isError ? (checklist.error instanceof ApiError && checklist.error.status === 404 ? 'Closure checklist · not available yet' : `Closure checklist · could not load: ${checklist.error.message}`) : null;

  return (
    <div data-testid="money-task" data-step={c.step}>
      {paras ? <TaskParas paras={[paras]} /> : null}
      <ParallelTracks tracks={tracksFor(c, remediation.data)} onFocus={() => {}} />
      {c.step.startsWith('dsp_') && dispute?.narrative_status ? (
        <DisputeNarrative
          status={dispute.narrative_status}
          reasonCode={dispute.reason_code}
          statements={dispute.narrative ?? []}
          retryLabel={narrativeRetry?.label}
          onRetry={narrativeRetry ? () => onAction(narrativeRetry) : undefined}
          busy={run.isPending}
          onOpenRecord={onOpenRecord}
        />
      ) : null}
      {planItems.length && CONTROL_STEPS.has(c.step) ? (
        <ControlPlan
          items={planItems}
          selected={selected}
          editable={editableControls}
          onToggle={(k) => setPicked(() => {
            const n = new Set(selected);
            if (n.has(k)) n.delete(k);
            else n.add(k);
            return n;
          })}
          onOpenRecord={onOpenRecord}
        />
      ) : null}
      {c.step === 'final' ? (
        <FinalDraft to={c.final_message?.to ?? c.cardholder.name} value={body} error={draftError} onChange={setEdited} />
      ) : null}
      {CLOSURE_STEPS.has(c.step) ? <ClosureChecklist items={items} unavailable={unavailable} onOpenRecord={onOpenRecord} /> : null}
      {notice ? <Banner tone="bad">{notice}</Banner> : null}
      {formFor ? (
        <form
          aria-label={formFor.label}
          onSubmit={(e) => {
            e.preventDefault();
            execute(formFor, formValues);
          }}
        >
          {commandForms[formFor.command]!.map((f) => (
            <Field key={f.name} label={f.label} multiline={f.multiline ? true : undefined} placeholder={f.placeholder} value={formValues[f.name] ?? ''} onChange={(e: { target: { value: string } }) => setFormValues((v) => ({ ...v, [f.name]: e.target.value }))} />
          ))}
          {formFor.confirm ? <p>{formFor.confirm}</p> : null}
          <Button variant="go" type="submit" disabled={run.isPending}>
            {formFor.label}
          </Button>
          <Button variant="ghost" onClick={() => setFormFor(null)}>
            Cancel
          </Button>
        </form>
      ) : confirming ? (
        <div role="group" aria-label="Case actions">
          <p>{confirming.confirm}</p>
          <Button variant="go" disabled={run.isPending} onClick={() => execute(confirming)}>
            {confirming.label}
          </Button>
          <Button variant="ghost" onClick={() => setConfirming(null)}>
            Cancel
          </Button>
        </div>
      ) : actions.length ? (
        <ActionBar actions={actions} blocked={c.blocked_actions} busy={run.isPending ? (run.variables?.action.command ?? null) : null} onAction={onAction} />
      ) : null}
      {simulated ? <SimulatedNote /> : null}
      {creditNote ? <TaskNote text={creditNote} /> : null}
    </div>
  );
}
