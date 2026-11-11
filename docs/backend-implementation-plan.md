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

## 5. Canonical states and transitions

Two persisted levels (Handoff §4.1):

- `state` — ToSpec §6 enum: `reported, investigating, waiting_on_cardholder, response_received, evidence_review, callback_pending, callback_completed, decision_pending, policy_blocked, credit_eligible, reviewer_pending, credit_approved, credit_issued, dispute_prepared, remediation_pending, monitoring, closed, held`.
- `step` — `intake, working, draft, waiting, noresp1, noresp2, response, idv, verify, callfail, packet, decide, returned, stale, waitrv, issue, credit_check, controls, ctl_prep, dsp_prepare, dsp_open, dsp_review, dsp_submit, dsp_failed, waitctl, ctl_apply, finalprep, final, close, monitoring, closed, onhold`.

Rules:

1. `derive_step(case_data) -> (state, step)` is one pure function in `packages/domain`. It is called inside the command transaction after the reducer runs; the result is stored on `cases` and in `state_transitions`. Nothing else writes `state` or `step`.
2. `policy_blocked` / `credit_eligible` / `callback_completed` stay in the enum for audit but a case does not rest in them; the policy outcome is carried on `policy` while the case is in `decision_pending` (Handoff §4.1).
3. After credit (or a dispute-without-credit decision) the dispute and control tracks are independent sub-statuses (`dispute.status`, `controls.status`). `step` is the focused track's step; `final` is unreachable until both have an outcome (D3).
4. `held` stores the prior `(state, step)` inputs, not a copy of the result: resume re-derives, so failures recorded before the hold are still there.
5. The transition table is Handoff §4.2 rows 1–32, encoded as data (`TRANSITIONS`) and tested row by row.

Every transition row stores: prior/next state and step, actor, actor role, reason, case version, workflow version, policy version, evidence snapshot hash, event id, timestamp.

## 6. Command envelope and gate order

`POST /api/cases/{case_id}/commands/{command}` with `{idempotency_key, expected_case_version, payload}`; the acting user and role come from the session, never the body.

Gate stages, in order (each recorded as a stage in Run details):

| # | Stage | Failure |
|---|---|---|
| 1 | Role — command's single required role is held by the session and is the role acted under | 403 `role_forbidden` |
| 2 | Schema — Pydantic payload model | 422 `schema_invalid` |
| 3 | Idempotency replay — key already `completed` → return original result, `status: replayed`, attempts+1; key `checking` → 504 `adapter_uncertain` | — |
| 4 | Case version — `expected_case_version == cases.case_version` (row lock) | 409 `stale_case_version` |
| 5 | Closed — closed/monitoring rejects all but `record_dispute_outcome` | 409 `case_closed` |
| 6 | Step — command allowed in current step | 409 `invalid_step` |
| 7 | Policy — Policy Controller on current evidence for money/control/closure commands | 422 `policy_blocked` |
| 8 | Permission — prerequisites (approval binding current, identity verified, attempt limits) | 409/422 typed |
| 9 | Transaction — write key `pending`, run reducer, derive step, bump `case_version`, append events; commit | — |
| 10 | Adapter (Sim commands only) — outside the DB transaction; then persist `completed` / `failed_before_effect` / `checking` and emit one event | 502 / 504 |

Response: `{status: recorded|replayed, result, event_ids, case: CaseView}`. Errors: `{code, message, blocked_reason?, failed_rules?, case_version}`.

Each command is one registry entry: `CommandSpec(name, role, payload_model, allowed_steps, key_template, policy_gate, prerequisites, reducer, adapter?, events, label, style)`. `available_actions` is computed from the same registry by running stages 1 and 5–8 without side effects, so the UI cannot show an action the gateway would reject.

## 7. API contracts

Queries and commands exactly as Handoff §3.2–§3.4 and §10.2. Additions:

