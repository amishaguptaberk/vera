# features/verify — identity verification (VER-006) and verification calls (VER-007)

Exports (`@/features/verify`):

- `IdentityPanel({ caseId, onOpenSource?, onBack?, showActions? })` — Communications → identity verification detail
  (channel chooser, awaiting/cooldown, verified/failed/expired/denied/cancelled). Staff view: never a code or a code field.
- `CallPanel({ caseId, callbackId?, onOpenSource?, onBack?, showActions? })` — call preparation (when the server offers
  `start_callback` and no call exists), live call with the transcript appending in place (1s polling while
  `in_progress`), complete / call-failed with the structured result block, reviewer notes (`add_callback_note`), and the
  labelled synthetic "next call outcome" demo control (synthetic env only).
- `CardholderVerifyPanel({ caseId })` — cardholder role only: "Verify it's you" task (code entry or push approve/deny).
  The code appears only in the labelled synthetic demo box, fetched from the cardholder-only outbox route.
- `tabs` — `{ key, label, Panel }[]` (identity, call). `commandForms` — inputs for `send_verification_request`, `add_callback_note`.
- `previewStates` — every prototype state, rendered from `dev-fixtures/` (imported only by `preview.tsx`).

Where to mount (integrator):

- `src/features/case/CaseWorkspace.tsx`, the Communications inspector (prototype `cm.isCall`): render `IdentityPanel` for the
  identity item and `CallPanel callbackId=…` for a call item; pass `showActions={false}` if the workspace's own ActionBar is
  already visible (the panels otherwise render the server's `available_actions` via `ActionBar`).
- Cardholder view (step `idv`): render `CardholderVerifyPanel caseId=…` in place of the cardholder task card.
- Merge `commandForms` into `COMMAND_FORMS` in `features/case/command-forms.ts`.

Endpoints: `GET /api/cases/{id}/verifications`, `GET /api/verifications/{id}/outbox` (cardholder only),
`GET /api/cases/{id}/callbacks`, `GET /api/cases/{id}/callbacks/{cb}`, `POST /api/demo/callback-outcome`; commands go through
`runCommand` (`POST /api/cases/{id}/commands/{command}`) with the server's key: `send_verification_request`,
`resend_verification_request`, `cancel_verification_request`, `submit_otp`, `answer_verification_push`, `start_callback`,
`add_callback_note`. Query keys sit under `caseKey(id)`.
