# Vera — Implementation Specification

## Product requirements, behavior contract, architecture, and evaluation plan

**Version:** 1.1
**Date:** November 10, 2026
**Status:** Implementation-ready hackathon specification
**Product:** Vera
**Primary case:** CHG-1042 · Northstar Equipment · $2,840.00

> This document is the canonical contract for Vera’s next implementation pass. It supersedes the earlier supplier-payment/bank-detail PRD wherever the two conflict. The current product is a post-report corporate-card investigation workspace.

---

## 1. Product definition

Vera helps finance teams resolve suspicious corporate-card charges after a cardholder reports a problem. It assembles transaction and purchase evidence, requests missing information, records structured verification, prepares a decision, routes the decision to a human reviewer, and carries the case through credit, dispute preparation, remediation, communication, and closure.

**Product promise:** Turn a suspicious charge into a clear, evidence-backed, human-controlled resolution.

Vera is not a generic chatbot, a fraud verdict engine, or an unrestricted autonomous finance agent. Vera investigates and coordinates work. People make consequential decisions. Deterministic policy code controls money-affecting actions.

### 1.1 Product principles

1. **Claims are not facts.** A report, reply, document, or model output starts as a claim or source record. It becomes a supported finding only through permitted evidence assessment.
2. **Agents recommend; people decide.** Specialists can inspect, compare, draft, recommend, and hand off. They cannot approve credit, change source records, override policy, or close cases.
3. **Policy is code, not prose.** A message cannot satisfy a policy rule or bypass a permission.
4. **Evidence is versioned.** A material change reopens only affected checks and invalidates approvals bound to the changed evidence.
5. **Every consequential action is explicit.** Sending, calling, approving, issuing credit, applying a card control, and closing a case require a visible action with a recorded actor.
6. **The current state is always legible.** Every case exposes its state, owner, blocker, next action, and recovery path.
7. **Simulation is honest.** Synthetic data and simulated adapters are labeled, and no screen implies that real money, cards, banks, or external communications were affected.

---

## 2. Scope decisions

### 2.1 In scope for the first complete build

- Post-report corporate-card charge investigation.
- One continuous synthetic case across Finance analyst, Cardholder, and Reviewer views.
- Evidence collection, comparison, provenance, versioning, and conflict handling.
- Cardholder follow-up with text and attachments.
- Optional analyst-approved simulated callback/verification.
- Related-transaction search and separate case scoping.
- Decision packet preparation.
- Deterministic policy evaluation.
- Reviewer approval or return.
- Simulated provisional credit.
- Simulated dispute packet preparation.
- Simulated card-control recommendation/application.
- Final communication and monitoring/closure.
- Bounded finance specialists and versioned workflows.
- Immutable active policies and workflow versions.
- Append-only activity and execution traces.
- Idempotency, stale-approval invalidation, retries, and recovery.
- Evaluation fixtures and CI regression checks.

### 2.2 Explicitly out of scope

- Live bank, card-network, ERP, email, telephony, or dispute integrations.
- Bank-grade account ownership or identity verification.
- Automatic fraud declarations or law-enforcement reports.
- Arbitrary user-created autonomous agents.
- Arbitrary code execution in workflows.
- Autonomous money movement.
- Automatic source-record mutation.
- Graph database infrastructure.
- A multi-agent swarm with unrestricted peer-to-peer authority.
- Real provisional funds or accounting entries.

### 2.3 Superseded material

The previous prototype centered on `VER-1042` / `PAY-1042`, a changed supplier bank-detail workflow. That remains useful as historical design material but is not the primary product contract. The canonical demo is now `CHG-1042`, a post-report corporate-card investigation. Any supplier/bank-detail concepts retained in code must be isolated as legacy fixtures or removed from the primary navigation and demo.

---

## 3. Actors and permissions