- `GET /api/cases/{id}/available-actions` (prompt VER-002) — same `ActionView[]` embedded in `CaseView`.
- `GET /api/session`, `POST /api/session/role` — demo role selection (view change only; writes nothing to the case, no event).
- `POST /api/demo/reset`, `/api/demo/advance-clock`, `/api/demo/material-change`, `/api/demo/adapter-fault` — synthetic environment only.
- OpenAPI is generated from the Pydantic models and snapshot-tested in `tests/contracts`; `CaseView` TypeScript types are generated from it for the frontend.

Auth for the demo: a signed session cookie holding `user_id` and `active_role`; `active_role` must be in `user_roles`. Seed: Sam Rivera (`analyst`, `ops_admin`), Dana Okafor (`reviewer`, `card_admin`), Priya Shah (`cardholder`). Service principals: `specialist:<name>`, `policy_controller`, `system`, `adapter:<name>`.

## 8. Event types

The list in Handoff §10.5 is the registry (`packages/domain/events.py`, one enum). `run.step_*` are stream-only. Each audit event: `{event_id, type, case_id, case_version, at, actor_id, actor_role, record_ids[], summary, detail}`. Delivery to browsers: SSE at `/api/cases/{id}/stream`, fed by Postgres `LISTEN/NOTIFY` on insert; clients refetch `CaseView` on a new `case_version`. Polling `GET /api/cases/{id}` is the fallback.

## 9. Policy Controller

Pure function `evaluate(policy_version_rules, evidence_snapshot, case_facts) -> PolicyResult`; no model, no I/O. Result shape is Handoff §7.4 plus `status: blocked | needs_evidence | eligible | ineligible` (prompt VER-008). Persisted in `policy_evaluations` on every evidence change and before every gated command. Policy v1 rules are data (`rule_id`, group, predicate name, params such as receipt threshold 75); predicates are code.

## 10. Roles, idempotency, snapshots

**Role/permission matrix:** Handoff §5 is the contract; it is encoded once as `CommandSpec.role` and tested as a full command × role table (every non-permitted pair must return 403). `reviewer` and `card_admin` are distinct; Dana holding both never merges them, and each event records the single role used (D2). Analyst cannot apply controls (D7). Only the cardholder role can call `submit_otp` (D8).

**Idempotency boundaries:** keys per Handoff §10.6 (including new `idv-cancel:` / `idv-expire:` keys, gap G1). `idempotency_keys(key PK, command, status pending|completed|failed_before_effect|checking, request_id, attempts, first_at, last_at, result)`. For adapter commands the key row is committed before the adapter is invoked; adapters accept the key and are themselves idempotent on it, and expose `lookup(key)`. `checking` is resolved only by `lookup_execution_result` or the reconciler — never by re-sending. Unique constraints back this up: one credit per transaction, one submission per dispute, one application per control plan.

**Evidence snapshot and stale approval:** `snapshot_hash = sha256(canonical JSON of the sorted current evidence version ids and the material fields used by policy rules)`. Material fields are ToSpec §7.4. On `evidence.version_added`: append version → recompute hash → compute affected checks from a `rule → evidence kinds` map → mark only those checks and any approval whose bound hash differs as `stale` (original rows kept) → re-evaluate policy → derive step (`stale`). Approvals bind `(case, transaction, snapshot_hash, policy_version, workflow_version)`; `issue_provisional_credit` re-checks the binding at stage 8.

**OTP:** the code is never stored or logged. `identity_verifications` keeps an HMAC of the code, attempts, expiry, cooldown. The simulated SMS adapter holds the code in a short-lived outbox readable only by the cardholder session (and by the labeled synthetic-demo control acting as the cardholder). A test greps analyst responses, events and logs for the code (fixture 42).

## 11. LangGraph nodes and edges

LangGraph runs specialists and holds the run's position; it never writes case state directly. Nodes call domain services through the same typed tool gateway, and human steps are `interrupt()` points resumed by the command gateway after a command commits.

