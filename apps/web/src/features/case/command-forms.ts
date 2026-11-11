// Input fields for commands whose payload needs user input (packages/domain/vera_domain/commands.py payload models).
// This maps a command to its input schema only; which commands appear is always the server's `available_actions`.
export type FormField = { name: string; label: string; multiline?: boolean };

export const COMMAND_FORMS: Readonly<Record<string, readonly FormField[]>> = {
  hold_case: [
    { name: 'reason', label: 'Reason', multiline: true },
    { name: 'next_owner', label: 'Next owner (user id)' },
  ],
  reassign_case: [
    { name: 'to', label: 'Reassign to (user id)' },
    { name: 'reason', label: 'Reason', multiline: true },
  ],
  link_report: [{ name: 'statement', label: 'Statement', multiline: true }],
};
