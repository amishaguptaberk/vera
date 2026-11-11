// DEVELOPMENT FIXTURES — not live data. Imported ONLY by ../preview.tsx.
// CHG-1042 content taken from prototype/Main.dc.html (CONTROLS catalog, DSP_L/CTL_L, task copy, closure items).
import type { ActionView } from '@/api';
import type { ClosureItemView, ControlItem, TrackRow } from '@/components/money';

const act = (command: string, label: string, style: ActionView['style'] = 'primary', extra: Partial<ActionView> = {}): ActionView => ({
  command,
  label,
  role: 'analyst',
  style,
  enabled: true,
  blocked_reason: null,
  expected_state: 'credit_issued',
  expected_step: 'controls',
  safe_note: null,
  confirm: null,
  idempotency_key: `${command}:CHG-1042`,
  payload_defaults: {},
  key_template: `${command}:{case_id}`,
  ...extra,
});

export const controls: ControlItem[] = [
  { key: 'lock', label: 'Lock card ••4418', why: 'Priya confirmed she didn’t make the charge, and CHG-1051 on the same card is unreviewed.', affects: 'Card ••4418', effect: 'Declines all new charges on the card', reversible: 'Yes — an admin can unlock', permission: 'Card admin', record_id: 'CALL-1042' },
  { key: 'replace', label: 'Replace card', why: 'A locked card can’t be used again.', affects: 'Card ••4418', effect: 'New physical card in 5–7 days', reversible: 'No — the old number is retired', permission: 'Card admin', record_id: 'CALL-1042' },
  { key: 'virtual', label: 'Create replacement virtual card', why: 'Lets Priya keep making approved purchases today.', affects: 'Priya Shah', effect: 'New virtual card, same limits', reversible: 'Yes — can be closed', permission: 'Card admin', record_id: 'REP-1042' },
  { key: 'block', label: 'Block Northstar Equipment on this card', why: 'Three Northstar charges on ••4418 in three weeks; one disputed.', affects: 'Northstar Equipment on ••4418', effect: 'Declines charges from this merchant on this card', reversible: 'Yes — admin can unblock', permission: 'Card admin', record_id: 'CHG-1051' },
  { key: 'monitor', label: 'Monitor Northstar Equipment for 30 days', why: 'Catches repeat activity on other cards.', affects: 'Northstar Equipment, all cards', effect: 'Flags new charges for review', reversible: 'Yes — ends automatically', permission: 'Finance analyst or admin', record_id: 'CHG-1048' },
];

const SIM = 'Simulated · no funds moved · safe to retry';
export const actions = {
  issue: [act('issue_provisional_credit', 'Issue temporary credit — simulated', 'primary', { safe_note: SIM })],
  credit_check: [act('lookup_execution_result', 'Look up existing result')],
  controls: [act('propose_card_controls', 'Send control plan to Dana'), act('skip_card_controls', 'No controls needed', 'ghost')],
  dsp_prepare: [act('prepare_dispute_packet', 'Prepare dispute packet')],
  dsp_open: [act('open_dispute_packet', 'Open packet')],
  dsp_review: [act('review_dispute_packet', 'Confirm review')],
  dsp_submit: [act('submit_dispute', 'Record submission — simulated', 'primary', { safe_note: SIM })],
  dsp_failed: [act('submit_dispute', 'Retry submission — simulated', 'primary', { safe_note: SIM })],
  waitctl_admin: [act('approve_card_controls', 'Approve controls', 'primary', { role: 'card_admin' }), act('decline_card_controls', 'Decline controls', 'secondary', { role: 'card_admin' })],
  ctl_apply_admin: [act('apply_card_controls', 'Apply approved controls — simulated', 'primary', { role: 'card_admin', safe_note: SIM })],
  finalprep: [act('draft_final_message', 'Draft final update')],
  final: [act('send_final_message', 'Send final update')],
  close: [act('close_case', 'Close case — monitoring active')],
} satisfies Record<string, ActionView[]>;

export const tracks = (dispute: string, controlsLabel: string, focus: 'dispute' | 'controls' | null, dSlot: TrackRow['slot'], cSlot: TrackRow['slot']): TrackRow[] => [
  { key: 'dispute', name: 'Dispute packet', status: dispute, slot: focus === 'dispute' ? 'review' : dSlot, on: focus === 'dispute', canGo: false },
  { key: 'controls', name: 'Card controls', status: controlsLabel, slot: focus === 'controls' ? 'review' : cSlot, on: focus === 'controls', canGo: focus === 'dispute' && cSlot === 'idle' },
];

export const finalBody =
  'Hi Priya, we’ve issued a temporary credit of $2,840.00 for the Northstar Equipment charge (CHG-1042) while the dispute is reviewed. Your card ••4418 is locked and a replacement virtual card is ready. We’ll watch for Northstar charges for 30 days.';

export const checklist = (finalSent: boolean): ClosureItemView[] => [
  { key: 'decision', label: 'Decision recorded', status: 'met', detail: 'Temporary credit · Nov 10, 10:42', owner_name: null, next_action: null, record_ids: [] },
  { key: 'credit', label: 'Credit status recorded', status: 'met', detail: 'Temporary credit issued · Nov 10, 10:44', owner_name: null, next_action: null, record_ids: ['CREDIT-1042'] },
  { key: 'dispute', label: 'Dispute status recorded', status: 'met', detail: 'Submission recorded · simulated', owner_name: null, next_action: null, record_ids: ['DSP-1042'] },
  { key: 'controls', label: 'Card-control decision recorded', status: 'met', detail: 'Applied · simulated', owner_name: null, next_action: null, record_ids: ['CTL-1042'] },
  finalSent
    ? { key: 'final', label: 'Final cardholder communication sent', status: 'met', detail: 'Sent Nov 10, 11:02', owner_name: null, next_action: null, record_ids: ['MSG-2210'] }
    : { key: 'final', label: 'Final cardholder communication sent', status: 'unmet', detail: 'Drafted · not sent', owner_name: 'Sam Rivera', next_action: 'Send the final update', record_ids: ['MSG-2210'] },
  { key: 'outcome', label: 'Final outcome recorded', status: 'unknown', detail: 'Pending · dispute outcome due Nov 24 · the case stays in monitoring', owner_name: 'Sam Rivera', next_action: 'Record dispute outcome by Nov 24', record_ids: [] },
];
