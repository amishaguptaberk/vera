# Vera — Fable / Claude Agent-Team Backend Build Prompt

Use this as the single implementation prompt. Attach `Vera_ToSpec.md`, `Vera_User_Stories.md`, `Vera_Handoff.md`, the current HTML prototype, and `amisha-skills.plugin`.

## Mission

Build Vera as a real, replayable finance-operations application behind the existing prototype. Use Claude Agent Teams for parallel work, but use the attached plugin's `run-tickets` skill for discipline:

```text
scout → contract → builder → reviewer → commit
```

Do not run an unstructured “build the backend” task. Every change must be a small, user-visible vertical slice with tests, persistence, permissions, events, and a reviewer pass.

## Read first

Read these files before creating tickets or code:

- `Vera_ToSpec.md`
- `Vera_User_Stories.md`
- `Vera_Handoff.md`
- current Vera HTML prototype
- `amisha-skills.plugin`, especially:
  - `skills/run-tickets/SKILL.md`
  - `skills/run-tickets/contract.md`
  - `skills/run-tickets/workflows.md`
  - `skills/improve-codebase-architecture`
  - `skills/diagnosing-bugs`
  - `skills/impeccable` for UI tickets

The handoff and spec are the behavior contract. The prototype is the visual baseline. Do not redesign the product during backend implementation.

## Resolved decisions

- Cases uses the five-column queue: Case, What’s blocking it, Next action, Owner, Due.
- `card_admin` is a separate backend role. Dana may hold reviewer and card-admin permissions in the demo, but the permissions and audit events remain separate.
- After provisional credit, dispute preparation and prevention planning are parallel branches.
- Store complete workflow node types in the domain model; map to visual categories only in the UI.
- Vera becomes a right-side drawer below 1280px.
- “Synthetic environment” appears once in the top bar. Use “No funds moved” only on relevant money surfaces.
- The analyst recommends controls. The card administrator approves and applies them.
- The cardholder enters the OTP in the Cardholder view/app. The analyst sees only verification status.

## Architecture

Use:

- Python 3.12
- FastAPI
- PostgreSQL
- SQLAlchemy 2
- Pydantic
- LangGraph
- Postgres checkpointer
- Redis or a small worker queue
- typed simulated adapters
- append-only audit events
- idempotency records
- SSE or polling
- OpenTelemetry/Langfuse
- pytest, Ruff, mypy
- Docker Compose

Suggested repository:

```text
/apps/web
/services/api
/services/worker
/packages/domain
/packages/workflows
/packages/adapters
/tests
/evals
/infra
/docs
```

LangGraph is the workflow runtime. Do not build a separate scheduler product. LangGraph handles graph execution, branches, parallel evidence work, human interrupts, checkpointing, and resume. It does not own authority, permissions, money approval, policy overrides, or unrestricted database writes.

The frontend renders backend `CaseView` and `available_actions`. It must not infer state or permissions from chat, animation, or local component flags.

## Agent-team roles

Create isolated teammates/worktrees with disjoint ownership:

1. **Architecture lead — strongest reasoning model**
   - domain/state/API contract
   - dependency graph
   - final architecture review

2. **Domain builder — strong coding model**
   - models, migrations, reducers, events, idempotency

3. **Workflow builder — strong coding model**
   - LangGraph, specialists, interrupts, checkpoints, workflow fixtures

4. **API builder — strong coding model**
   - FastAPI commands, queries, projections, roles, available actions

5. **Communications/adapters builder — strong coding model**
   - messages, replies, attachments, OTP/push, callback, simulated adapters

6. **Evaluation/CI builder — fast coding model**
   - tests, replay fixtures, CI, Docker test setup, contract tests

7. **Final verifier council — strongest reasoning model**
   - independent hackathon-readiness review after all tickets pass

No two agents may edit overlapping core files simultaneously.

## Phase 0 — architecture gate

Before feature code, create `docs/backend-implementation-plan.md` containing:

- repository map
- frontend routes and components
- hardcoded state to replace
- domain entities
- canonical states and transitions
- command envelope
- API contracts
- event types
- LangGraph nodes/edges
- worker jobs
- role/permission matrix
- idempotency boundaries
- evidence snapshot/stale-approval behavior
- evaluation plan
- ticket dependencies
- unresolved assumptions

Do not start implementation until this contract is internally consistent.