| Actor | Can do | Cannot do |
|---|---|---|
| Cardholder | View assigned request, answer focused questions, attach files, submit response | View internal evidence, approve credit, edit transaction/vendor records |
| Finance analyst | Investigate, inspect evidence, request information, approve a callback, prepare/hold/resume/reassign cases, submit decision packet, apply permitted remediation | Override policy, approve own required reviewer checkpoint, silently edit source records |
| Finance reviewer | Inspect packet/evidence, ask Vera about the packet, approve or return the decision | Approve through chat, change evidence, bypass policy, issue credit without a valid packet |
| Vera orchestrator | Sequence workflow steps, create tasks, hand off work, summarize current state | Make human decisions, change source records, override policy, authorize money |
| Finance specialist | Read only permitted records; produce typed findings, claims, drafts, recommendations, and evidence links | Approve, release, issue credit, alter source records, close cases |
| Policy Controller | Evaluate deterministic rules and block/allow transitions | Be overridden by model text or user conversation |
| Release/credit executor | Execute an already-approved simulated action exactly once | Choose a destination, invent authority, execute without a current approval |

---

## 4. Canonical case fixture

The seed case must be internally consistent and support both a successful demo and adversarial branches.

| Record | Value |
|---|---|
| Case | `CHG-1042` |
| Cardholder | Priya Shah |
| Finance owner | Sam Rivera |
| Reviewer | Dana Okafor |
| Merchant | Northstar Equipment |
| Charge | `$2,840.00` |
| Card | ending `4418` |
| Posted | Nov 8, 2026 |
| Purchase order | `PO-219` · one unit approved for `$2,400.00` |
| Delivery record | `DLV-882` · two units received |
| Initial report | `REP-1042` · cardholder says the charge is not recognized |
| Follow-up request | `MSG-2201` |
| Later response | `MSG-2251` · cardholder explains the second unit |
| Related charge | `CHG-1051` · `$1,200.00` · separate review |
| Related cleared charge | `CHG-1048` · `$620.00` |
| Callback | `CALL-1042` |
| Decision packet | `PKT-1042` |
| Provisional credit | `CREDIT-1042` |
| Dispute packet | `DSP-1042` |
| Controls recommendation | `CTL-1042` |

The initial report and later response are separate records. If their meanings conflict, the case must create a structured conflict finding rather than silently replacing the initial report.

Related charges are linked by a full synthetic transaction identity and source evidence, never by matching suffixes alone. A decision on `CHG-1042` never approves `CHG-1051`.

---

## 5. End-to-end user journeys

### 5.1 Successful demo

1. A cardholder submits a suspicious-charge report.
2. Vera creates `CHG-1042`, records the report as a claim, and assigns Sam Rivera.
3. Charge Investigator compares the transaction, purchase order, delivery record, and related charges.
4. Vera shows the amount, current state, discrepancy, and next action.
5. Cardholder Follow-up drafts a focused request for the missing receipt/business-purpose detail.
6. Sam reviews and explicitly sends the request.
7. The cardholder responds in the Cardholder view and may attach a sample file.
8. Receipt and Document Reviewer classifies the response and identifies remaining gaps or conflicts.
9. Sam reviews the proposed callback question and explicitly authorizes a simulated callback.
10. Live Verification Agent records a structured callback result.
11. Policy Controller evaluates current evidence.
12. Decision Packet Preparer creates `PKT-1042`.
13. Dana reviews the packet and explicitly approves or returns it.
14. If eligible and approved, Sam explicitly issues simulated provisional credit.
15. Dispute Packet Preparer creates `DSP-1042` when appropriate.
16. Prevention Planner recommends card controls; the permitted analyst/admin action applies them.
17. Vera sends a concise final communication.
18. The case moves to monitoring or closed with a durable decision record.

### 5.2 Failure and recovery journeys

Each branch must be reachable from the UI and must have a named owner, blocker, next action, and recovery action.

- **No cardholder response:** wait → reminder/reassign → hold or continue when response arrives.
- **Incomplete response:** preserve response → draft focused follow-up → send only after analyst action.
- **Conflicting response:** create conflict finding → block affected decision → request clarification.
- **Unanswered callback:** record structured no-answer result → offer retry or hold; do not silently pass.
- **Reviewer return:** preserve original packet and note → create follow-up task → resubmit as a new packet version.
- **Material evidence change after approval:** preserve approval as stale → reopen affected checks → require fresh policy evaluation and approval.
- **Duplicate action:** return original idempotent result; do not create duplicate message, credit, control, or closure.
- **Uncertain adapter result:** look up idempotency key before retrying; show “checking result,” never false success.
- **Closed-case action:** reject command and explain that the case must be reopened through an authorized workflow.

---

## 6. Canonical case state

The backend owns state. The UI renders state; it does not infer state from messages.

