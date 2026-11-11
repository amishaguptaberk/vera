// Input fields for commands whose payload needs user input (packages/domain/vera_domain/commands.py payload models).
// This maps a command to its input schema only; which commands appear is always the server's `available_actions`
// / `recovery_actions`. `users: true` offers the assignable staff list when GET /api/users exists.
export type FormField = { name: string; label: string; multiline?: boolean; users?: boolean; placeholder?: string };

export const COMMAND_FORMS: Readonly<Record<string, readonly FormField[]>> = {
  hold_case: [
    { name: 'reason', label: 'Reason', multiline: true },
    { name: 'next_owner', label: 'Next owner (user id)', users: true },
  ],
  reassign_case: [
    { name: 'to', label: 'Reassign to (user id)', users: true },
    { name: 'reason', label: 'Reason', multiline: true },
  ],
  link_report: [{ name: 'statement', label: 'Statement', multiline: true }],
  retry_specialist_step: [{ name: 'mode', label: 'Mode (live or replay)', placeholder: 'replay' }],
};
