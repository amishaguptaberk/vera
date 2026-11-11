# features/comms — integration notes

Exports (`@/features/comms`):

- `tabs` — `[{ key: 'comms', label: 'Communications', Panel: CommsPanel }]`. Mount in `src/features/case/CaseWorkspace.tsx`
  where the tab panels are chosen: render `<CommsPanel caseId={caseId} />` for the `comms` tab (prototype tab order:
  Evidence, Communications, Decision, Run details).
- `FollowupTask` + `isFollowupStep(step)` — in the CaseWorkspace task card body: when `isFollowupStep(view.step)`
  (draft / waiting / noresp1 / noresp2 / response) render `<FollowupTask caseId={caseId} />` in place of the generic
  title/paragraphs. The workspace `ActionBar` stays as is (server actions); in the draft step the editor's own
  "Approve and send" runs `send_communication` with `{channel, subject, attachments}`, so the integrator may hide
  `send_communication` / `update_communication_draft` from the ActionBar in that step to avoid a second button.
- `commandForms` — merge into `COMMAND_FORMS` (`src/features/case/command-forms.ts`) for ActionBar-driven forms.
- `RequestPage` — new route `src/app/requests/[requestId]/page.tsx`: `<RequestPage requestId={params.requestId} />`
  (cardholder role; the prototype's "Charge review" view). Shows only that request's questions and deadline.
- `previewStates` — for the VERA_PREVIEW=1 `/preview` route only (uses `dev-fixtures/`, imported only by `preview.tsx`).

Endpoints: `GET /api/cases/{id}/communications`, `GET /api/cases/{id}/communications/{item_id}`,
`GET /api/requests/{id}`, `GET /api/requests?mine=true`, `POST /api/requests/{id}/responses`.
Commands (via `runCommand`, key echoed): `update_communication_draft`, `send_communication`, `send_reminder`,
`draft_follow_up`, `review_cardholder_response`.
Query keys live under `caseKey(id)` so every command refreshes them. A 404 without a typed body renders "Not available yet".
Unsaved draft edits are kept in localStorage (`vera.comms.draft.<case>.<item>`) until saved or sent.