```text
reported
→ investigating
→ waiting_on_cardholder
→ response_received
→ evidence_review
→ callback_pending
→ callback_completed
→ decision_pending
→ policy_blocked | credit_eligible
→ reviewer_pending
→ credit_approved
→ credit_issued
→ dispute_prepared
→ remediation_pending
→ monitoring
→ closed
```

Any state may enter `held` with a reason and next owner. A held case can resume without erasing the failed result.

Every transition stores:

- prior state
- next state
- actor and role
- reason
- case version
- workflow version
- policy version
- evidence snapshot hash
- event ID
- timestamp

### 6.1 State/action contract

The API returns `available_actions` for the current role and state. Each action includes:

- command name
- label
- required role
- prerequisites
- blocking reason when unavailable
- expected resulting state

The frontend must never show an action merely because a component exists.

---

## 7. Evidence contract

### 7.1 Evidence classes

- Source record: transaction, receipt, purchase order, delivery record, message.
- Claim: statement from cardholder, merchant, or user.
- Finding: typed interpretation tied to source records.
- Check: structured verification result.
- Decision: human approval/return bound to a snapshot.
- Recommendation: proposed remediation or follow-up.

### 7.2 Evidence statuses

- Supporting
- Missing
- Conflicting
- Superseded
- Pending review
- Not relevant

### 7.3 Evidence requirements

Every evidence item has:

- stable ID
- case ID
- record type
- source
- source timestamp
- content or structured fields
- uploader/actor
- version
- current/superseded status
- provenance links
- status explanation

Attachments never auto-verify a claim. A model may extract or classify content, but a finding must cite actual source fields/excerpts and remain subject to policy and human review.

### 7.4 Material changes

Material changes include transaction amount, merchant, card, cardholder identity, relevant purchase quantity, receipt version, verification target, decision packet inputs, and any fact used by a policy rule.

On a material change:

1. append the new evidence version;
2. compute affected checks;
3. mark only affected checks and approvals stale;
4. preserve the original approval and evidence;
5. reopen required work;
6. block money-affecting actions until current evidence passes.

---

## 8. AI, specialists, and deterministic controls

### 8.1 AI may

- retrieve permitted records through tools;
- compare fields and documents;
- identify candidate relationships;
- draft concise questions and communications;
- summarize evidence with citations;
- propose findings, next steps, and remediation;
- classify a response as complete, incomplete, or conflicting;
- answer role-scoped questions about current evidence.

### 8.2 AI may not

- create unsupported facts;
- accuse a person or merchant of fraud without evidence and human decision;
- change source records;
- alter contact/card/merchant details from conversation text;
- satisfy a policy rule through prose;
- approve, issue credit, release money, apply controls, or close a case;
- call or send external communication without the configured human checkpoint;
- access records outside its declared scope.

### 8.3 Specialist contract

Every specialist definition declares:

- name and purpose;
- permitted input records;
- permitted tools;
- output schema;
- handoff target;
- execution mode;
- required human checkpoint;
- estimated synthetic cost;
- prohibited actions.

Initial specialists:

- Charge Investigator
- Related-Transaction Investigator
- Receipt and Document Reviewer
- Cardholder Follow-up
- Live Verification Agent
- Decision Packet Preparer
- Prevention Planner
- Policy Controller

User-facing UI calls these **Specialists**, not generic agents. The full permission model has one canonical permissions drawer; other surfaces show concise contextual summaries.

---

## 9. Workflow and policy model

### 9.1 Workflow nodes

Supported node types:

- Trigger
- Finance specialist
- Human checkpoint
- Policy check
- Communication
- Verification
- Decision
- Remediation
- Close case

Workflows are composed from approved nodes. Users cannot create arbitrary autonomous agents, arbitrary code, unrestricted tools, money-moving nodes, or policy overrides in this prototype.

### 9.2 Required workflow controls

Every money-affecting workflow must contain:

- Policy Controller
- human decision checkpoint;
- current-evidence recheck;
- decision record;
- idempotency check before execution.

Published versions are immutable. A change creates a new draft/version. A running case remains pinned to the version on which it started.

### 9.3 Policy Controller

The Policy Controller is deterministic application code, not a model. It evaluates:

