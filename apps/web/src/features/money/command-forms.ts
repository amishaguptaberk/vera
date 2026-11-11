import { MODE_CHOICES, type FormField } from '@/features/case/command-forms';

// Inputs for money/controls/closure commands that need user text (same shape as features/case/command-forms.ts).
// Which commands appear is always the server's `available_actions`.
export const commandForms: Readonly<Record<string, readonly FormField[]>> = {
  skip_card_controls: [{ name: 'reason', label: 'Reason', multiline: true }],
  decline_card_controls: [{ name: 'reason', label: 'Reason', multiline: true }],
  retry_dispute_narrative: [{ name: 'mode', label: 'Mode', choices: MODE_CHOICES }],
  // CloseCasePayload: reason (5-500 chars), outcome resolved | no_action | unresolved.
  close_case: [
    { name: 'reason', label: 'Reason', multiline: true },
    { name: 'outcome', label: 'Outcome', choices: [{ value: 'resolved', label: 'Resolved' }, { value: 'no_action', label: 'No action needed' }, { value: 'unresolved', label: 'Unresolved' }] },
  ],
};