## Ticket creation

Create ready tickets under `.scratch/vera/issues/`.

Every ticket must contain:

```text
Status: ready-for-agent
Title:
User value:
Scope:
Non-goals:
Acceptance criteria:
Dependencies:
Test-first behavior:
Demo proof:
```

Tickets must not guess file paths. The scout discovers exact paths, symbols, nearest tests, and verified commands before the builder contract is written.

Every builder contract must contain:

```text
TICKET:
GOAL:
ACCEPTANCE:
SEAM:
TEST FIRST:
NEAREST TEST:
OWNS:
DO NOT TOUCH:
PATTERNS:
CONTEXT:
CHECKS:
SKILLS:
FINDINGS:
```

Keep contracts under 80 lines.

## Vertical slices

Implement these in dependency order. Each ticket must leave the application runnable.

### VER-001 — Persist and read CHG-1042

Seed the canonical case and expose a real case projection containing state, amount, merchant, owner, due date, workflow version, and available actions. Emit `case.created`. Test duplicate creation.

### VER-002 — Canonical commands and available actions

Implement the command dispatcher, role/action matrix, valid and invalid transitions, typed errors, and append-only events. Expose `GET /cases/{id}/available-actions`.

### VER-003 — LangGraph investigation

Run Charge Investigator, Related-Transaction Investigator, and Receipt and Document Reviewer. Support parallel evidence work, typed findings, evidence links, Postgres checkpointing, and resume after interruption.

### VER-004 — Evidence provenance and conflicts

Persist source records, claims, findings, links, supporting/missing/conflicting/superseded statuses, evidence snapshot hashes, and stale-approval invalidation.

### VER-005 — Follow-up, approval, reply, attachment

Create a targeted message draft, require analyst approval, simulate delivery, persist the cardholder reply and attachments, update Communications and Activity, and make send idempotent.

### VER-006 — OTP/push identity verification

Implement `ready_to_verify → request_sent → awaiting_cardholder_verification → identity_verified` plus failed, expired, denied, and locked states. Never persist raw OTP. Successful verification enables callback but does not determine charge authorization.

### VER-007 — Analyst-approved callback

Require identity verification and analyst approval before callback. Persist transcript and structured result separately. Support confirmed, contradicted, voicemail, no-answer, and incomplete outcomes.

### VER-008 — Deterministic Policy Controller

Evaluate current evidence with versioned deterministic rules. Return blocked, needs-evidence, eligible, or ineligible. Chat and model text cannot bypass policy.

### VER-009 — Decision packet and reviewer action

Prepare the packet with evidence links, findings, conflicts, gaps, policy result, and recommendation. Bind approval to case, transaction, evidence hash, policy version, and workflow version. Support approve and return. Reject stale approval.

### VER-010 — Credit, dispute, and controls

Implement simulated provisional credit, dispute lifecycle (`prepared → ready_for_review → ready_to_submit → submitted`), prevention plan, card-admin approval, and card-control application. All actions execute exactly once.

### VER-011 — Final communication and closure

Implement final message, closure checklist, monitoring, closed state, incomplete-work blockers, recorded-action-only messaging, and closed-case rejection.

### VER-012 — Connect frontend to backend

Replace hardcoded UI state gradually. Connect Cases, case workspace, Evidence, Communications, Decision, Activity, and Run details to backend projections. Preserve tabs, scroll, drafts, panel sizes, and non-blanking transitions.

### VER-013 — Evaluation and CI

Build deterministic replay fixtures for recognized charge, no reply, incomplete reply, conflict, OTP outcomes, callback outcomes, reviewer approve/return, stale approval, duplicate actions, uncertain adapter result, immutable workflow versions, unauthorized actions, closed-case rejection, refresh mid-run, failed workflow checks, and required-control removal.

## Required command rules

Every consequential command validates:

- actor role
- case state
- workflow version
- policy prerequisites
- evidence snapshot
- expected case version
- idempotency key

Every command returns:

- updated projection
- resulting event
- available next actions
- typed blocking reason when unavailable

Minimum commands include:

```text
start_investigation
create_follow_up
approve_send
record_reply
request_verification
verify_identity
approve_callback
start_callback
record_call_result
evaluate_policy
prepare_decision_packet
approve_decision
return_decision
issue_provisional_credit
prepare_dispute
approve_card_controls
apply_card_controls
send_final_communication
hold_case
resume_case
close_case
```