- authenticated cardholder;
- identified transaction;
- required evidence;
- duplicate/related-case search;
- structured verification results;
- decision-packet completeness;
- reviewer approval;
- current evidence snapshot;
- workflow and policy version;
- case status;
- idempotency.

It returns:

- eligible or blocked;
- rules passed;
- rules failed;
- evidence used;
- blocking reason;
- policy version;
- evidence snapshot hash;
- evaluation timestamp.

---

## 10. Backend architecture

```text
Next.js / React UI
        ↓
FastAPI API and command gateway
        ↓
Authentication / role checks / Zod or Pydantic validation
        ↓
Workflow orchestrator
        ↓
Bounded specialists → typed finance tools
        ↓
PostgreSQL case, evidence, workflow, decision, and event stores
        ↓
Deterministic Policy Controller
        ↓
Simulated adapters: messaging, telephony, credit, dispute, card control
```

Recommended implementation stack:

- Next.js/React/TypeScript frontend;
- Python/FastAPI backend;
- Pydantic command and record schemas;
- PostgreSQL with SQLAlchemy/SQLModel and Alembic;
- Redis only for leases/background jobs if required;
- LangGraph only for durable orchestration/checkpointing, never authority;
- OpenTelemetry and/or Langfuse for model/tool traces;
- Pytest for backend behavior;
- Playwright for end-to-end role journeys;
- GitHub Actions for CI.

### 10.1 Persistence tables

Minimum durable entities:

- `cases`
- `case_assignments`
- `card_transactions`
- `cardholders`
- `merchants`
- `reports`
- `claims`
- `evidence_records`
- `evidence_versions`
- `findings`
- `attachments`
- `communications`
- `callbacks`
- `decision_packets`
- `policy_evaluations`
- `approvals`
- `provisional_credits`
- `dispute_packets`
- `card_controls`
- `workflow_definitions`
- `workflow_versions`
- `workflow_runs`
- `workflow_steps`
- `specialist_definitions`
- `idempotency_keys`
- `audit_events`

Every write must be attributable to a user, specialist, policy service, or adapter and must retain provenance.

### 10.2 Typed commands

The API should expose commands, not arbitrary mutation endpoints:

- `create_case`
- `start_investigation`
- `link_evidence`
- `record_claim`
- `record_finding`
- `request_cardholder_response`
- `attach_file`
- `review_cardholder_response`
- `request_callback`
- `record_callback`
- `create_decision_packet`
- `evaluate_policy`
- `request_reviewer_approval`
- `approve_decision`
- `return_decision`
- `issue_provisional_credit`
- `prepare_dispute_packet`
- `recommend_card_control`
- `apply_card_control`
- `send_final_message`
- `hold_case`
- `resume_case`
- `reassign_case`
- `close_case`

Each command validates role, case state, workflow step, required evidence, policy result, target record, current version, and idempotency key.

---

## 11. Money and simulated execution

The UI must show money as operational impact, not claimed loss.

Use a compact charge-impact ledger:

```text
Posted charge       $2,840.00
Temporary credit          —
Current exposure    $2,840.00
```

After simulated credit:

```text
Posted charge       $2,840.00
Temporary credit   -$2,840.00
Current exposure          $0.00
```

Every money-affecting screen must include a quiet qualifier such as `Synthetic only · no funds moved`.

Credit requires sufficient evidence, a passing policy evaluation, a current decision packet, reviewer approval, and an idempotency key. Authorization and execution are separate records.

---

## 12. Communications and verification

### 12.1 Communications

Specialists draft. The authorized human sends.

The system must preserve:

- draft
- approver
- sent event
- recipient
- channel
- delivery result
- request ID
- response linkage

Repeated send commands return the original result.

### 12.2 Callback

The Live Verification Agent is optional and analyst-started. The analyst approves the call’s scope and target before the simulated adapter runs.

The callback record stores:

- target contact source;
- approved question set;
- start/end time;
- transcript or structured outcome;
- authentication/identity result when simulated;
- unresolved questions;
- analyst who authorized it;
- specialist recommendation;
- policy effect.

An unanswered or non-confirming callback never satisfies the check. The UI offers retry or hold and preserves prior attempts.

---

## 13. UI information architecture

### 13.1 Global navigation

```text
Vera | Cases | Automations
```

Automations contains:

```text
Workflows | Specialists | Policies
```

