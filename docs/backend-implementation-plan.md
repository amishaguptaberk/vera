# Vera — Backend Implementation Plan (Phase 0 architecture gate)

Status: **draft for sign-off** · Nov 10, 2026 · No feature code starts until §16 is answered.

## 0. Sources and precedence

1. `docs/spec/Vera_Handoff.md` decisions D1–D8 and the orchestration prompt's "Resolved decisions"
2. `docs/spec/Vera_ToSpec.md` v1.1 (behavior, states, permissions)
3. `docs/spec/Vera_User_Stories.md` (acceptance)
4. `apps/web/prototype/Main.dc.html` (visual baseline; its local logic is a reference, not the state machine)

Where sources disagree, §15 records the reconciliation.

## 1. Repository map

```text
/apps/web                 frontend; /apps/web/prototype is the v34 baseline export
/services/api             FastAPI app: routers (queries, commands, ask, stream), auth/role dependency
/services/worker          job loop: specialist runs, adapters, deadlines, expiry, reconciliation
/packages/domain          pure Python: enums, Pydantic records, reducers, step derivation,
                          policy controller, closure checklist, action registry, snapshot hashing
/packages/workflows       workflow definitions (graph JSON v3), validation, dry run, LangGraph builder
/packages/adapters        typed simulated adapters: messaging, verification, telephony, credit, dispute, card control
/tests                    unit/, integration/ (Postgres), contracts/ (OpenAPI + CaseView schema)
/evals/replay             deterministic replay fixtures (ToSpec §15 1–24, Handoff §10.7 25–46)
/infra                    docker-compose.yml, Alembic migrations, dev scripts
/docs                     this plan, architecture notes, HACKATHON_READINESS.md (end)
/.scratch/vera/issues     tickets
```

Dependency direction: `domain` imports nothing internal; `adapters` and `workflows` import `domain`; `api` and `worker` import all three. `domain` has no SQLAlchemy, FastAPI or LangGraph imports, so reducers and policy are testable without a database.

## 2. Frontend routes and components (from the prototype)

The prototype is one design-component export (`Main.dc.html`, 4,717 lines) with a single logic class. It has no router; it switches on `state.screen` and `state.view`.

| Prototype switch | Target route (Handoff §1) | Read model |
|---|---|---|
| `screen: cases` | `/cases` | `GET /api/cases`, `/api/cases/summary` |
| `screen: case`, `view: analyst` | `/cases/:caseId?tab=&item=` | `CaseView` + evidence, communications, activity, runs |
| `view: cardholder` | `/requests/:requestId` | `GET /api/requests/{id}` |
| `view: reviewer` | `/cases/:caseId/review` | `CaseView` (reviewer / card_admin scope), decision packet |
| `screen: workflows` | `/automations/workflows/:id?version=` | workflow version, draft, validation, checks |
| `screen: agents`, `appearance` | `/automations/specialists/:id` | specialists |
| `screen: policies` | `/automations/policies/:id?version=` | policy versions |

Components are the ones contracted in Handoff §2 (`SummaryStrip`, `QueueTable`, `StatusRail`, `TaskCard`, `CommunicationsPanel`, `EvidenceRegister`, `DecisionPanel`, `RunDetails`, `ActivityTable`, `VeraRail`, `ControlPlan`, `ParallelTracks`, `ClosureChecklist`, `ChargeImpact`, workflow builder set).

## 3. Hardcoded state to replace

All prototype state is one object from `vFresh()`, persisted to `localStorage`. Each piece moves server-side:

| Prototype (function / field) | Replaced by |
|---|---|
| `vFresh()` seed, `localStorage` | Postgres seed + `POST /api/demo/reset` |
| `COMMANDS()` + `dispatch()` (32 commands, local Z schemas) | command gateway, §6 |
| `phaseOf(d)` | `domain.derive_step()`; persisted `cases.step` |
| `pc(d)` | Policy Controller, §9 |
| `ACTS()`, `actBtn()` | action registry → `available_actions` |
| `vm(d)`, `focus(d)`, `gapsOf`, `estOf`, `recOf`, `creditOf`, `conflictsOf` | `CaseView` projection |
| `closure(d)` | closure checklist (server) |
| `evHash(d)`, `apValid(d)` | evidence snapshot hash + approval binding, §10 |
| `d.idem`, `d.execs`, `execRec()` | `idempotency_keys` + executions view |
| `agentRun`, `runAgents`, `finishAgent`, `resumeAfterReload` | LangGraph run in the worker, §11 |
| `d.events`, `d.trace`, `d.feed` | `audit_events`, `workflow_steps`, `conversation_messages` |
| `answer()`, `intentOf()` | `POST /api/cases/{id}/ask` (read-only) |
| `gValidate`, `gSim`, `gPublish`, `G3()` | workflow validation / dry-run / publish services |
| `d.policy.thr` | `policy_versions.rules` |
| `dashRows()` display fixtures | seeded non-openable rows (`live: false`) |
| `view` (role switcher) | demo session role; never a command |
| demo drawer (`passDeadline`, `changeDelivery`, `dupReport`, OTP controls) | `/api/demo/*` endpoints, enabled only when `VERA_ENV=synthetic` |

UI-only state stays client-side: tab, selection, panel sizes, drawer open, zoom, draft text in progress.

## 4. Domain entities

Tables per ToSpec §10.1 plus Handoff §10.1 additions. Every table has `id`, `created_at`; mutable ones have `version`.

| Group | Tables |
|---|---|
| Case | `cases` (state, step, case_version, owner_id, waiting_on, due_at, workflow_version, policy_version, current_snapshot, hold JSON), `case_assignments`, `state_transitions` |
| Parties | `users` (+ `user_roles`), `cardholders` (contact_on_file), `merchants`, `card_transactions` |
| Intake | `reports` (immutable), `claims` |
| Evidence | `evidence_records`, `evidence_versions` (append-only, current/superseded), `findings` (type, status, conflict status, resolved_by), `finding_links`, `attachments` |
| Communications | `communications`, `communication_drafts`, `communication_responses`, `identity_verifications` (+ `verification_attempts`), `callbacks` (attempt, transcript JSON, result JSON, notes) |
| Decision | `decision_packets` (version, snapshot_hash, sections), `decisions`, `policy_evaluations`, `approvals` (binding columns + status) |
| Execution | `provisional_credits`, `dispute_packets`, `control_plans`, `card_controls`, `idempotency_keys`, `jobs` |
| Automations | `workflow_definitions`, `workflow_versions` (immutable graph), `workflow_drafts`, `workflow_check_runs`, `workflow_runs`, `workflow_steps`, `specialist_definitions`, `policy_versions`, `policy_drafts` |
| History | `audit_events` (append-only, `actor_id`, `actor_role`), `conversation_messages` |
| LangGraph | checkpointer tables (managed by `langgraph-checkpoint-postgres`) |

Immutability is enforced in the database, not only in code: `audit_events`, `reports`, `evidence_versions`, `state_transitions` and published `workflow_versions` / `policy_versions` get `BEFORE UPDATE OR DELETE` triggers that raise.