## Idempotency and recovery

Messages, verification requests, callbacks, credit, disputes, and card controls must be retry-safe.

Before an adapter call:

1. persist the idempotency key
2. acquire the command execution record
3. execute the adapter
4. persist completed, failed-before-effect, or uncertain result
5. emit one event

A retry returns the original result when already completed. Uncertain results go to reconciliation, never false success.

## Ticket execution gates

For every ticket:

1. scout finds paths, symbols, tests, and commands
2. orchestrator writes contract
3. builder writes the first failing behavior test
4. builder implements the smallest complete slice
5. builder reports exact command output
6. reviewer inspects the diff independently
7. reviewer returns `pass`, `repair_required`, `spec`, or `inconclusive`
8. only a reviewer pass permits commit
9. recompute the frontier

At most three builders run in parallel. Parallelize only tickets with disjoint `OWNS` paths.

Never weaken acceptance criteria. Never mark a ticket complete without reviewer pass. Never claim tests passed without output. Do not push remotely.

## First demo slice

Prioritize this complete path before expanding:

```text
CHG-1042
→ persisted case
→ investigation
→ evidence findings
→ targeted follow-up
→ analyst approval/send
→ cardholder reply
→ OTP/push verification
→ callback transcript
→ Policy Controller
→ reviewer decision packet
```

Then complete:

```text
→ provisional credit
→ dispute packet
→ prevention plan
→ card-admin approval/application
→ final communication
→ monitoring/closure
```

## Test gates

Use the repository’s real commands. If missing, document them in `CONTRIBUTING.md`.

```bash
docker compose up -d postgres redis
alembic upgrade head
ruff check .
mypy .
pytest -q
pytest tests/integration -q
pytest tests/contracts -q
pytest evals/replay -q
npm test
npm run build
```

CI fails on invalid transitions, unauthorized actions, duplicate money-like actions, stale approvals, published workflow mutation, missing Activity events, unexpected adapter calls, replay mismatch, API drift, or frontend actions rejected by the backend.

## Final verifier council

After all tickets pass and the full suite is green, do not add more features immediately. Spawn an independent verifier council.

### Product judge

Check whether the problem is clear in 30 seconds, the 3-minute demo is compelling, Vera is more than a chatbot, the human-control story is obvious, and the scope is believable.

### Architecture reviewer

Check FastAPI/Postgres/LangGraph boundaries, durable state, resumable workflows, typed commands, canonical projections, retries, concurrency, and absence of UI-only fake backend behavior.

### Finance/security reviewer

Attempt unauthorized credit, policy override, evidence mutation, closure, control application, and OTP misuse. Verify reviewer/card-admin separation and honest simulated boundaries.

### UX reviewer

Inspect the Cases queue, case workspace, Communications, Evidence, Decision, Activity, Run details, specialist page, workflow builder, responsive layouts, panel resizing, state transitions, and specialist motion. Look specifically for repetition, blanking, clipping, and AI-dashboard styling.

### Submission reviewer

Verify clean reset/replay, README setup, architecture diagram, demo script, current screenshots/video, CI, known limitations, and repository clarity.

Each reviewer returns:

```text
VERDICT: PASS / NEEDS FIXES / BLOCKED
P0 BLOCKERS:
P1 HIGH-VALUE FIXES:
P2 POLISH:
EVIDENCE: commands, tests, screens, replay scenarios
RECOMMENDATION: ship / P0 only / P0 + selected P1 / do not expand
```

The council must reset the database, replay CHG-1042, switch roles, attempt unauthorized actions, retry money-like actions, change evidence after approval, inspect Communications and Activity, resize panels, test desktop/mobile widths, and run the full eval suite.

Produce:

```text
HACKATHON_READINESS.md
```

It must contain the final verdict, prioritized fixes, five-minute demo script, architecture explanation, setup instructions, known limitations, future work, and exact tests run.

Only implement P0 issues automatically. Implement P1 issues only when small, low-risk, and non-expansive.

The build is complete only when CHG-1042 replays from a clean database, the existing frontend is driven by backend projections, all consequential actions are idempotent, role permissions are server-enforced, policy cannot be bypassed, workflow versions are immutable, CI is green, the verifier council passes, and the demo works from a clean start.