The demo role switcher contains Finance analyst, Cardholder, and Reviewer. Switching roles changes visibility and available actions but does not itself submit, approve, or mutate anything.

### 13.2 Cases dashboard

The dashboard must answer:

- how much is under review;
- what needs attention;
- what is due today;
- what is overdue;
- how much temporary credit has been issued.

Primary summary metrics:

- Open exposure
- Due today
- Overdue
- Temporary credits

Waiting-on states belong in table filters. Use one `Work to review` table with Case, Current state, Next action, Owner, Waiting on, and Due. Amount stays visible in each row.

### 13.3 Case workspace

Order:

1. case identity and amount;
2. current state;
3. next action;
4. decision summary;
5. evidence;
6. activity;
7. Vera conversation;
8. technical run details.

Technical workflow version, policy version, evidence snapshot, run ID, and token/cost data belong in a drawer or execution view, not in the main reading path.

### 13.4 Reviewer view

The reviewer can ask Vera about the packet and evidence, but approval and return remain explicit controls. The Decision Packet separates recommendation, supporting evidence, conflicts, missing evidence, related records, policy result, and approval binding.

### 13.5 Cardholder view

Cardholders see a focused task, not internal case architecture:

- charge identity and amount;
- one focused question;
- answer options where appropriate;
- attach file / use sample file;
- optional note;
- deadline;
- send response.

No internal IDs, policies, specialist names, or AI orchestration language.

### 13.6 Workflow checks

Workflow checks use a resizable canvas, trace, and inspector. The canvas fits the workflow at a readable zoom. Selecting a node opens an inspector. Selecting a trace row selects the corresponding node. Technical details are expandable.

---

## 14. Observability and cost visibility

Every workflow run records:

- run ID;
- case ID;
- workflow and policy version;
- specialist and step ID;
- input/output record IDs;
- tool calls;
- duration;
- retries;
- errors;
- state before/after;
- policy effect;
- token usage when applicable;
- estimated synthetic cost;
- human checkpoint status.

The user-facing case activity is concise and grouped. The technical execution trace is inspectable by operators/admins and used by the evaluation suite. Costs are visibility and budgeting data, never policy evidence.

---

## 15. Evaluation suite and CI

Create deterministic fixtures for:

1. recognized charge with receipt;
2. unrecognized charge with missing receipt;
3. cardholder no response;
4. incomplete response;
5. conflicting cardholder statements;
6. contradictory receipt/document;
7. related transaction;
8. callback confirmed;
9. callback unanswered;
10. callback retry;
11. reviewer approval;
12. reviewer return without note;
13. reviewer return with note;
14. material evidence change after approval;
15. amount/merchant change after approval;
16. duplicate credit request;
17. uncertain credit adapter result;
18. repeated communication;
19. unsupported source-record change;
20. closed-case action;
21. policy bypass attempt;
22. workflow version immutability;
23. card control recommendation and approval;
24. final communication and closure.

Each fixture asserts both visible behavior and persisted state:

- case state;
- available actions;
- evidence status;
- findings and claims;
- policy result;
- approval validity;
- event history;
- idempotency result;
- recovery action.

CI runs:

- formatting;
- type checking;
- schema validation;
- unit tests;
- state-transition tests;
- policy tests;
- idempotency tests;
- adapter failure tests;
- API contract tests;
- Playwright analyst journey;
- Playwright cardholder journey;
- Playwright reviewer journey;
- Playwright material-change journey.

The test suite must test actual resulting state, not only response wording.

---

## 16. Acceptance criteria

### Product acceptance

- A presenter can move through analyst, cardholder, and reviewer views without losing the case.
- A viewer can identify the amount, current state, owner, blocker, and next action within two seconds.
- A natural question produces a case-scoped answer with source links.
- The UI distinguishes claims, findings, evidence, policy results, and human decisions.
- A related transaction is visible but cannot be accidentally approved through the primary case.
- A cardholder response visibly updates the same case.
- The reviewer can inspect the packet, ask Vera questions, and approve/return explicitly.
- A changed material fact makes affected checks and approvals stale.
- No repeated action creates duplicate side effects.
- Every failure has a visible recovery action.
- The final simulated credit/dispute/remediation outcome is traceable.

### Backend acceptance

