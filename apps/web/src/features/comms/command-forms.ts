// Input fields for the communications commands whose payload needs user input (vera_domain/comms.py payloads).
// Same shape as features/case/command-forms.ts entries; which commands appear is always the server's.
import type { FormField } from '@/features/case/command-forms';

export const commandForms: Readonly<Record<string, readonly FormField[]>> = {
  update_communication_draft: [
    { name: 'subject', label: 'Subject' },
    { name: 'body', label: 'Message', multiline: true },
  ],
  send_communication: [
    { name: 'channel', label: 'Channel (email or portal)', placeholder: 'email' },
    { name: 'subject', label: 'Subject' },
  ],
  review_cardholder_response: [
    { name: 'outcome', label: 'Outcome (complete, incomplete or conflicting)', placeholder: 'complete' },
    { name: 'note', label: 'Note', multiline: true },
  ],
};
