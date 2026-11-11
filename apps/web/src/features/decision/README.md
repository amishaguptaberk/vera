# features/decision — decision packet, reviewer view, Vera rail (VER-012-F7, VER-012-F9)

Mount (integrator; nothing here is wired yet):

1. **Decision tab** — `src/features/case/CaseWorkspace.tsx`, the `{tab === 'decision' ? <DecisionPanel c={c} /> : null}` line:
   replace the inline `DecisionPanel` with `import { DecisionPanel } from '@/features/decision'` and render
   `<DecisionPanel c={c} selected={sel} onSelectRecord={selectRecord} />`. (`tabs` export carries the same.)
2. **Reviewer "Approvals" view** — where the reviewer role opens a case (prototype `__vera.setView('reviewer')`), in the
   left column (prototype `.colM`): `<ReviewerPanel c={c} selected={sel} onSelectRecord={selectRecord} />`.
   Charge impact (`.colR`) stays the existing component.
3. **Vera rail** — as the right sibling of the case `<main>` inside the shell row (prototype `aside#vera-rail` after
   the main column): `<VeraRailPanel c={c} role={role} open={veraOpen} onClose={() => setVeraOpen(false)} selected={sel}
   onSelectRecord={selectRecord} onNavigate={(t) => router.push(...)} />`. Put `<VeraButton open={veraOpen}
   onToggle={...} />` in the case header bar (prototype line 1526). The button and close X are visible below 1280px only;
   at ≥1280px the rail is inline (CSS in components/decision/VeraRail.module.css).
4. **Command forms** — merge `commandForms` into `features/case/command-forms.ts` `COMMAND_FORMS` (record_decision,
   return_decision, reassign_reviewer).

Endpoints: `GET /api/cases/{id}/decision-packet?version=`, `POST /api/cases/{id}/ask`, `GET /runs`, `GET /activity`,
commands via `useRunCommand` (approve_decision, return_decision, plus whatever the server offers in available_actions).