- Graph is built from the pinned `workflow_versions.graph` by reading each node's `kind` (D4), so v3 in the builder and the executed graph are the same data.
- Nodes: Handoff §10.3 (21 nodes). Edges: v3 outcomes in Handoff §7.2, with retry limits (follow-up 2, contradicted verification 2, reviewer rejection 2, not-eligible 1, callback attempts 2 per response).
- Parallelism: `charge_investigator` ∥ `related_transaction_investigator` → `receipt_document_reviewer` → `pc1`; after `credit_executor`, `dispute_packet_preparer` ∥ `prevention_planner` → join before `final_communication` (D3).
- Checkpointer: `PostgresSaver`, `thread_id = run_id`. Refresh or worker restart resumes from the last checkpoint; an interrupted step is shown as interrupted, never as complete.
- Specialists are deterministic, fixture-backed functions behind a `Specialist` protocol with typed input/output models and a declared record scope enforced by the tool gateway (out-of-scope read raises). A model-backed implementation can be swapped in per specialist later; CI and replay always use the deterministic one.

## 12. Worker jobs

One worker process, Postgres-backed queue (`jobs` table, `FOR UPDATE SKIP LOCKED`); no Redis required. Jobs per Handoff §10.4: `specialist_runner`, `adapter_executor`, `deadline_watcher`, `verification_expirer`, `uncertain_result_reconciler`, `policy_reevaluator`, `workflow_check_runner`, `dispute_outcome_ingest`, `notification_fanout`. Time comes from an injectable demo clock (starts Nov 10, 9:08 AM) so deadlines and expiry are deterministic in tests and fast-forwardable in the demo.

## 13. Evaluation plan

- `tests/unit` — reducers, `derive_step` (every Handoff §4.2 row), policy rules, snapshot hashing, closure checklist, workflow validation rules 1–9.
- `tests/integration` — gateway against Postgres: role table, stale version, idempotent replay, adapter failed-before-effect and uncertain, DB immutability triggers, concurrency (two simultaneous credit commands → one credit).
- `tests/contracts` — OpenAPI snapshot; every enabled `available_action` is accepted and every blocked one is rejected with the stated reason.
- `evals/replay` — fixtures 1–46, each a YAML script of commands with assertions on state, step, available actions, evidence status, findings/claims, policy result, approval validity, event sequence, idempotency rows, adapter call counts and recovery action. Failure output names case, workflow version, step and invariant (US-K03).
- Playwright — analyst, cardholder, reviewer/card-admin, material-change journeys (with VER-012).
- CI (GitHub Actions): ruff, ruff format --check, mypy, alembic upgrade on a Postgres service, pytest (unit, integration, contracts, replay), frontend test + build.

## 14. Ticket dependencies

```text
VER-001 persist/read CHG-1042 (includes repo scaffold, migrations baseline, seed, reset)
  └─ VER-002 command gateway + available actions
       ├─ VER-004 evidence provenance, snapshots, stale invalidation
       │    ├─ VER-003 LangGraph investigation (writes findings through VER-004 records)
       │    ├─ VER-005 follow-up, send, reply, attachment
       │    │    └─ VER-006 OTP/push identity verification
       │    │         └─ VER-007 analyst-approved callback
       │    └─ VER-008 Policy Controller
       │         └─ VER-009 decision packet + reviewer action   (also needs VER-007)
       │              └─ VER-010 credit, dispute, controls
       │                   └─ VER-011 final communication + closure
       ├─ VER-012 frontend connection — sliced: 012a Cases + case shell after 002; 012b–e follow each backend slice
       └─ VER-013 evaluation + CI — harness after 002; fixtures added with each slice; full suite last
```

Parallel frontiers (max three builders, disjoint `OWNS`): after 002 → {004, 012a, 013 harness}; after 004 → {003, 005, 008}; then {006 → 007} alongside 008; 009, 010, 011 are serial because they share the gateway registry and case reducer.

