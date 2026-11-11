import type { FormField } from '@/features/case/command-forms';

// Inputs for VER-009 decision commands (same shape as features/case/command-forms.ts). Which commands appear is
// always the server's `available_actions`; this only maps a command to its input fields.
export const commandForms: Readonly<Record<string, readonly FormField[]>> = {
  record_decision: [{ name: 'rationale', label: 'Your rationale', multiline: true }],
  return_decision: [
    { name: 'reason', label: 'Reason', multiline: true },
    { name: 'next_step', label: 'Requested next step' },
    { name: 'owner', label: 'Owner (user id)', users: true },
  ],
  reassign_reviewer: [{ name: 'to', label: 'Reassign to (user id)', users: true }],
};
