# features/automations (VER-012-F10)

Mount points for the integrator:
- Routes (own files, already created): `src/app/automations/{workflows,specialists,policies}/page.tsx` render
  `WorkflowsPage`, `SpecialistsPage`, `PoliciesPage` from `@/features/automations`. The sidebar already links there.
- `previewStates` (from `@/features/automations`): mount in the `/preview` route (VERA_PREVIEW=1 only). It is the
  only importer of `dev-fixtures/`.
- `commandForms`: input fields for `publish_workflow_version` (reason) and `publish_policy_version`
  (receipt_threshold, reason).
- No case-workspace tabs are added.

Endpoints: `GET /api/automations/workflows/card-dispute`, `GET /api/automations/specialists`,
`GET /api/policies/{id}` and `/versions/{v}`, `POST /api/automations/commands/{name}` with
`{idempotency_key, expected_version, payload}`. The key and version are echoed from server-offered
`available_actions`. VER-014 does not return these yet, so command buttons stay hidden on the live API.
Wire → screen adapters: `api.ts` `fromWorkflowOut`, `fromSpecialistsOut`. Layout table: `layout.ts`.