The prompt lists VER-004 after VER-003, but 003 needs somewhere typed to write findings, so 004's record layer goes first. Not covered by any listed ticket: workflow/specialist/policy draft-validate-check-publish APIs (Epic H, I; fixtures 39–41, 46). Proposed **VER-014 Automations versioning**, depending on 003 and 008 — see §16 U5.

## 15. Reconciliations between sources

| # | Conflict | Resolution |
|---|---|---|
| R1 | Prompt command names (`create_follow_up`, `approve_send`, `record_reply`, `request_verification`, `verify_identity`, `approve_callback`, `record_call_result`, `prepare_decision_packet`, `prepare_dispute`) differ from Handoff §3.3 | Handoff names are canonical (`draft_follow_up`, `send_communication`, `submit_cardholder_response`, `send_verification_request`, `submit_otp` / `answer_verification_push`, `start_callback`, `record_callback`, `create_decision_packet`, `prepare_dispute_packet`). `approve_callback` is not a separate command: `start_callback` by the analyst is the approval and emits `callback.approved` + `callback.started`. |
| R2 | Handoff gate order lists Idempotency after Permission, then says it runs before the step check | Replay lookup is stage 3 (§6); the key is written in stage 9. |
| R3 | Policy vocabulary: prompt `blocked/needs-evidence/eligible/ineligible` vs Handoff `code` + `credit_eligible` | Both: `status` (four values) and `code`/`label`. |
| R4 | Identity states: prompt adds `failed`, `locked`; Handoff adds `cancelled` | Enum: `ready_to_verify, request_sent, awaiting_cardholder_verification, identity_verified, locked, expired, denied, cancelled, failed`. `locked` = three wrong codes (analyst label `Verification failed`); `failed` = request could not be delivered. |
| R5 | Callback outcomes: prompt has five, Handoff three | `confirmed, contradicted, voicemail, no_answer, incomplete`; only `confirmed` satisfies the check. |
| R6 | ToSpec lists Redis and "LangGraph only if needed"; prompt makes LangGraph the runtime and allows "Redis or a small worker queue" | LangGraph + Postgres checkpointer; Postgres job queue; no Redis. |
| R7 | ToSpec §13.2 `Work to review` columns vs D1 | D1 five-column queue. |
| R8 | ToSpec: analyst/admin applies controls; D7 | Card admin approves and applies. |
| R9 | `docker compose up -d postgres redis` in the test gates | Compose file ships with `postgres` only (plus api, worker, web). This build workspace has no Docker daemon, so local runs use the installed Postgres 16 binaries via `infra/dev-db.sh`; the compose path will be written but can only be verified on a machine with Docker. |
| R10 | Python 3.12 required; workspace default is 3.13 | venv on the installed `python3.12`. |

## 16. Unresolved assumptions — need an answer before VER-001

| # | Question | Default if unanswered |
|---|---|---|
| U1 | **Frontend path.** The prototype is a 611 KB single-file design export on a custom runtime; ToSpec recommends Next.js. Option A: keep the export and swap its logic class's state for API calls (fastest, pixel-identical, hard to maintain). Option B: port to Next.js/React components replicating the markup and tokens (matches ToSpec, more work, risk of visual drift). | A for the demo |
| U2 | **Where the repo lives.** It is currently only in the cloud workspace; nothing is pushed. A connected folder on your computer or a GitHub repo is needed for the work to outlive this session. | stay local, no push |
| U3 | **Model-backed specialists.** Deterministic fixture-backed specialists first; optional model phrasing later. Is a model call wanted in the demo at all, and with which key/runtime? | deterministic only |
| U4 | **Ticket skills.** `to-tickets` and `run-tickets` in the plugin are user-invoked only; the assistant cannot start them. | wait for you to run them |
| U5 | **VER-014 Automations versioning** as an added ticket (see §14). | add it |
| U6 | ToSpec §18 #1–3 are settled by the prototype (five controls, immediate synthetic credit, full transcript + structured record). #4–7 (runtime, Langfuse in CI, auth, retention) remain open; defaults: LangGraph, Langfuse off in CI, demo cookie session, no retention policy. | as stated |
