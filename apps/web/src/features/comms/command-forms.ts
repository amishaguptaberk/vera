// Input fields for the communications commands whose payload needs user input (vera_domain/comms.py payloads).
// Same shape as features/case/command-forms.ts entries; which commands appear is always the server's.
import type { FormField } from '@/features/case/command-forms';

export const commandForms: Readonly<Record<string, readonly FormField[]>> = {
  update_communication_draft: [
    { name: 'subject', label: 'Subject' },
    { name: 'body', label: 'Message', multiline: true },
  ],
  send_communication: [
    { name: 'channel', label: 'Channel', choices: [{ value: 'email', label: 'Email' }, { value: 'portal', label: 'Ramp app' }] },
    { name: 'subject', label: 'Subject' },
  ],
  // ReviewResponsePayload: outcome, note, receipt_accepted (accept the attached receipt as evidence).
  review_cardholder_response: [
    {
      name: 'outcome',
      label: 'Outcome',
      choices: [
        { value: 'complete', label: 'Complete · the reply answers the questions' },
        { value: 'incomplete', label: 'Incomplete · something is still missing' },
        { value: 'conflicting', label: 'Conflicting · the reply contradicts the report' },
      ],
    },
    { name: 'note', label: 'Note', multiline: true },
    { name: 'receipt_accepted', label: 'Accept the attached receipt as evidence', checkbox: true },
  ],
};
