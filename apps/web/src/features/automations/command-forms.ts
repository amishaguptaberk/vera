// Input fields for automation commands whose payload needs user input (payload models in
// packages/domain/vera_domain/automations.py). Same shape as features/case/command-forms.ts; which commands
// appear is always the server's `available_actions`.
export type FormField = { name: string; label: string; multiline?: boolean; placeholder?: string };

export const commandForms: Readonly<Record<string, readonly FormField[]>> = {
  publish_workflow_version: [{ name: 'reason', label: 'Reason for publishing', multiline: true }],
  publish_policy_version: [
    { name: 'receipt_threshold', label: 'Receipt threshold (USD)' },
    { name: 'reason', label: 'Reason for publishing', multiline: true },
  ],
};
