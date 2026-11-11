# features/money — credit, parallel tracks, dispute, card controls, closure (VER-012-F8)

## What to mount (integrator)

1. `src/features/case/CaseWorkspace.tsx`, inside `<section id="task">`, after the `<h2 data-testid="next-action">` title:
   when `MONEY_STEPS.has(c.step)`, render `<MoneyTask caseId={caseId} c={c} onOpenRecord={selectRecord} />`
   **instead of** the generic `<ActionBar>` (MoneyTask renders the server's `available_actions` itself, because the
   control-list / message-body payloads come from its own UI state). Keep the generic ActionBar for every other step.
2. `src/features/case/command-forms.ts`: spread `commandForms` from `@/features/money` into `COMMAND_FORMS`
   (reason inputs for `skip_card_controls`, `decline_card_controls`) if those payloads have no server defaults.
3. Tabs: none (`tabs` is empty). ChargeImpact already exists in CaseWorkspace and reads `charge_impact` from the server.
4. Card-admin view: nothing extra — the role selector's "Reviewer · card admin" switches the session role; the server
   then returns approve/decline/apply in `available_actions` and MoneyTask renders them.

## Endpoints / commands
- `GET /api/cases/{id}/closure-checklist` (VER-011) — key `[...caseKey(id), 'closure-checklist']`; 404 → "not available yet".
- `GET /api/cases/{id}/remediation` (VER-010 MoneyView) — tracks + control-plan names; 404 → tracks fall back to optional CaseView fields, else hidden.
- `GET /api/cases/{id}/final-message` (VER-011) — seeds the final draft editor.
- `GET /api/cases/{id}/executions` (VER-010) — `executionsQuery` exported, not yet rendered.
- `close_case` payload `{reason, outcome}` is collected by MoneyTask's inline form (`commandForms`).
- Preview: `previewStates` (preview.tsx) uses `dev-fixtures/` only; mount it in the VERA_PREVIEW=1 /preview route.
- Commands via `useRunCommand` (key echoed from the action): `issue_provisional_credit`, `lookup_execution_result`,
  `prepare_dispute_packet`, `open_dispute_packet`, `review_dispute_packet`, `submit_dispute`, `propose_card_controls`
  (`{controls}`), `skip_card_controls`, `approve_card_controls` (`{controls}`), `decline_card_controls`,
  `apply_card_controls`, final message commands (`update_final_message` / `send_final_message` get `{body}`), `close_case`.

## Contract
`contract.ts` — `MoneyCaseView` extends the generated `CaseView` with the Handoff §3.2 fields `credit`, `dispute`,
`controls`, plus `control_plan` and `final_message` (GAPS until the backends expose them). Re-align after VER-010/011 merge.
