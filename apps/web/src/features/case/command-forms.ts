// Input fields for commands whose payload needs user input (packages/domain/vera_domain/commands.py payload models).
// This maps a command to its input schema only; which commands appear is always the server's `available_actions`
// / `recovery_actions`. `users: true` offers the assignable staff list when GET /api/users exists.
// `choices` renders a select over the payload's fixed values (a server payload_default, when there is one, is
// preselected); `targets: true` a select over the action's server-listed `targets` (record ids), so a record id is
// picked, never typed; `checkbox: true` a boolean field.
export type FormChoice = { value: string; label: string };
export type FormField = { name: string; label: string; multiline?: boolean; users?: boolean; placeholder?: string; choices?: readonly FormChoice[]; targets?: boolean; checkbox?: boolean };
export const MODE_CHOICES: readonly FormChoice[] = [
  { value: 'replay', label: 'Replay (reference recording)' },
  { value: 'live', label: 'Live model' },
];

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
  retry_specialist_step: [{ name: 'mode', label: 'Mode', choices: MODE_CHOICES }],
  // ReviewRelatedChargePayload: record_id (one of the action's targets), decision, reason (1-500 chars).
  review_related_charge: [
    { name: 'record_id', label: 'Related charge', targets: true },
    { name: 'decision', label: 'Decision', choices: [{ value: 'related', label: 'Related to this charge' }, { value: 'not_related', label: 'Not related' }] },
    { name: 'reason', label: 'Reason', multiline: true },
  ],
};
