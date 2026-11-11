import type { FormField } from '@/features/case/command-forms';

// Inputs for money/controls/closure commands that need user text (same shape as features/case/command-forms.ts).
// Which commands appear is always the server's `available_actions`.
export const commandForms: Readonly<Record<string, readonly FormField[]>> = {
  skip_card_controls: [{ name: 'reason', label: 'Reason', multiline: true }],
  decline_card_controls: [{ name: 'reason', label: 'Reason', multiline: true }],
};