- All consequential commands are typed and role-checked.
- State transitions are persisted and append-only events are emitted.
- Policy gates are deterministic and cannot be bypassed by model output.
- Approval is bound to case, transaction, evidence snapshot, workflow version, and policy version.
- Stale approval cannot authorize credit.
- Simulated execution is idempotent and uncertain-result safe.
- Source records cannot be mutated by specialists.
- Workflow versions and active policies are immutable.
- CI passes the complete evaluation fixture suite.

### Design acceptance

- No repeated guardrail essay appears on every page.
- No disabled chat input looks like a broken feature.
- No raw trace or implementation metadata dominates the main case flow.
- No evidence panel mixes source records with activity and execution logs.
- No icon/status change causes layout shift or clipping.
- Workflow canvas, trace, and inspector are resizable/expandable.
- Specialist characters communicate real work state without becoming decorative noise.
- The interface feels like finance operations software, not an AI demo.

---

## 17. Implementation sequence

### Phase 1 — Contract and foundation

- freeze this spec;
- reconcile current fixtures to `CHG-1042`;
- define Pydantic/domain schemas;
- create PostgreSQL migrations;
- implement role and command validation;
- implement append-only events.

### Phase 2 — Deterministic case engine

- implement state machine;
- implement evidence/versioning;
- implement policy controller;
- implement stale-check invalidation;
- implement idempotency;
- implement simulated adapters.

### Phase 3 — Orchestration and specialists

- implement workflow definitions and version pinning;
- implement typed specialist contracts;
- implement tool gateway;
- implement handoffs and human checkpoints;
- add structured model-backed interpretation where useful.

### Phase 4 — API and UI integration

- expose case/query/command APIs;
- replace prototype-local transitions with API calls;
- render typed `available_actions`;
- connect evidence, activity, decision, and run-detail views.

### Phase 5 — Evaluation and demo hardening

- add all fixtures;
- run Playwright role journeys;
- test failure recovery and changed evidence;
- add CI;
- capture a deterministic demo recording;
- document simulation boundaries and architecture.

Do not start by building every specialist as a separate autonomous model. Start with the deterministic state/evidence/policy backbone, then add narrow model calls behind typed contracts.

---

## 18. Open decisions to resolve before production implementation

These do not block the synthetic hackathon build but must be named rather than silently assumed:

1. Which exact card-control actions are simulated: freeze card, replace card, merchant block, or all three?
2. Whether provisional credit is shown as immediate synthetic ledger credit or as an approved pending action before execution.
3. Whether the callback transcript is retained in full or only as a structured verification record in the first implementation.
4. Whether the model runtime is OpenAI Agents SDK, LangGraph, or a thin internal orchestrator for the demo.
5. Whether Langfuse is used in CI or only for local/demo observability.
6. The exact authentication model if the prototype becomes multi-user.
7. The production retention and redaction policy for cardholder attachments and transcripts.

Until resolved, use explicit synthetic defaults, label them in the environment, and keep the interfaces replaceable.

---

## 19. Verified versus proposed

### Verified in the current prototype or source material

- Synthetic role switching exists or is represented.
- The product has a continuous case concept.
- Evidence/source records, communications, requests, reviewers, and simulated outcomes are represented.
- The frontend now includes Cases, Automations, Workflows, Specialists, Policies, evidence, reviewer, cardholder, workflow checks, and activity surfaces.
- The prototype has already exposed failures involving stale evidence, duplicate actions, callback retries, reviewer returns, confusing evidence grouping, repeated AI-style copy, and non-expandable workflow panels.

### Required product behavior

- Claims must remain distinct from verified findings.
- Material changes stale affected checks and approvals.
- Human checkpoints are required for consequential actions.
- Policy must be deterministic and enforceable.
- Simulated execution must be idempotent.
- Every failure must have a recovery path.

### Proposed implementation

- FastAPI/PostgreSQL/Pydantic architecture.
- LangGraph for durable orchestration only if needed.
- OpenTelemetry/Langfuse for traces and cost visibility.
- Command-oriented API and typed tool gateway.
- The listed schema/table decomposition.

### Simulation boundary

- No real money moves.
- No bank-grade verification occurs.
- No external message or call is sent.
- No real card control is applied.
- No fraud determination is asserted.

This distinction must remain visible in the demo, README, architecture explanation, and final presentation.

