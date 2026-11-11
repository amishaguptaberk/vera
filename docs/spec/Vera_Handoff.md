# Vera — Design-to-Engineering Handoff

**Case:** CHG-1042 · Northstar Equipment · $2,840.00
**Prototype baseline:** Vera prototype canvas, version 34 (`project/Main.dc.html`)
**Contract:** `Vera_ToSpec.md` v1.1 (canonical) · **Acceptance:** `Vera_User_Stories.md`
**Date:** Nov 10, 2026 · **Status:** Ready for implementation planning

---

## 0. How to read this document

| Source | Role in this handoff |
|---|---|
| `Vera_ToSpec.md` | Wins on product behavior, architecture, states, commands and permissions. |
| `Vera_User_Stories.md` | Acceptance tests. Story IDs (`US-x00`) are cited next to each contract. |
| Prototype v34 | Visual and interaction baseline. Its local logic is a reference implementation of the contract, not the production state machine. |

Where the prototype and the spec disagreed, this document records the product decision (D1–D8, resolved Nov 10) inline and in §10.8. Those decisions override ToSpec where they conflict. Nothing here redesigns the product.

**Ground rules for implementation**

1. The backend owns state. The UI renders `CaseView` (see §3.1) and never infers state from chat text, animations or component-local flags (ToSpec §6, US-K01).
2. Every visible action is rendered from `available_actions` returned by the API. If the backend would reject it, it is not rendered as enabled (ToSpec §6.1, product-wide rule 6).
3. Every consequential write is a typed command with role check, state check, policy check, idempotency key and an append-only audit event (ToSpec §10.2).
4. Simulation is honest: one environment indicator in the top bar, plus a quiet "No funds moved" qualifier on money surfaces only (ToSpec §11, US-B01).

**Prototype reference map.** In the prototype source, these functions are the reference for the contracts below:

| Prototype function | Production equivalent |
|---|---|
| `COMMANDS()` + `dispatch()` | Command gateway: role → schema → step → policy → permission → idempotency → transaction → event |
| `vm(d)` | `GET /cases/{id}` → `CaseView` |
| `phaseOf(d)` | `case.state` + `case.step` derivation (server) |
| `ACTS()` | `available_actions` registry (server) |
| `pc(d)` | Policy Controller evaluation |
| `closure(d)` | Closure checklist (server) |
| `execRec()` / `xsList()` | `idempotency_keys` + execution-safety view |
| `answer()` / `INTENTS` | Case-scoped Q&A endpoint (read-only) |
| `gValidate()` / `gSim()` / `gPublish()` | Workflow validation, dry-run and publish services |

---

## 1. Screen inventory

Global shell for every analyst screen: left sidebar (Cases · Automations › Workflows, Specialists, Policies), top bar (page context · `Synthetic environment` · `Viewing as: <role> ▾` · Reset). Cardholder and Reviewer views hide the sidebar and show the Vera wordmark instead.

### 1.1 Cases queue

| Field | Spec |
|---|---|
| Route | `/cases` |
| Role | Finance analyst |
| Purpose | Prioritize work by urgency and exposure (US-B01, US-B02, US-B03) |
| Primary task | Open the case that needs action now |
| Visible data | Page heading `Cases` + `Updated 9:08 AM`. Summary strip: Open exposure, Due today, Overdue, Temporary credit (whole dollars + case counts). Case queue rows: Case ID · merchant, amount · broad state, What's blocking it, Next action, Owner, Due. Recent activity (cross-case). |
| Primary action | Click a live case row (whole row clickable; `Open` button appears on hover/focus only) |
| Secondary actions | Sort: Priority / Amount. Filters: All, Due today, Overdue, Waiting on me, Waiting on cardholder, Waiting on reviewer (with counts). Activity "View details". |
| Empty | `No cases match this filter.` |
| Loading | Skeleton rows on first load only. |
| Error | Inline banner above the queue: `Cases couldn't load. Retry.` Keep last good data visible. |
| Responsive | ≥761px: table. ≤760px: each row becomes a structured block (Case + Due on row 1; blocker; next action; owner as secondary text). Summary strip becomes 2 columns ≤900px. |

> **Decision D1 (resolved).** Use the five-column `Case queue`: Case · What's blocking it · Next action · Owner · Due. The broad state lives in the case subtitle (`$2,840 · Waiting on cardholder`); waiting states stay available as filters (`Waiting on me`, `Waiting on cardholder`, `Waiting on reviewer`). This supersedes ToSpec §13.2's `Work to review` columns.
>
> **Specialist character per row.** The Case cell starts with a 40px tile holding the character of the specialist currently responsible for that case (from `CaseView.current_specialist`). States: working (chartreuse dot + working loop, only during a real run), waiting (amber clock badge, still), idle (still). On row hover or focus the character does one 350ms lean and the tile lifts 2px. Tooltip and `aria-label`: `<Specialist name> · working now | waiting | on this case`. The character is decoration plus status; the row's text carries all the meaning.

### 1.2 CHG-1042 analyst workspace

| Field | Spec |
|---|---|
| Route | `/cases/:caseId` |
| Role | Finance analyst |
| Purpose | Own one investigation from report to closure (Epics C–G) |
| Primary task | Complete the single task in the task card |
| Layout (desktop) | Top bar context `CHG-1042 · Northstar Equipment`. Header: amount, card, posted date, cardholder, `Workflow v3 · Run details` link. Status rail: Current state (status icon) · Next action · Owner · Due. Progress: `Step n of 11 · <step>` + Show steps. **Left column:** task card → charge impact → Activity. **Middle column:** tabs Evidence · Communications · Decision · Run details. **Right:** Vera rail. |
| Visible data | All from `CaseView` (§3.1). |
| Primary action | Exactly one primary (chartreuse) button in the task card, rendered from `available_actions[0]`. |
| Secondary actions | Other `available_actions` for the step (ghost/secondary), demo drawer (synthetic only), record links. |
| Empty | Before investigation: Vera rail shows `Start the investigation. Vera's specialists will post concise updates here.` |
| Loading | Never blank the workspace. Running steps show an inline status in the task card (`Charge Investigator · checking transaction`) and a work entry in the Vera rail. |
| Error | Command rejection shows inline under the actions (`.err`), worded as the blocking reason from the API. Adapter failure shows "Nothing was issued. Safe to retry · one credit per charge." |
| Responsive | ≥1280: three regions (left, middle ≥364px, Vera 360–400px). <1280: Vera becomes a right drawer opened from a `Vera` button in the top bar. ≤899: middle panel stacks below the left column. ≤760: sidebar becomes a drawer behind a menu button. |

### 1.3 Cardholder view

| Field | Spec |
|---|---|
| Route | `/requests/:requestId` (cardholder session) |
| Role | Cardholder |
| Purpose | Answer one focused question about one charge (US-D03, ToSpec §13.5) |
| Primary task | `Confirm this charge` → choose an answer → optional note → attach file → Send |
| Visible data | Merchant, amount, card ending, request message, deadline (`Please respond by today, 4:00 PM`), sent responses. **Never** internal IDs, policies, specialists, traces. |
| Primary action | Send response (disabled until an answer is chosen) |
| Secondary actions | Answer options: `I did` / `Someone else did` / `I'm not sure`. Note. Attach file (validated ≤10 MB). Sample files (demo drawer only). Remove file. |
| Empty / idle | `Nothing is waiting for you right now.` + context line. Closed request: `This request has closed.` |
| Error | File too large: `<name> is over 10 MB.` Submit failure: inline, keep the draft. |
| Responsive | Single column, full width on mobile. |

### 1.4 Reviewer view

| Field | Spec |
|---|---|
| Route | `/cases/:caseId/review` (reviewer session) |
| Role | Finance reviewer **and** card admin (Decision D2: two separate permissions held by Dana in the demo) |
| Purpose | Inspect the current packet and approve or return it (US-F02–F04) |
| Primary task | `Approve a temporary credit of $2,840.00?` (reviewer) · `Approve card controls for ••4418?` then `Apply the approved card controls?` (card admin) |
| Visible data | Packet sections (charge, claim, receipts, related charges, messages, verification, conflicts, policy result, recommendation, gaps), source record chips, charge impact, approval history. Vera rail with a state-generated first message. |
| Primary action | `Approve temporary credit` (reviewer) / `Approve controls` → `Apply approved controls — simulated` (card admin) |
| Secondary actions | `Return to Sam` (note required), control checkboxes, `Decline controls`, open records. |
| Empty | `Nothing is waiting for you right now.` + what happened to the last approval. |
| Stale | Approve disabled; banner `Evidence changed after this packet was sent (delivery record updated). Approval is blocked until Sam refreshes the packet.` |
| Responsive | Same rules as 1.2; no sidebar. |

> **Decision D2 (resolved).** `card_admin` is a separate backend role because card-control approval is a distinct authority. In the demo Dana holds both `reviewer` and `card_admin`; the role menu shows `Reviewer · card admin`. Every command is authorized against one role, and every audit event records the role it was executed under (`Dana Okafor · reviewer` approved SIGN-1; `Dana Okafor · card admin` approved and applied CTL-1042). Holding both never merges them: a `reviewer` grant alone cannot approve or apply controls.

### 1.5 Communications (tab inside the case)

| Field | Spec |
|---|---|
| Route | `/cases/:caseId?tab=comms&item=:id` (selection persisted) |
| Role | Analyst (read + act), Reviewer (read-only, if exposed) |
| Purpose | Keep requests, replies, identity verification and calls in-case (ToSpec §12, user brief) |
| List | One row per item, in conversation order: `Cardholder request · MSG-2201` (status), `Identity verification · one-time code / Ramp app push`, `Verification call · CALL-1042`, `Verification call · proposed`. Each row has a fixed status icon slot. |
| Message detail | To, Sent, Approved by, Status, Reply due; `Original request · show full message`; Response block (ID, time, quote, Attachments, Fact status, Assessment, Open questions); actions; `Message sent once · retrying checks the existing delivery result before sending again`; links: Open in Evidence · Open related decision · Open policy effect · Open activity event. |
| Call detail | Title `Call in progress` / `Verification call complete`; Target, Identity, Authorized by, Attempt n of m, Status; Questions asked; Transcript (rows `Vera · 9:39 AM` + quote); Structured result (Identity, Call answered, Authorization answer, Second-unit answer, Card possession, Unresolved, Result, Confidence, Fact status, Policy effect); Reviewer notes + Save note; Sources chips. |
| Identity detail | Channel, Bound to, Sent · expires, Attempts or Method, Status, History, What this proves, Next. |
| Empty | `No messages or calls yet.` |
| Responsive | Same panel; long values wrap by word; IDs never break mid-ID. |

### 1.6 Evidence (tab)

| Field | Spec |
|---|---|
| Purpose | Source records, findings, claims and gaps (US-C02, C04, C07) |
| Visible data | `Charge vs records` comparison table (Field / Expected or recorded / Charge, differing rows marked). Grouped register: Transaction; Purchase and delivery; Cardholder; Verification and decision. Columns: Record (+ source), Date, Status (Supporting / Missing / Conflicting / Superseded / Pending review / Not relevant) + currency line, Supports. Conflict line on responses: `Conflict remains open` / `Conflict resolved by CALL-1042`. Contact on file row. |
| Record view | In-panel detail: kind, ID + version, source, fields, original document preview, transcript, packet sections, connected records, `← Back` (or `← Back to communications`). |

### 1.7 Decision (tab) and decision packet

| Field | Spec |
|---|---|
| Purpose | Recommendation, policy result, gaps, established facts, credit blocker (US-F01, G01) |
| Visible data | Recommendation; Policy (human label, e.g. `Blocked · waiting for cardholder response`); Open gaps; Established; `Issue provisional credit · <blocking reason>`; `View supporting evidence`; Provisional credit timeline (Eligibility evaluated → Reviewer approval → Credit issued → Credit finalized or reversed); `Open decision packet`. |
| Packet record (PKT-1042) | Sections: Original charge, Cardholder claim, Receipts and documents, Related charges, Cardholder messages, Verification, Evidence conflicts, Policy result, Recommended action, Remaining gaps. Source: preparer · time · snapshot hash · `out of date` when stale. |

### 1.8 Workflow builder

| Field | Spec |
|---|---|
| Route | `/automations/workflows/:workflowId?version=` |
| Role | Operations admin (analyst in prototype) |
| Purpose | Compose and validate versioned workflows from approved nodes (US-H04–H07) |
| Layout | Toolbar (name, version chips, status, undo/redo, Outline, `+ Add step`, `Run workflow checks`, `Publish vN`, ⋯ menu with `Reset panel layout`, Discard draft). Canvas (legend, zoom −/%/+/Fit, minimap, step library overlay). Right inspector (resizable 320–520px, collapsible, closable). Bottom checks panel with draggable divider. |
| Primary action | `Publish vN` (only when validation passes and a dry run on this draft has passed every scenario) |
| States | Active (read-only, editing starts a draft), Draft, Viewing an older version. Error bar for publish blockers. |
| Responsive | <1200: inspector overlays the canvas. ≤760: canvas and checks stack; checks becomes a bottom sheet; splitters hidden. |

### 1.9 Workflow checks (bottom panel)

| Field | Spec |
|---|---|
| Tabs | Validation · passing / n issues; Workflow checks · vN; Compare v3 → v4; Versions |
| Modes | Expanded (default ≈35% of builder height, min 180px; canvas min 360px), Compact (≤200px: per scenario `Passed · name · n steps · run time` + `Open details`), Collapsed (footer row `Workflow checks · v3 · Passed · 25 checks`, click restores previous height). |
| Workflow checks detail | Header result, meta (scenario, workflow, run, result), scenarios table (Scenario, Outcome, Last step, Steps, Run time) | resizable divider | trace table (Step, Action, Result, Records, Policy effect). Selecting a trace row selects its node. |

### 1.10 Specialists

| Field | Spec |
|---|---|
| Route | `/automations/specialists/:specialistId` |
| Purpose | Inventory and contract of bounded specialists (US-H01–H03) |
| Layout | Heading. Compact context row: `Card charge investigation v3 · 7 specialists · 1 required policy control` + `Workflow assigned · no active run` or `Running now · <specialist>` + current action. Left list (character, name, one-line status) + `+ New finance specialist`. Right detail: Purpose, Reads, Tools, Writes, Authority, Handoff, Cannot, Runs, Human checkpoint, Permissions (one drawer: Can configure / Restricted by Vera), Appearance (Customize). |
| Statuses | `Available · Used in 1 workflow`, `Working · …` (only during a real run), `Draft · Not used in a workflow`, `Draft · In workflow draft v4`, `Required control · Always enforced` (Policy Controller, always last). |

### 1.11 New specialist draft flow

| Field | Spec |
|---|---|
| Entry | `+ New finance specialist` (secondary, below the list). Opens a right drawer; page stays on Specialists. |
| Fields | Required: Name, Purpose, Permitted records, Permitted tools (approved library; money/controls/code shown disabled as `· not allowed`), Output record type, Handoff target, Execution mode, Human checkpoint. Optional (collapsed): Trigger condition, Example questions, Specialist character, Synthetic budget estimate. `Restricted by Vera` (collapsed). |
| Save | `Save as draft` disabled until Name (≥3), Purpose (≥10), ≥1 record, output type and handoff are set; status line lists what's missing. `Cancel` discards the draft only. |
| After save | Specialist appears as Draft, detail opens with `Edit draft` · `Add to workflow`. |
| Add to workflow | Inline panel: approved workflow list, copy `Adding this specialist creates a new workflow draft. Existing cases remain on their current version.`, `Create workflow draft` · Cancel. Never edits the active version. |

### 1.12 Policies

| Field | Spec |
|---|---|
| Route | `/automations/policies/:policyId?version=` |
| Purpose | Inspect rules; propose changes through drafts (US-I01, I02) |
| Visible data | Title `Corporate card charge investigation · Policy v1 · Active`, rule groups (Intake, Evidence, Decision and money, Remediation and closure) with Rule / Evidence / Effect / Example, meta (Owner, Effective date, Last changed, Used by, Enforcement), pin line `Used by CHG-1042` or `CHG-1042 stays on v1 · new cases use v2`. |
| Actions | `Create new draft` → editable receipt threshold (0–500) → `Publish v2` / `Discard draft`. |

### 1.13 Run details (tab)

| Field | Spec |
|---|---|
| Purpose | Technical metadata kept out of the main reading path (US-J02, J03; ToSpec §14) |
| Visible data | Workflow version, Policy version, Evidence snapshot, Case version, Run ID, Last policy evaluation, Environment. `Execution safety` (collapsed): per operation Operation, Idempotency key, Request ID, Attempts, Execution status, Result/Reason, Safe to retry, Original execution. Execution trace (newest first): specialist runs, policy evaluations, commands (with gate stages), adapter executions. |

---

## 2. Component contracts

Conventions: **Inputs** are fields of `CaseView` or other API resources (§3). **Emits** are command calls (§3.3) or navigation. **Listens** are server-sent events (§4.3). Every component renders from data, keeps its previous content during refetch, and applies a 180–260 ms local transition only to the element that changed.

### 2.1 Shell

| Component | Inputs | States | Emits | Listens | Loading / failure | Permissions | Responsive |
|---|---|---|---|---|---|---|---|
| `Sidebar` | route, `navCollapsed`, `navWidth` | expanded (220–320px, resizable), collapsed (64px icon rail with tooltips), mobile drawer | navigate; collapse/expand; resize (`Resize navigation` splitter: arrows ±16, Shift ±64, Home/End) | — | static | analyst only | <761 drawer behind menu button |
| `TopBar` | page context, role, unseen flags | — | open Vera drawer (<1280), Reset (demo) | `role.unseen` | static | all | context title ellipsizes |
| `RoleSelector` | current role, roles + descriptions, unseen dots | closed, open (menu), Escape closes | switch role (**no command**; view change only) | `role.unseen` | — | demo only | always in top bar; label hides "Viewing as" ≤760 |
| `StatusSlot` | kind: idle / working / complete / blocked / needs-review / waiting | 20px fixed box, crossfade | — | — | — | — | never shifts layout |

### 2.2 Cases queue

| Component | Inputs | States | Emits | Listens | Loading / failure | Permissions | Responsive |
|---|---|---|---|---|---|---|---|
| `SummaryStrip` | `GET /cases/summary` | — | — | `case.state_changed` (recompute) | skeleton on first load | analyst | 4 → 2 columns ≤900 |
| `QueueTable` | `GET /cases?filter&sort` rows: id, merchant, amount, state_label, blocker, next_action, owner, due, wait, live, specialist (only if working or owns current action) | default, hover (action visible), selected (cobalt left bar + pale blue), example (non-interactive, no pointer) | open case; filter; sort | `case.state_changed` | keep rows during refetch | permitted cases only | table → structured rows ≤760 |

### 2.3 Case workspace

| Component | Inputs | States | Emits | Listens | Loading / failure | Permissions | Responsive |
|---|---|---|---|---|---|---|---|
| `CaseHeader` | amount, card, posted date, cardholder, workflow version | — | open Run details | — | static | analyst/reviewer | wraps by word |
| `StatusRail` | `state_label`, `state_kind`, `next_action`, `owner`, `due` | idle/working/complete/blocked/needs-review/waiting icon | — | `case.state_changed` | never blanks | analyst | 4 cells → 2×2 ≤760 |
| `ProgressSteps` | `step_index`, steps[11] with done/current/skipped | collapsed bar, expanded list | toggle | `case.state_changed` | — | analyst | — |
| `TaskCard` | `task` {title, paras, lines, facts, questions, list, draft, idv, choices, controls, checklist, safe_note, result_note}, `available_actions` | per step (§4.2); `In progress` with run sequence; demo drawer | the step's commands | `case.state_changed`, `run.step_*` | content stays visible; inline run sequence instead of a loader | analyst | full width ≤899 |
| `DraftEditor` | communication draft (to, body) | editable, sending, sent | `update_draft`, `send_communication` | `communication.*` | — | analyst | — |
| `IdentityVerification` (analyst) | idv {status, channel, requested_at, expires_at, attempts_used, method, verified_at} — **never the code** | `Verification requested` → `Awaiting cardholder` → `Identity verified` / `Verification failed` / `Verification expired` / `Verification denied` (+ `Request cancelled`) | `send_verification_request`, `resend_verification_request`, `cancel_verification_request`, switch channel (local), `Open cardholder view` | `verification.*` | quiet progress icon only | analyst; demo drawer `Synthetic demo · acts as the cardholder` with `Cardholder enters the right code` / `…a wrong code` / `Cardholder approves` / `Cardholder denies` / `Let the request expire` | — |
| `CardholderVerification` (cardholder view / Ramp app) | active request, channel, expires_at, attempts_left | SMS: 6-digit input + `Verify`; push: `Approve` / `Deny`; result: `Thanks — you're verified.` / `Verification didn't complete.` | `submit_otp`, `answer_verification_push` | `verification.*` | — | cardholder only | full width |
| `DecisionChoices` | choices[] each = action + why/blocking reason | enabled/blocked/not applicable | `request_reviewer_approval`, `record_decision` | — | — | analyst | — |
| `ControlPlan` | recommended controls with reason, scope, reversibility, permission, evidence | checkbox per control | `propose_card_controls`, `skip_card_controls` (analyst) · `approve_card_controls`, `decline_card_controls`, `apply_card_controls` (card admin) | `controls.*` | — | analyst (send/skip), card admin (approve, decline, apply) | — |
| `ParallelTracks` | dispute status, control status, which track is in focus | two rows (`Dispute packet`, `Card controls`), each with a status slot and status text; the non-focused track shows `Work on this next` when it has an analyst action | set track focus (local UI state) | `dispute.*`, `controls.*` | — | analyst | rows wrap; button drops below |
| `ClosureChecklist` | `closure.items[]` {label, applicable, ok, pending, detail} | — | `close_case` | `case.state_changed` | — | analyst | — |
| `ChargeImpact` | posted, temporary credit, exposure, note | before/after credit, reversed | — | `credit.*` | — | analyst/reviewer | — |
| `CaseTabs` | active tab (persisted), selected record | Evidence, Communications, Decision, Run details, Record view | select tab; open record | — | keep content | role-scoped | tabs scroll horizontally if needed; middle column ≥364px |
| `EvidenceRegister` | `GET /cases/{id}/evidence` | grouped table | open record | `evidence.version_added` | keep rows | analyst/reviewer | — |
| `CommunicationsPanel` | `GET /cases/{id}/communications` (list + selected) | list, message detail, call detail (live/complete), identity detail, proposed call | send/remind/review/start call/notes | `communication.*`, `verification.*`, `callback.*` | transcript appends in place | analyst | — |
| `DecisionPanel` | recommendation, policy, gaps, established, credit blocker, credit timeline | — | open packet, go to Evidence | `policy.evaluated` | — | analyst/reviewer | — |
| `RunDetails` | run metadata, executions, trace | Execution safety collapsed by default | — | `run.*`, `execution.*` | — | analyst/operator | — |
| `ActivityTable` | `GET /cases/{id}/activity` (grouped) | rows: time · actor · action (+ record chip) · result · View details | open communication; open record; expand | `audit.event_appended` (append one row) | — | analyst | 2-column grid in narrow columns |
| `VeraRail` | conversation (role-scoped), chips, state-generated context (reviewer) | messages, work entries (running → complete), action buttons on latest message | `POST /cases/{id}/ask`; message actions = registry actions | `run.step_*`, `conversation.*` | composer disabled only while sending | analyst and reviewer (both can type) | drawer <1280 |

### 2.4 Automations

| Component | Inputs | States | Emits | Listens | Loading / failure | Permissions | Responsive |
|---|---|---|---|---|---|---|---|
| `WorkflowCanvas` | version graph (nodes, edges, positions), validation issues, dry-run highlight | view only (active/older), draft editable | node select, edge select, drag, connect, zoom (preserved across resize) | `workflow.draft_updated` | never re-mount on resize | admin | min height 360 |
| `StepLibrary` | approved node catalog | search, groups, insert into selected edge | `add_workflow_node` | — | list min height 150px | admin | — |
| `NodeInspector` | selected node/edge | open, collapsed (44px), closed; overlay <1200 | update mode, retry limit, add failure path, remove | — | independent scroll | admin; Policy Controller and required controls not removable | width 320–520 |
| `ChecksPanel` | validation[], dry-run results, compare, versions | expanded/compact/collapsed; height persisted per session | `run_workflow_checks`, select scenario/trace row | `workflow.checks_completed` | keep previous results | admin | bottom sheet ≤760 |
| `SpecialistList` / `SpecialistDetail` | specialists, workflow usage, live run | see 1.10 | select; edit (opens workflow node); customize appearance | `run.step_*` | — | admin | — |
| `NewSpecialistDrawer` | approved records/tools/outputs/handoffs | invalid (Save disabled), valid, saving | `create_specialist_draft`, `update_specialist_draft` | — | inline error | admin | full-width drawer ≤480 |
| `AddToWorkflowPanel` | approved workflows | — | `add_specialist_to_workflow` (creates draft) | — | — | admin | — |
| `PolicyView` | active/draft policy | active (read-only), draft (threshold editable) | `create_policy_draft`, `publish_policy_draft`, discard | — | validation error `Threshold must be a number from 0 to 500.` | admin | — |

---

## 3. UI-to-API contract

### 3.1 Read model: `CaseView`

`GET /api/cases/{case_id}` returns everything the case workspace renders, scoped to the caller's role. The frontend never computes these fields itself.

```ts
type CaseView = {
  case_id: "CHG-1042";
  case_version: number;               // increments on every accepted command; sent back as expected_case_version
  state: CaseState;                   // spec enum, §4.1
  step: CaseStep;                     // fine-grained task key, §4.2
  state_label: string;                // "Waiting on cardholder"
  state_kind: "idle" | "working" | "complete" | "blocked" | "review" | "waiting";
  next_action: string;                // "Send reminder or reassign"
  owner: Person; waiting_on: Person | null;
  due: { at: string; label: string; overdue: boolean } | null;
  pins: { workflow_version: number; policy_version: number; evidence_snapshot: string };
  transaction: { id; merchant; amount_cents; currency; card_last4; posted_at };
  cardholder: { id; name; department; contact_on_file: { phone_masked; email; verified_at } };
  task: TaskView;                     // title, paragraphs, facts, questions, draft, idv, choices, checklist, notes
  available_actions: ActionView[];    // ordered; [0] is the primary action
  blocked_actions: { command; label; reason }[];
  recovery_actions: string[];         // command names
  policy: PolicyResult;               // §7.4
  credit:   { status: "not_eligible"|"eligible"|"awaiting_approval"|"approved"|"issued"|"checking"|"finalized"|"reversed"; label; why; credit_id?; issued_at? };
  dispute:  { status: "not_prepared"|"prepared"|"ready_for_review"|"ready_to_submit"|"submitted"|"failed"|"accepted"|"denied"; label; applicable };
  controls: { status: "not_recommended"|"recommended"|"awaiting_approval"|"approved"|"applied"|"declined"; label; not_needed: boolean };
  identity_verification: IdvView | null;
  closure: { items: ClosureItem[]; can_close: boolean; will_monitor: boolean };
  recommendation: string;
  gaps: { text; record_id | null }[];
  established: { text; record_id }[];
  conflicts: { text; status: "open"|"resolved"|"accepted_unresolved"; label; resolved_by?; record_id }[];
  charge_impact: { posted_cents; credit_cents; exposure_cents; note };
};

type ActionView = {
  command: string;                    // "issue_provisional_credit"
  label: string;                      // "Issue temporary credit — simulated"
  role: Role;
  style: "primary" | "secondary" | "dark" | "ghost";
  enabled: boolean; blocked_reason?: string;
  expected_state: CaseState; expected_step: CaseStep;
  safe_note?: string;                 // "Safe to retry · one credit per charge"
  confirm?: string;                   // optional confirm copy
};
```

### 3.2 Command envelope

All writes: `POST /api/cases/{case_id}/commands/{command}`

```json
// request
{
  "idempotency_key": "credit:CHG-1042",
  "expected_case_version": 41,
  "payload": { }
}
// 200 response
{
  "status": "recorded" | "replayed",       // replayed = idempotent no-op, original result returned
  "result": { },                           // command-specific
  "event_ids": ["EVT-57"],
  "case": { /* CaseView */ }
}
```

| HTTP | Code | Meaning | UI behavior |
|---|---|---|---|
| 403 | `role_forbidden` | Role can't run this command | Never shown if UI renders from `available_actions`; show reason inline |
| 409 | `stale_case_version` | `expected_case_version` is old | Refetch `CaseView`, re-render, do **not** auto-retry consequential commands (US-J06) |
| 409 | `invalid_step` | Command not allowed in current step | Show `blocked_reason` |
| 409 | `case_closed` | Case closed / monitoring | `The case is closed. No further actions can run.` |
| 422 | `schema_invalid` | Payload invalid | Field-level message |
| 422 | `policy_blocked` | Policy Controller blocked | Show failed rules from `policy` |
| 502 | `adapter_failed_before_effect` | Adapter failed, nothing happened | `Nothing was issued. Safe to retry.` |
| 504 | `adapter_uncertain` | Response lost after dispatch | Case enters `checking`; show `Checking the existing result`; only `lookup_execution_result` offered |

Gate order (matches the prototype pipeline, shown in Run details as stages): **Role → Schema → Step → Policy → Permission → Idempotency → Transaction → Event**. The idempotency check runs before the step check so a repeat returns the original result instead of a step error.

Read endpoints:

| Endpoint | Returns |
|---|---|
| `GET /api/cases?filter=&sort=` | queue rows |
| `GET /api/cases/summary` | four summary metrics |
| `GET /api/cases/{id}` | `CaseView` |
| `GET /api/cases/{id}/evidence` · `/evidence/{record_id}` | register, record detail (versions, provenance) |
| `GET /api/cases/{id}/communications` · `/communications/{item_id}` | thread list, message/call/identity detail |
| `GET /api/cases/{id}/decision-packet?version=` | packet sections + binding |
| `GET /api/cases/{id}/activity` | grouped audit events |
| `GET /api/cases/{id}/runs` · `/executions` | trace, execution-safety rows |
| `GET /api/cases/{id}/conversation?role=` | role-scoped chat |
| `POST /api/cases/{id}/ask` | read-only answer (§3.4) |
| `GET /api/cases/{id}/stream` | SSE events (§4.3) |
| `GET /api/requests/{request_id}` | cardholder task view (no internal IDs) |
| `GET /api/workflows/{id}` · `/versions/{v}` · `/drafts/current` · `/validation` · `/checks` | builder data |
| `GET /api/specialists` · `/{id}` | inventory + contract + usage |
| `GET /api/policies/{id}` · `/versions/{v}` | rules + meta |

### 3.3 Command catalog

`Key` is the idempotency key template. `Roles`: A analyst · C cardholder · R reviewer · K card admin · S specialist/orchestrator · P Policy Controller. "Sim" = goes through a simulated adapter and gets an execution record.

#### Intake and investigation

| UI action | Command | Endpoint | Payload → Result | Roles | Prerequisites | Resulting state/step | Activity event | Key | Errors |
|---|---|---|---|---|---|---|---|---|---|
| Report a charge (cardholder app) | `create_case` | `POST /api/reports` | `{transaction_id, statement, reason, card_in_possession, attachments[]}` → `{report_id, case_id}` | C (authenticated) | authenticated profile (US-A02); transaction identified | `reported` / `intake` | `report.received` "Priya Shah reported a charge she doesn't recognize" | `report:{transaction_id}:{client_nonce}` | duplicate → links to existing case (US-A04) |
| Simulate duplicate report (demo) | `link_report` | `.../commands/link_report` | `{report_id}` → `{linked_to}` | A, C | case open | unchanged | `report.linked` "Second report REP-1047 linked · no new case" | `report:{report_id}` | already linked → replay |
| Open case | — (navigation) + `case.opened` audit | `POST .../commands/open_case` | — | A | — | `investigating`? **no state change** | `case.opened` | `open:{case_id}:{user}` | — |
| Start investigation | `start_investigation` | `.../start_investigation` | `{}` → `{run_id, workflow_version}` | A | step `intake`; transaction bound | `investigating` / `working` → `draft` when run completes | `investigation.started`, then per specialist `specialist.completed` (e.g. "Matched CHG-1042 to PO-219 and DLV-882") | `inv:{case_id}` | run already exists → replay |
| Review response | `review_cardholder_response` | `.../review_cardholder_response` | `{response_id}` → `{classification: complete|incomplete|conflicting, findings[], conflict?}` | A (S executes) | step `response`; response unreviewed | `evidence_review` / `idv` (conflict) or `decision_pending` / `packet` | `evidence.reassessed`; `conflict.opened` | `review:{response_id}` | — |

#### Communications

| UI action | Command | Endpoint | Payload → Result | Roles | Prerequisites | Resulting state/step | Activity event | Key | Errors |
|---|---|---|---|---|---|---|---|---|---|
| Edit draft | `update_communication_draft` | `.../update_communication_draft` | `{communication_id, body}` → `{draft_version}` | A | status `drafted` | unchanged | none (draft versions stored) | `draft:{id}:{draft_version}` | sent → `invalid_step` |
| **Approve and send** (request, follow-up, final) | `send_communication` (spec: `request_cardholder_response` / `send_final_message`) | `.../send_communication` | `{communication_id, body, channel:"email", subject}` → `{status:"delivered", sent_at, request_id}` | A | drafted; content policy (no re-asking reported facts; final message may only state recorded actions: lock/credit/virtual card checks) | request: `waiting_on_cardholder` / `waiting`; final: `remediation_pending` / `close` | `communication.approved`, `communication.sent`, `communication.delivered` (grouped: "Request sent to Priya Shah") | `msg:{communication_id}` | content policy → 422; adapter → 502/504. **Sim** |
| Send reminder | `send_reminder` | `.../send_reminder` | `{communication_id}` → `{reminded_at}` | A | open request, no response | unchanged | `communication.reminder_sent` | `rem:{communication_id}` | no open request |
| Draft follow-up / Send targeted follow-up instead | `draft_follow_up` | `.../draft_follow_up` | `{reason}` → `{communication_id}` | A (S drafts) | one follow-up max per case | `waiting_on_cardholder` / `draft` | `communication.drafted` | `followup:{case_id}` | second follow-up → 409 |
| Cardholder: Send response | `submit_cardholder_response` (spec: `attach_file` + response) | `POST /api/requests/{id}/responses` | `{answer: did|someone_else|not_sure, note, attachments[]}` → `{response_id, attachment_ids[]}` | C | request delivered, not expired | `response_received` / `response` | `response.received` "Reply received from Priya Shah"; `attachment.stored` per file | `reply:{request_id}` | expired → 409; file >10 MB → 422 |
| Let the deadline pass (demo) / deadline job | `mark_deadline_missed` (system) | worker | `{communication_id}` | system | due passed, no reply | `waiting_on_cardholder` / `noresp1` or `noresp2` | `communication.overdue` (recorded once, US-D04) | `overdue:{communication_id}` | — |

#### Identity verification and callback

| UI action | Command | Endpoint | Payload → Result | Roles | Prerequisites | Resulting state/step | Activity event | Key | Errors |
|---|---|---|---|---|---|---|---|---|---|
| **Send verification request** | `send_verification_request` | `.../send_verification_request` | `{channel: "sms"|"app_push"}` → `{verification_id, sent_at, expires_at}` | A | step `idv`; no active request; not locked | `callback_pending` / `idv` (awaiting) | `verification.approved` "Identity verification approved by Sam Rivera"; `verification.sent` | `idv-send:{case_id}:{n}` | active request → 409. **Sim** |
| Resend request | `resend_verification_request` | `.../resend_verification_request` | `{verification_id}` → `{sent_at, expires_at}` | A | active request; cooldown ≥20 s elapsed | unchanged | `verification.resent` | `idv-send:{case_id}:{n+1}` | cooldown → 429 `Wait a moment before resending.` |
| **Enter OTP** (cardholder view / approved app flow) | `submit_otp` | `POST /api/verifications/{id}/submit_otp` | `{code}` → `{result: verified|incorrect|locked, attempts_left}` | **C only** (Decision D8). The analyst never sees or enters the code; analyst API responses omit it. A synthetic-demo control may call this as the cardholder. | active SMS request, not expired | verified → `callback_pending` / `verify`; incorrect → unchanged; 3rd failure → `idv` (locked) | `verification.code_entered`; `verification.code_rejected` ("Code not accepted · 2 attempts remaining") or `verification.verified` | `idv-check:{verification_id}:{attempt}` | expired → transitions to expired, 409 |
| Push approved / declined (cardholder device; demo control) | `answer_verification_push` | `POST /api/verifications/{id}/answer` | `{approve: bool}` | C (device) | active push request | approve → `verify`; decline → `idv` (declined) | `verification.push_approved` / `verification.declined` | `idv-push:{verification_id}` | — |
| Cancel request | `cancel_verification_request` | `.../cancel_verification_request` | `{verification_id}` | A | active request | `idv` (cancelled) | `verification.cancelled` | `idv-cancel:{verification_id}` | **Gap G1:** prototype has no key |
| Request expiry (job / demo) | `expire_verification_request` | worker | `{verification_id}` | system | now > expires_at | `idv` (expired) | `verification.expired` | `idv-expire:{verification_id}` | **Gap G1** |
| **Start verification call** / Retry | `start_callback` (spec: `request_callback`) | `.../start_callback` | `{question_set_id, target:"contact_on_file"}` → `{callback_id, attempt}` | A | `p.verify_needed`; identity verified; attempts < 2 for this response | `callback_pending` / `working` | `callback.approved` "Callback approved by Sam Rivera"; `callback.started` | `call:{response_id}:{attempt}` | identity unverified → 409; 2 attempts → 422. **Sim** |
| (system) Record call result | `record_callback` | worker → `.../record_callback` | `{callback_id, answered, authorization_answer, second_unit_answer, card_possession, unresolved[], confidence, transcript[]}` → `{policy_result}` | S (Live Verification Agent) | callback started | confirmed → `decision_pending` / `packet`; not confirmed/no answer → `callback_pending` / `callfail` | `callback.transcript_received`, `callback.result_recorded`, `policy.evaluated` | `call-result:{callback_id}` | transcript missing → result not recorded (state "Transcript unavailable") |
| Save reviewer note on call | `add_callback_note` | `.../add_callback_note` | `{callback_id, note}` | A, R | call complete | unchanged | `callback.note_added` | `call-note:{callback_id}:{hash(note)}` | — |

> Identity verification is a design addition requested after ToSpec v1.1. It fits ToSpec §12.2 ("authentication/identity result when simulated") and stays out of bank-grade scope (§2.2). OTP/push proves control of the approved channel only; it never changes `policy.outcome`.

#### Decision and reviewer

| UI action | Command | Endpoint | Payload → Result | Roles | Prerequisites | Resulting state/step | Activity event | Key | Errors |
|---|---|---|---|---|---|---|---|---|---|
| Prepare decision / Refresh packet | `create_decision_packet` | `.../create_decision_packet` | `{}` → `{packet_id, version, snapshot_hash}` | A (S prepares) | evidence sufficient; no pending approval on current hash | `decision_pending` / `decide` | `packet.prepared` "Decision packet prepared"; on refresh `approval.superseded` | `pkt:{case_id}:{snapshot_hash}` | — |
| Send to Dana (Approve provisional credit) | `request_reviewer_approval` | `.../request_reviewer_approval` | `{rationale≥15 chars}` → `{approval_id}` | A | packet current; `policy.credit_eligible` | `reviewer_pending` / `waitrv` | `decision.recorded`, `approval.requested` | `sign:{snapshot_hash}:{returns_count}` | not eligible → 422 |
| Prepare dispute without credit / Clear / Record violation / Close as unresolved | `record_decision` | `.../record_decision` | `{kind: dispute|clear|violation|unresolved, rationale}` | A | outcome matches kind (policy) | dispute → `credit_issued`-equivalent path (`dispute_prepared` pending); others → `remediation_pending` / `finalprep` | `decision.recorded` | `decide:{case_id}:{kind}` | wrong outcome → 422 |
| Remind reviewer | `remind_reviewer` | `.../remind_reviewer` | `{approval_id | control_plan_id}` | A | pending | unchanged | `approval.reminder_sent` | `rvrem:{id}` | — |
| Reassign to backup reviewer | `reassign_reviewer` | `.../reassign_reviewer` | `{approval_id}` | A | reviewer deadline passed | unchanged (new reviewer, new due) | `approval.reassigned` | `rvreassign:{approval_id}` | before deadline → 409 |
| **Approve decision** | `approve_decision` | `.../approve_decision` | `{approval_id}` → `{approved_at, binding:{case, transaction, snapshot_hash, policy_version, workflow_version}}` | R | pending; `approval.hash == current snapshot` | `credit_approved` / `issue` | `approval.approved` "Temporary credit approved" | `approve:{approval_id}` | stale → 422 `The evidence changed after this packet was prepared.` |
| Return to Sam | `return_decision` | `.../return_decision` | `{approval_id, reason≥5, requested_next_step?, owner?}` | R | pending | `decision_pending` / `returned` | `approval.returned` | `return:{approval_id}` | missing reason → 422. **Gap G2:** US-F04 also requires requested next step + owner |

#### Money, dispute and remediation

| UI action | Command | Endpoint | Payload → Result | Roles | Prerequisites | Resulting state/step | Activity event | Key | Errors |
|---|---|---|---|---|---|---|---|---|---|
| **Issue temporary credit — simulated** | `issue_provisional_credit` | `.../issue_provisional_credit` | `{transaction_id}` → `{credit_id, issued_at, status}` | A (never S) | policy eligible; current approval bound to current snapshot/policy/workflow; current packet | `credit_issued` / `controls` (after Prevention Planner) | `credit.issued` "Temporary credit issued · CREDIT-1042 · simulated · safe to retry" | `credit:{transaction_id}` (persisted **before** adapter call) | 502 failed-before-effect; 504 uncertain → step `credit_check`. **Sim** |
| Look up existing result | `lookup_execution_result` | `.../lookup_execution_result` | `{idempotency_key}` → `{found, result}` | A | step `credit_check` (or any `checking` execution) | `credit_issued` | `credit.confirmed` "CREDIT-1042 issued once · nothing re-sent" | read-only | — |
| Send control plan to Dana | `propose_card_controls` (spec: `recommend_card_control` is the specialist step) | `.../propose_card_controls` | `{controls:[lock, replace, virtual, block, monitor]}` | A | plan `recommended` | `credit_issued` → next dispute step; controls `awaiting_approval` | `controls.requested` | `ctl-req:{sorted controls}` | none selected → 422 |
| No controls needed | `skip_card_controls` | `.../skip_card_controls` | `{reason}` | A | plan `recommended` (not yet sent) | controls `declined` | `controls.declined` | `ctl-decline:{case_id}` | already sent → 409 |
| Decline controls | `decline_card_controls` | `.../decline_card_controls` | `{reason}` | K | `awaiting_approval` | controls `declined` | `controls.declined` | `ctl-decline:{case_id}` | — |
| **Approve controls** | `approve_card_controls` | `.../approve_card_controls` | `{controls[] ⊆ requested}` | K (`card_admin` only; `reviewer` grant is rejected) | awaiting approval | controls `approved`; card admin's next task `Apply the approved card controls?`; analyst stays on `Waiting on card admin to apply controls` | `controls.approved` "Card controls approved · not applied yet" | `ctl-approve:{plan_id}` | not requested → 422 |
| **Apply approved controls — simulated** | `apply_card_controls` | `.../apply_card_controls` | `{plan_id}` → `{applied[], applied_at}` | K only (Decision D7; analyst → 403 `Only the card administrator can apply card controls.`) | controls approved | controls `applied`; analyst's next step resumes (dispute or `finalprep`) | `controls.applied` "Card controls applied · CTL-1042 · simulated · safe to retry" | `ctl-apply:{plan_id}` | before approval → 409 (US-G06). **Sim** |
| **Prepare dispute packet** | `prepare_dispute_packet` | `.../prepare_dispute_packet` | `{}` → `{dispute_id}` | A (S assembles) | decision credit (credit issued) or dispute | `dispute_prepared` / `dsp_open` | `dispute.prepared` | `dsp:{case_id}` | — |
| Open packet | `open_dispute_packet` | `.../open_dispute_packet` | `{dispute_id}` | A | `prepared` | `ready_for_review` | `dispute.opened` | `dsp-open:{dispute_id}` | — |
| Review packet | `review_dispute_packet` | `.../review_dispute_packet` | `{dispute_id}` | A | `ready_for_review` | `ready_to_submit` | `dispute.reviewed` | `dsp-review:{dispute_id}` | — |
| Record submission — simulated / Retry | `submit_dispute` | `.../submit_dispute` | `{dispute_id}` → `{submission_id, submitted_at}` | A | `ready_to_submit` or `failed` | `submitted`; next step is the open control-track step, `waitctl`, or `finalprep` | `dispute.submitted` "Dispute submission recorded · simulated · safe to retry" | `dsp-sub:{dispute_id}` | 502 → dispute `failed`. **Sim** |
| Draft final update | `draft_final_message` | `.../draft_final_message` | `{}` → `{communication_id}` | A (S drafts from recorded state) | closure items 1–4 met | `remediation_pending` / `final` | `communication.drafted` | `final:{case_id}` | — |
| **Close case** / Close case — monitoring active | `close_case` | `.../close_case` | `{}` → `{state: closed|monitoring, owner, due}` | A | closure checklist passes (US-G08) | `monitoring` or `closed` | `case.closed` | `close:{case_id}` | open items → 422 listing them |
| Dispute accepted / denied | `record_dispute_outcome` | `.../record_dispute_outcome` | `{outcome: accepted|denied}` | A (or dispute feed) | `monitoring`; dispute `submitted` | `closed`; credit `finalized` / `reversed` | `dispute.outcome_recorded`, `case.closed` | `outcome:{case_id}` | — |

#### Case management

| UI action | Command | Endpoint | Payload | Roles | Prerequisites | Result | Event | Key | Errors |
|---|---|---|---|---|---|---|---|---|---|
| Hold for more information | `hold_case` | `.../hold_case` | `{reason, next_owner, due}` | A | not held, not closed | `held` | `case.held` | `hold:{case_id}:{case_version}` | **Gap G3:** prototype uses a default reason; US-J05 requires reason + next owner input |
| Resume | `resume_case` | `.../resume_case` | `{}` | A | held | prior step recomputed; failures kept | `case.resumed` | `resume:{case_id}:{case_version}` | — |
| Reassign / Reassign to card program | `reassign_case` | `.../reassign_case` | `{to, reason}` | A | — | `held` with new owner | `case.reassigned` | `reassign:{case_id}:{case_version}` | — |

#### Automations

| UI action | Command | Endpoint | Payload → Result | Roles | Prerequisites | Result | Event | Key | Errors |
|---|---|---|---|---|---|---|---|---|---|
| Edit active workflow (any canvas edit) | `create_workflow_draft` (implicit) | `POST /api/workflows/{id}/drafts` | `{from_version}` → `{draft_version}` | admin | no open draft | draft vN+1 | `workflow.draft_created` | `wfdraft:{id}:{from_version}` | — |
| Add step / connect / move / remove / set mode / set retry limit / add failure path | `update_workflow_draft` | `PATCH /api/workflows/{id}/drafts/{v}` | JSON-patch ops on nodes/edges | admin | draft open; required controls not removable | draft updated; validation recomputed | `workflow.draft_updated` | `wfpatch:{id}:{v}:{op_seq}` | removing Policy Controller / human checkpoint / recheck / decision record / idempotency gate on money workflow → 422 |
| Run workflow checks | `run_workflow_checks` | `POST /api/workflows/{id}/versions/{v}/checks` | `{scenarios:"all"}` → `{run_id, results[]}` | admin | — | results stored per version | `workflow.checks_completed` | `wfcheck:{id}:{v}:{graph_hash}` | — |
| **Publish workflow draft** | `publish_workflow_version` | `POST /api/workflows/{id}/drafts/{v}/publish` | `{reason}` → `{active_version}` | admin | validation passes; checks run on this exact draft; every scenario reaches close | new active version; running cases stay pinned | `workflow.published` | `wfpub:{id}:{v}` | issues → 422 with list. **Gap G4:** prototype publishes locally, not through the command pipeline |
| Discard draft | `discard_workflow_draft` | `DELETE /api/workflows/{id}/drafts/{v}` | — | admin | draft open | draft removed | `workflow.draft_discarded` | — | — |
| Save as draft (new specialist) | `create_specialist_draft` | `POST /api/specialists` | `{name, purpose, records[], tools[], output_type, handoff, execution_mode, checkpoint, trigger?, examples?, character?, budget?}` → `{specialist_id, status:"draft"}` | admin | name ≥3, purpose ≥10, records ≥1, output, handoff; tools ⊆ approved library | `Draft · Not used in a workflow` | `specialist.draft_created` | `spec:{client_nonce}` | prohibited tool → 422 |
| Edit draft | `update_specialist_draft` | `PATCH /api/specialists/{id}` | same fields | admin | status draft | — | `specialist.draft_updated` | `spec:{id}:{rev}` | — |
| **Add specialist to workflow** | `add_specialist_to_workflow` | `POST /api/workflows/{id}/drafts` + patch | `{specialist_id, from_version}` → `{draft_version, node_id}` | admin | specialist draft valid | workflow draft (never active) | `workflow.draft_created` / `workflow.draft_updated` | `spec-wf:{specialist_id}:{workflow_id}:{from_version}` | — |
| Create policy draft | `create_policy_draft` | `POST /api/policies/{id}/drafts` | `{from_version}` | admin | — | draft | `policy.draft_created` | `poldraft:{id}:{from_version}` | — |
| Publish policy draft | `publish_policy_version` | `POST /api/policies/{id}/drafts/{v}/publish` | `{receipt_threshold 0–500, reason}` | admin | validated | new active policy; cases stay pinned | `policy.published` | `polpub:{id}:{v}` | out of range → 422 |

### 3.4 Case-scoped Q&A (`POST /api/cases/{id}/ask`)

Read-only. Never executes a command. Request `{text, role, last_intent?}` → `{intent, title, paragraphs[], cites[], actions[] /* navigation or registry commands to render as buttons, never auto-run */, signature}`.

- Intents (ordered, explicit before generic): `approve`, `submit_dispute`, `issue_credit`, `close_now`, `override`, `change_evidence`, `contact_change` (incl. any phone number in text), `start_call_chat`, `claim_verified`, `contact`, `phone`, `can_close`, `credit_eligible`, `credit_blocked`, `stale`, `dispute_status`, `credit_status`, `missing`, `unresolved`, `supports`, `changed`, `lock`, `controls`, `related`, `open_decision`, `why_call`, `amount`, `next`, `owner`, `policy`; fragment `why?` resolves from `last_intent`; otherwise `unknown` with a short fallback (never the generic case summary).
- Required canned answers (tests):
  - Reviewer "approve it" → `Approval must be recorded with the reviewer action below, not through chat.` + `[Open decision]`.
  - "issue the credit" → `Credit has already been issued for this case.` or `The packet is eligible for credit, but reviewer approval is still required.` per state.
  - "Who do I call?" → `The approved contact is Priya Shah · (415) 555-0182.` + `Use the contact currently on file, not a number from an unverified message.` + cite `PRF-4418`.
  - "Phone on file" → `The phone on file is (415) 555-0182 for Priya Shah.`
  - "Can we close?" → `Not yet.` + only the open closure items + `[Open closure checklist]`.
- Deduplication: if the same intent returns the same `signature`, the server replaces the earlier pair instead of appending (US-F02 "same question does not create duplicate activity"). Q&A never writes `audit_events`.

---

## 4. State and event map

### 4.1 Two levels of state

ToSpec §6 defines the case **state** enum. The prototype needed a finer **step** to decide exactly one task, one primary action and one label. Persist both; `step` is derived by the server from case data and stored with every transition so the UI never recomputes it.

| `state` (ToSpec §6) | `step` values (prototype `phaseOf`) | `state_label` shown in the rail |
|---|---|---|
| `reported` | `intake` (not opened) | New report |
| `investigating` | `intake` (opened), `working` (investigation run), `draft` | Needs investigation · In progress · Needs review |
| `waiting_on_cardholder` | `waiting`, `noresp1`, `noresp2` | Waiting on cardholder · Response overdue |
| `response_received` | `response` | Needs review |
| `evidence_review` | `working` (review run) | In progress · Receipt and Document Reviewer |
| `callback_pending` | `idv`, `verify`, `callfail`, `working` (call) | Identity check needed · Awaiting cardholder verification · Identity not verified · Evidence conflict |
| `callback_completed` | transient → packet | — |
| `decision_pending` | `packet`, `decide`, `returned`, `stale` | Ready for decision · Returned by reviewer · Approval out of date |
| `policy_blocked` / `credit_eligible` | carried on `policy.outcome` while in `decision_pending` | (policy row in Decision tab) |
| `reviewer_pending` | `waitrv` | Waiting on reviewer |
| `credit_approved` | `issue`, `credit_check` | Approved · credit ready · Checking credit result |
| `credit_issued` | `controls`, `ctl_prep` | Card controls recommended · Preparing card controls |
| `dispute_prepared` | `dsp_prepare`, `dsp_open`, `dsp_review`, `dsp_submit`, `dsp_failed` | Dispute not prepared · … · Dispute submission failed |
| `remediation_pending` | `waitctl`, `ctl_apply`, `finalprep`, `final`, `close` | Waiting on card admin · Controls approved · Final update needed · Ready to close |
| `monitoring` | `monitoring` | Monitoring |
| `closed` | `closed` | Closed |
| `held` (from any) | `onhold` | On hold |

> **Decision D3 (resolved).** After provisional credit (or a dispute-without-credit decision) two tracks open **in parallel**: the dispute track (`prepare → open → review → submit`) and the control track (Prevention Planner recommends → analyst sends plan → card admin approves → card admin applies, or analyst skips / card admin declines). Neither track blocks the other. The analyst's task card shows the focused track's step plus a `Running in parallel · close waits for both` strip; `Work on this next` switches focus. Default focus: control plan if it is ready to send (it starts the card admin's clock), otherwise the dispute. The final communication and closure wait for the required dispute, control and communication outcomes. In the workflow definition, `credit` fans out to `dispute` and `prevent`, and both join before `final`. ToSpec's single `remediation_pending` state becomes a pair of sub-statuses (`dispute.status`, `controls.status`).

`state_kind` drives the status icon: `working` (spinner, only during a real run), `blocked` (red policy mark), `waiting` (amber clock), `review` (cobalt dot), `complete` (green check), `idle` (neutral outline).

### 4.2 Transition table

Every row persists: prior/next state and step, actor + role, reason, case version, workflow version, policy version, evidence snapshot hash, event ID, timestamp (ToSpec §6).

| # | From (state / step) | Command | Actor | Prerequisites | To (state / step) | Event(s) | Visible UI change | Recovery |
|---|---|---|---|---|---|---|---|---|
| 1 | — | `create_case` | Cardholder | authenticated, transaction identified | reported / intake | `report.received` | New row in queue (`New report`) | duplicate → `link_report` |
| 2 | reported / intake | `start_investigation` | Analyst | transaction bound | investigating / working | `investigation.started` | Task card shows run sequence `Assembling review team` → specialists with status icons; Vera rail work entries | run is idempotent; resume on reload |
| 3 | investigating / working | (run completes) | Orchestrator | docs specialist finished | investigating / draft | `specialist.completed` ×3, `evidence.linked`, `policy.evaluated`, `communication.drafted` | Task `Ask Priya for the missing receipt and the amount difference.` with editable draft | edit/discard draft |
| 4 | investigating / draft | `send_communication` | Analyst | content policy passes | waiting_on_cardholder / waiting | `communication.sent/delivered` | Task `Request sent to Priya`; rail `Waiting on cardholder`; comms `Delivered · reply due …` | resend returns original |
| 5 | waiting / waiting | deadline job | System | due passed | waiting / noresp1 (or noresp2 after follow-up) | `communication.overdue` | `Cardholder response overdue`; Vera offers `Draft follow-up` · `Hold` | reminder, follow-up, reassign, hold |
| 6 | waiting / noresp2 | `record_decision{unresolved}` | Analyst | follow-up overdue | remediation_pending / finalprep | `decision.recorded` | `Send Priya a final update.` | — |
| 7 | waiting / * | `submit_cardholder_response` | Cardholder | request open | response_received / response | `response.received`, `attachment.stored` | Analyst lands on Communications with the reply under the original request (`New`); task `Priya replied.` | — |
| 8 | response_received / response | `review_cardholder_response` | Analyst → Reviewer specialist | — | callback_pending / idv (conflict or incomplete) · decision_pending / packet (supported) | `evidence.reassessed`, `conflict.opened`, `policy.evaluated` | Comms: `Claim · reviewed`, Assessment, Open questions. Evidence: `Conflict remains open` | — |
| 9 | callback_pending / idv | `send_verification_request` | Analyst | — | idv (awaiting) | `verification.approved`, `verification.sent` | Same card: `Awaiting cardholder verification`, `Push sent to Priya's Ramp app · Sent 9:42 AM · Expires in 10 minutes`, `Resend request` · `Cancel request` | resend (cooldown), cancel, expire |
| 10 | idv (awaiting) | `submit_otp` ✓ / push approved | Cardholder | code valid / push approved | callback_pending / verify | `verification.verified` | Same card updates: ✓ `Identity verified`, `Verified 9:43 AM · Method: …`, `Ready for verification call` + 2 questions | — |
| 11 | idv (awaiting) | `submit_otp` ✕ | Cardholder | — | idv (awaiting) or idv (locked after 3) | `verification.code_rejected` | Cardholder sees `Code not accepted · 2 attempts remaining`; analyst sees `Awaiting cardholder · Attempts used: 1 of 3`, then `Verification failed` → `Send targeted follow-up instead` · `Reassign` · `Hold` | follow-up/reassign/hold; never closes |
| 12 | idv (awaiting) | expire / decline / cancel | System / Cardholder / Analyst | — | idv (expired / declined / cancelled) | `verification.expired/declined/cancelled` | `Verification expired · Send a new request` / `Verification denied · Use another approved method or hold` | send new request; other method; hold |
| 13 | callback_pending / verify | `start_callback` | Analyst | identity verified; < 2 attempts | callback_pending / working | `callback.approved`, `callback.started` | Task `Call in progress · Using verified phone ending 0182` with live transcript; comms call record live | — |
| 14 | working (call) | `record_callback` confirmed | Live Verification Agent | transcript + structured result | decision_pending / packet → decide | `callback.transcript_received`, `callback.result_recorded`, `policy.evaluated`, `packet.prepared` | Evidence: `Conflict resolved by CALL-1042`; task `Recommended: temporary credit while the dispute is prepared.` | — |
| 15 | working (call) | `record_callback` not confirmed / no answer | Live Verification Agent | — | callback_pending / callfail | same | `Verification failed · credit remains blocked` / `The call wasn't answered.`; actions retry (if < 2), follow-up, hold | retry (new attempt ID), follow-up, reassign, hold — never close |
| 16 | decision_pending / decide | `request_reviewer_approval` | Analyst | eligible, packet current | reviewer_pending / waitrv | `decision.recorded`, `approval.requested` | Task `Decision packet sent for approval`; reviewer sees packet | remind, reassign after deadline |
| 17 | decision_pending / decide | `record_decision{dispute|clear|violation}` | Analyst | outcome matches | dispute path or remediation_pending / finalprep | `decision.recorded` | Next task per path | — |
| 18 | reviewer_pending / waitrv | `approve_decision` | Reviewer | hash current | credit_approved / issue | `approval.approved` | Task `Issue the provisional credit` | — |
| 19 | reviewer_pending / waitrv | `return_decision` | Reviewer | reason | decision_pending / returned | `approval.returned` | `Revise the packet Dana returned` + note | resubmit as new packet version |
| 20 | reviewer_pending or credit_approved | material evidence change (e.g. `DLV-882 v2`) | Source system | — | decision_pending / stale | `evidence.version_added`, `approval.stale`, `policy.evaluated` | `Approval out of date`; reviewer approve disabled; credit blocked | `create_decision_packet` → re-request approval |
| 21 | credit_approved / issue | `issue_provisional_credit` ✓ | Analyst | approval current | credit_issued / working → controls | `credit.issued` | Ledger: `Temporary credit −$2,840.00 · Current exposure $0.00`; note `Credit issued once · safe to retry…` | repeat → replay |
| 22 | credit_approved / issue | `issue_provisional_credit` ✕ before effect | Analyst | — | credit_approved / issue | `execution.failed_before_effect` | `The credit service timed out before confirming. Nothing was issued. Safe to retry · one credit per charge.` | retry |
| 23 | credit_approved / issue | `issue_provisional_credit` uncertain | Analyst | — | credit_approved / credit_check | `execution.uncertain` | `Checking the existing credit result` | `lookup_execution_result` → #21 |
| 24 | credit_issued / controls ∥ dsp_* | `propose_card_controls` / `skip_card_controls` | Analyst | — | controls `awaiting_approval` / `declined`; dispute track unaffected | `controls.requested` / `controls.declined` | Next focused track step; parallel strip updates | — |
| 25 | dispute_prepared / dsp_* | `prepare` → `open` → `review` → `submit_dispute` | Analyst | per status | dsp_open → dsp_review → dsp_submit → (submitted) | `dispute.prepared/opened/reviewed/submitted` | Task, button, chat and activity all use the same dispute status | failed → `dsp_failed` → retry |
| 26 | controls `awaiting_approval` | `approve_card_controls` / `decline_card_controls` | Card admin | requested | controls `approved` / `declined` | `controls.approved` / `controls.declined` | Card admin: `Apply the approved card controls?`; analyst: `Waiting on card admin to apply controls` | — |
| 27 | controls `approved` | `apply_card_controls` | Card admin | approved | controls `applied` → analyst resumes (dispute step or finalprep) | `controls.applied` | `Card controls applied by card admin · simulated · applied once` | repeat → replay; analyst attempt → 403 |
| 28 | finalprep → final | `draft_final_message` → `send_communication` | Analyst | only recorded actions mentioned | remediation_pending / close | `communication.sent` | Closure checklist | — |
| 29 | remediation_pending / close | `close_case` | Analyst | checklist passes | monitoring (dispute pending) / closed | `case.closed` | `Waiting for the dispute outcome.` | — |
| 30 | monitoring | `record_dispute_outcome` | Analyst / feed | dispute submitted | closed | `dispute.outcome_recorded`, `case.closed` | `Credit finalized` / `Credit reversed` | — |
| 31 | any (not closed) | `hold_case` → `resume_case` | Analyst | reason + owner | held → prior step | `case.held`, `case.resumed` | `On hold` card with `Resume` | failures preserved |
| 32 | closed / monitoring | any other command | anyone | — | rejected | none (trace only) | `The case is closed. No further actions can run.` | reopen via authorized workflow (not built) |

### 4.3 Event stream

`GET /api/cases/{id}/stream` (SSE). Each event: `{event_id, type, case_id, case_version, at, actor:{id, role}, record_ids[], summary, detail}`. The client applies the new `case_version` by refetching `CaseView` (or applying a patch) and appends one Activity row. Run progress events (`run.step_started`, `run.step_line`, `run.step_completed`) drive the Vera rail work entries and the live transcript; they never change `state` by themselves.

Closure checklist (server-side, US-G08), each item `{label, applicable, ok, pending, detail}`:

1. Decision recorded
2. Credit status recorded (credit decisions only)
3. Dispute status recorded (credit/dispute decisions only; submitted, accepted or denied)
4. Card-control decision recorded (applied or declined; not applicable for clear/violation/unresolved)
5. Final cardholder communication sent
6. Final outcome recorded — for dispute paths, `pending` is allowed and closing enters `monitoring`

---

## 5. Role and permission matrix

Legend: ✓ allowed · ◐ draft/recommend only · ✕ never · — not applicable. "Sees" is the visibility scope.

| Capability | Cardholder | Finance analyst | Reviewer | Card admin | Specialist | Policy Controller | Vera orchestrator |
|---|---|---|---|---|---|---|---|
| **Sees** | own request: merchant, amount, card, question, deadline, own replies | full case, evidence, comms, decision, activity, run details | packet, evidence, approvals, charge impact, role-scoped chat | control plan + supporting evidence | declared input records only | all inputs to rules | case state, tasks |
| Create report / claim | ✓ | ✓ | ✕ | ✕ | ✕ | ✕ | ✕ |
| Add evidence / attachments | ✓ own | ✓ | ✕ | ✕ | ◐ evidence links | reads | ✕ |
| Edit source records | ✕ | ✕ | ✕ | ✕ (only authorized admin per US matrix) | ✕ | ✕ | ✕ |
| Draft communication | ✕ | ✓ | ✕ | ✕ | ◐ | ✕ | ◐ |
| **Send** communication | ✓ own response | ✓ (explicit) | ✕ | ✕ | ✕ | ✕ | ✕ |
| Send identity verification | ✕ | ✓ | ✕ | ✕ | ✕ | ✕ | ✕ |
| Enter OTP / answer push | ✓ | ✕ (never sees the code; sees status only) | ✕ | ✕ | ✕ | ✕ | ✕ |
| Approve / start callback | ✕ | ✓ | ✕ | ✕ | ◐ recommends | gates | ✕ |
| Record callback result | ✕ | ✕ | ✕ | ✕ | ✓ Live Verification Agent (structured only) | evaluates | ✕ |
| Prepare decision packet | ✕ | ✓ | ✕ | ✕ | ◐ Decision Packet Preparer | validates | sequences |
| **Approve / return** decision | ✕ | ✕ | ✓ | ✕ | ✕ | validates binding | ✕ |
| **Issue** provisional credit | ✕ | ✓ after approval | ✕ (approves prerequisite) | ✕ | ✕ | gates | ✕ |
| Prepare / submit dispute (sim) | ✕ | ✓ | ✕ | ✕ | ◐ assembles | gates | ✕ |
| Recommend card controls | ✕ | — | ✕ | — | ◐ Prevention Planner | — | ✕ |
| Send / skip control plan | ✕ | ✓ | ✕ | ✕ | ✕ | ✕ | ✕ |
| Approve / decline card controls | ✕ | ✕ | ✕ (a reviewer grant alone is rejected) | ✓ | ✕ | gates | ✕ |
| **Apply** card controls | ✕ | ✕ (Decision D7) | ✕ | ✓ after approval | ✕ | gates | ✕ |
| Hold / resume / reassign | ✕ | ✓ | ✕ | ✕ | ✕ | ✕ | ✕ |
| **Close** case | ✕ | ✓ after checklist | ✕ | ✕ | ✕ | validates checklist | ✕ |
| Ask Vera (read-only Q&A) | ✕ | ✓ | ✓ | ✓ | — | — | answers |
| Configure specialists / workflows / policy drafts | ✕ | ✓ admin role | ✕ | ✕ | ✕ | ✕ (required, non-removable) | ✕ |
| Publish workflow / policy | ✕ | ✓ admin role | ✕ | ✕ | ✕ | ✕ | ✕ |
| Override policy | ✕ | ✕ | ✕ | ✕ | ✕ | — | ✕ |
| Move money | ✕ | ✕ | ✕ | ✕ | ✕ | ✕ | ✕ (only the credit executor, once, after approval) |

Specialists inherit these restrictions with no exceptions: cannot move money; issue or reverse credit; approve a decision; release a payment; override the Policy Controller; change source records; close a case; assign a reviewer; use arbitrary tools or code.

---

## 6. Communications contract

One in-case thread. The analyst never leaves the case to see a reply, attachment, identity check or transcript.

| Stage | Record | Fields persisted | Status shown | Next actions | Event |
|---|---|---|---|---|---|
| Request drafted | `communications` (kind request/followup/final) | id, case, kind, to, channel, subject, body, draft_versions[], drafted_by (specialist) | `Drafted · awaiting your approval` | Approve and send, edit, hold | `communication.drafted` |
| Approval | same | approved_by, approved_at | (grouped) | — | `communication.approved` |
| Sent | same + `idempotency_keys` | sent_at, request_id, adapter | `Delivered · reply due …` | Send reminder, hold | `communication.sent` |
| Delivered | same | delivered_at, delivery_result | same | — | `communication.delivered` |
| Overdue | same | overdue_at (once) | `No reply · deadline passed` | Send reminder, reassign, hold | `communication.overdue` |
| Reply | `communications.response` + `claims` | response_id, text, answer option, at, linked request | `Replied · 9:31 AM · not reviewed` + `New` | Review response | `response.received` |
| Attachments | `attachments`, `evidence_versions` | file name, type, size, sha256, uploader, extracted fields (after review) | `Pending review` | — | `attachment.stored` |
| Review | `findings` | classification, conflict, open questions, reviewed_at | `Claim · reviewed by Receipt and Document Reviewer`, Assessment (`Incomplete response · follow-up required` / `Conflicting response · decision blocked pending clarification`) | Draft follow-up, Start verification call | `evidence.reassessed` |
| Verification request | `identity_verifications` | channel, bound_to (case + profile), sent_at, expires_at (10 min), attempts (max 3), cooldown_until, status history | Analyst: `Awaiting cardholder` (the code is never shown) | Resend, Cancel, Open cardholder view | `verification.sent` |
| OTP / push result | same | entered attempts, verified_at, method, declined_at, expired_at | Analyst: `Identity verified · 9:43 AM` / `Verification failed` / `Verification expired` / `Verification denied`; cardholder additionally sees `Code not accepted · n attempts remaining` | Start call / new request / other method / follow-up | `verification.*` |
| Callback approval | `callbacks` | authorized_by, authorized_at, target source (`contact on file`), approved question set, attempt | `Proposed · waiting for your approval` → live | Start verification call | `callback.approved` |
| Transcript | `callbacks.transcript[]` | speaker, text, at — append-only, retained after completion | `Call in progress` → `Verification call complete` | — | `callback.transcript_received` |
| Structured result | `callbacks.result` | identity, answered, authorization_answer, second_unit_answer, card_possession, unresolved[], confidence, result, reviewer_notes | e.g. `Identity: Verified · Authorization: Did not authorize · Second unit: Confirmed · Result: Evidence supports unauthorized-charge review` | Save note | `callback.result_recorded` |
| Policy effect | `policy_evaluations` | rules passed/failed, result, snapshot, version | `Policy effect: Ready for decision` / `Verification failed · credit remains blocked` | Open policy effect | `policy.evaluated` |

Rules:

- The initial report (`REP-1042`) and every later response are separate immutable records. Conflicts are `findings` with status open / resolved (with `resolved_by`) / accepted as unresolved (US-A05, C05).
- A reply never auto-verifies anything; opening or reviewing it never changes `policy.outcome` by itself.
- Phone numbers or contacts supplied in chat or a message are recorded as claims and never used as a call target (ToSpec §8.2).
- No successful verification state is shown unless a structured result exists. Missing transcript → `Transcript unavailable. A structured result can't be recorded until the call is reviewed.`
- Repeated send returns the original delivery result (`msg:{communication_id}`).
- Selection (`tab`, `item`) is part of the URL so refresh returns to the same record (US-J06).

---

## 7. Workflow and specialist contract

### 7.1 Versioning

| Rule | Behavior |
|---|---|
| Published versions are immutable | Any edit on an active version first creates `draft vN+1` (`create_workflow_draft`). |
| One open draft per workflow | Further edits patch the same draft; "Discard draft" deletes it. |
| Case pinning | A case stores `workflow_version` and `policy_version` at `start_investigation`; publishing never changes running cases. UI copy: `Used by CHG-1042` or `CHG-1042 stays on v3 · new cases use v4`. |
| Publish gate | (1) validation passes, (2) `run_workflow_checks` ran on this exact draft graph, (3) every scenario reached close/monitoring/hold-with-owner. |
| Compare | Draft vs active: added/removed/changed steps, added/removed paths, per-scenario path diff; `Only layout changed. Behavior is identical.` |
| Versions | Version list with publish log entries (`Published v4. CHG-1042 remains pinned to v3.`). |

### 7.2 Node types

ToSpec §9.1 lists Trigger, Finance specialist, Human checkpoint, Policy check, Communication, Verification, Decision, Remediation, Close case. The prototype uses five render types:

| Prototype type | ToSpec node types it covers | Example nodes in v3 |
|---|---|---|
| `trigger` | Trigger | Report received |
| `agent` | Finance specialist, Communication (drafting), Verification | Charge Investigator, Related-Transaction Investigator, Evidence assessment, Live verification, Cardholder follow-up, Prepare recommendation, Prevention Planner, Final communication |
| `policy` | Policy check | Policy Controller (pc1 evidence sufficiency, pc2 credit eligibility), Retry within limits |
| `checkpoint` | Human checkpoint, Decision, Close case | Analyst decision, Reviewer approval, Analyst handoff, Admin approval, Close or monitor |
| `action` | Remediation, money/dispute execution | Provisional credit, Dispute packet |

> **Decision D4 (resolved).** Every node stores its canonical behavior type in `kind` (`trigger`, `finance_specialist`, `human_checkpoint`, `policy_check`, `communication`, `verification`, `decision`, `remediation`, `close_case`). The builder maps `kind` to one of the five visual categories above; the inspector shows `Node type: Verification · shown as finance specialist`. Validation, execution and LangGraph node construction read `kind`, never the visual category. Prototype mapping: `follow`, `final` → communication; `verify` → verification; `decide` → decision; `close` → close_case; `review`, `admin`, `handoff`, `cp` → human_checkpoint; `credit`, `dispute` → remediation; `pc1`, `pc2`, `retry` → policy_check; other agents → finance_specialist.

Each node's declared outcomes (edges must cover them): `pc1`: sufficient / missing evidence / contradictory · `follow`: response / no answer · `verify`: verified / contradicted / no answer · `decide`: unauthorized / authorized · `pc2`: eligible / not eligible · `review`: approved / rejected · `credit`: issued / timeout · `dispute`: submitted · `final`: delivered / send failed · `handoff`: close unresolved · `retry`: escalation. Failure outcomes: no answer, timeout, send failed, failed, escalation.

### 7.3 Validation rules (run on every edit, save and publish — US-H05)

Each issue names the node(s)/edge(s) and the rule:

1. Exactly one trigger (`Starts at Report received`).
2. Every step reachable from the trigger.
3. Every path can reach Close or monitor.
4. No dead ends (every non-close node has an outgoing path).
5. Every declared decision outcome has a path.
6. Every analyst-started step and every action has a failure path.
7. Each outcome leads to exactly one step (no ambiguous edges).
8. Every back edge (loop) has a retry limit (`max`).
9. Money-affecting nodes must be preceded by: Policy Controller, human decision checkpoint, reviewer approval, current-evidence recheck, decision record, idempotency gate (ToSpec §9.2, US-H04). Removal of any of these is rejected at patch time, not only at publish.

### 7.4 Policy Controller

Deterministic code. Inputs and outputs per ToSpec §9.3. Result shape returned in `CaseView.policy`:

```json
{
  "code": "READY_FOR_DECISION",              // or WAITING_FOR_CARDHOLDER, EVIDENCE_CONFLICT, REVIEWER_REQUIRED, CREDIT_ELIGIBLE, DISPUTE_ESCALATION_REQUIRED, CREDIT_ISSUED, CLOSED …
  "label": "Ready for decision",            // human label for the main UI
  "outcome": "unknown" | "authorized" | "unauthorized",
  "credit_eligible": true,
  "verify_needed": false,
  "rules_passed": ["charge_identified", "cardholder_authenticated", "duplicate_search_done", "structured_verification"],
  "rules_failed": ["receipt_required_above_75"],
  "blocking_reason": "The packet is eligible for credit, but reviewer approval is still required.",
  "evidence_used": ["CHG-1042", "PO-219", "DLV-882 v1", "MSG-2251", "CALL-1042"],
  "policy_version": 1, "snapshot": "EV-3B7B7F", "evaluated_at": "…"
}
```

Runs on every evidence change and before every money-affecting command. Cannot be removed, disabled, re-instructed or overridden by chat or specialists. Policy v1 rule groups (as shown in the Policies screen): Intake (charge identified, cardholder authenticated, claims are not facts, duplicates ruled out) · Evidence (receipt required above $75, purchase records agree, structured callback results) · Decision and money (credit requires reviewer approval, approvals bind to evidence/policy/workflow, credit tied to one transaction, credit idempotent) · Remediation and closure (controls need admin approval, final message states only recorded actions, final outcome recorded).

### 7.5 Specialists

| Field | Constraint |
|---|---|
| Name | ≥3 chars |
| Purpose | ≥10 chars |
| Permitted records | ⊆ {Card transactions, Purchase orders, Receipts, Delivery records, Merchant history, Cardholder messages, Case notes}; ≥1 |
| Permitted tools | ⊆ approved library {Transaction search, PO lookup, Document reader, Merchant lookup, Related-charge search, Message drafting}. Issue/reverse credit, apply card controls, run custom code are not selectable. |
| Output record type | Finding · Evidence summary · Draft message · Recommendation |
| Handoff target | Policy Controller · Finance analyst · Decision Packet Preparer · Cardholder Follow-up |
| Execution mode | Automatic · Analyst-started |
| Human checkpoint | None · findings only · Analyst reviews output · Analyst approves each run |
| Optional | Trigger condition, example questions, character (appearance only), synthetic budget estimate |
| Status | `draft` → (added to workflow draft) → becomes active only when that workflow version is published |
| Prohibited (inherited, not editable) | the nine restrictions in §5 |

Initial set (ToSpec §8.3): Charge Investigator, Related-Transaction Investigator, Receipt and Document Reviewer, Cardholder Follow-up, Live Verification Agent, Decision Packet Preparer, Prevention Planner; Policy Controller is listed last as `Required control · Always enforced`.

**Retry limits and failure paths in v3:** cardholder follow-up loop max 2 (`response` back-edge), verification contradicted loop max 2, reviewer rejection loop max 2, not-eligible loop max 1; `Retry within limits` re-runs a failed step once then escalates to Analyst handoff (hold, reassign or close unresolved). Callback attempts per response: 2.

**Live motion rule:** a specialist shows `Working` and animates only while a real run step is executing (`run.step_started` … `run.step_completed`). No idle animation and no team-assembly sequence on page load. **Case queue rows** each show the character of the specialist responsible for that case in a 40px tile (updated design direction): still when idle; an amber clock badge when waiting; a chartreuse dot and working loop only during a real run; a single 350ms lean plus a 2px lift on row hover or focus. Reduced motion removes the lean, lift and loop.

---

## 8. Responsive and interaction rules

### 8.1 Breakpoints and minimums

| Region | Rule |
|---|---|
| Sidebar | Expanded 220px default, resizable to 320px (drag or keyboard); collapsed 64px icon rail with tooltips; never auto-collapses while working; ≤760px becomes an off-canvas drawer with scrim. |
| Case left column (task, charge impact, Activity) | `flex: 999 1 400px`; takes remaining width. |
| Case middle column (tabs) | min 364px (fits Evidence · Communications · Decision · Run details), max 520px; sticky with its own scroll ≥1200px; stacks under the left column ≤899px. |
| Vera rail | 360–400px; becomes a right drawer opened from the top-bar `Vera` button below 1280px (D5). |
| Activity | Compact rows (time · actor · action + record chip · result); in narrow columns time sits beside a stacked actor/action/result. Desktop table header only when width ≥420px. |
| Workflow canvas | min height 360px; never re-mounted on resize; zoom, selection, scenario and tab preserved. |
| Checks panel | default ≈35% of builder height, min 180px; expanded / compact (≤200px) / collapsed; height and internal list/trace split remembered for the session; `Reset panel layout` in ⋯. |
| Node inspector | 320–520px, resizable from its left edge, collapsible to 44px, closable; overlay drawer below 1200px or when the canvas would drop below its minimum. |
| Mobile (≤760px) | Cases queue rows become structured blocks; case regions stack; checks panel is a bottom sheet; splitters hidden. |

> **Decision D5 (resolved): 1280px.** Below 1280px Vera becomes a right-side drawer so the case workspace never gets too narrow. Background: the hierarchy brief said "below 1200px collapse Vera into a drawer". With the sidebar's required 220px minimum, the case center column would fall below 640px between 1200–1279px, so the prototype switches at 1280px.

### 8.2 Splitter accessibility

Labels: `Resize workflow checks`, `Resize inspector`, `Resize navigation`, `Resize scenario list`. `role="separator"` with `aria-orientation`, `aria-valuemin/max/now`. Keys: Arrow ±16px (±3% for the list split), Shift+Arrow ±64px (±10%), Home = minimum, End = maximum. Visible focus ring (2px cobalt). While dragging: `cursor: row-resize`/`col-resize`, text selection disabled, a subtle handle tint; DOM style is updated directly and state is committed once on pointer-up.

### 8.3 Interaction rules

1. Never blank a panel or show a full-page loader during a transition. Skeletons only on first load.
2. A running step shows an inline status (`Charge Investigator · checking transaction`, `Waiting for cardholder response…`) and keeps prior content visible.
3. Update only the affected record; append exactly one Activity row per event.
4. Preserve selected tab, record selection, scroll position, expanded sections, draft text and Vera drawer state across updates and refresh.
5. Local transitions 180–260ms on the changed element only; no page-wide fades, bounces, glows or layout jumps.
6. Status icons live in a fixed 20px slot and crossfade; no layout shift.
7. Text wraps by word. IDs (`CHG-1042`, `MSG-2251`) never break internally (`white-space: nowrap` on reference chips). Nothing wraps one character per line; every column has a min width.
8. One primary (chartreuse) action per task. Secondary actions are outline or ghost.
9. Role switching changes visibility and actions only; it never submits anything (US-K02).
10. Communications, transcripts and identity checks open inside the case; `Open in Evidence` shows the record with `← Back to communications`.

---

## 9. Design tokens

### 9.1 Color

| Token | Value | Use |
|---|---|---|
| `--ink` | `#0c0a08` | Primary text, active tab underline |
| `--ink2` | `#3b3a39` | Secondary text |
| `--mute` | `#6f6c68` | Labels, metadata |
| `--canvas` | `#f4f2f0` | App background |
| `--paper` | `#ffffff` | Cards, panels |
| `--rule` | `#e5e7eb` | Borders |
| `--rule2` | `#efede9` | Row dividers |
| `--cobalt` | `#2446c7` | Selection, links, due-today, active nav, needs-review icon |
| `--cobalt-wash` | `#eef2fc` | Selected row background |
| `--chart` | `#e4f222` | **One** primary action per task only; never as a dot beside ordinary labels |
| `--ok` | `#1d6a43` | Completed, passed |
| `--warn` | `#8a5300` (icons `#b7791f`) | Waiting, blocked-by-others |
| `--bad` | `#b42318` | Overdue, blocked by policy, failed |
| Dark button | `#1a1919` | Secondary emphasis (`Open cardholder view`, chat actions) |

### 9.2 Typography

Inter (`cv01`, `ss03`), base 14px / 1.5. Tabular numerals for money, dates and counts. Monospace (`ui-monospace`) only for section eyebrows (`YOUR NEXT STEP`), IDs in record headers, and the environment pill.

| Role | Size / weight |
|---|---|
| Page title (`Cases`) | 22–26px / 500, −0.02em |
| Case amount | 24px / 500 |
| Task title | 19px / 600, −0.015em, max 46ch |
| Section title | 14px / 600 |
| Specialist detail title | 20px / 600 |
| Top-bar context | 15px / 560 |
| Body | 13.5–14px; paragraphs max 68ch |
| Labels / metadata | 12–12.5px, `--mute` |
| Summary metric | 22px (lead 26px) / 500 |

### 9.3 Spacing, borders, radius

4px base grid; common gaps 8 / 12 / 16 / 20 / 24px. Page gutter 24px (16px at ≤1279px and on mobile). Borders 1px `--rule`; row dividers 1px `--rule2`; task card border `#d9d6d1`. Radius: chips/buttons 6px, inputs 7–8px, panels/cards 10–12px, drawers 0 at the docked edge.

### 9.4 Buttons and states

| Variant | Spec |
|---|---|
| Primary (`btn go`) | Chartreuse fill, ink text, 36–40px high, 6px radius — one per task |
| Dark (`btn dark`) | `#1a1919` fill, white text |
| Default (`btn`) | White, `#d3d3d3` border |
| Ghost (`btn ghost`) | Transparent, `--ink2` text |
| Small (`sm`) | 30px high, 12.5px text |
| Disabled | 45% opacity, `not-allowed`, with a visible reason nearby |
| Reference chip (`ref`) | 26px high, 1px border, 12px tabular text, no wrap |
| Selected row | Cobalt 3px left bar + `--cobalt-wash` |
| Selected nav | Cobalt text + 2px left bar; parent of a selected child is ink, not cobalt (one indicator) |
| Tabs | Text tabs, active = ink + 2px ink underline |
| Filters | Quiet text tabs with counts; active = ink + 2px underline |
| Overdue | `--bad` text (`2h overdue`); queue blocker `--warn` |
| Blocked | Red policy-mark icon + concise reason; never shaking |

### 9.5 Motion

| Use | Timing |
|---|---|
| Local state change (title, status, row) | 180–260ms, `cubic-bezier(0.2, 0.8, 0.2, 1)`, opacity 0.25→1 |
| Status icon crossfade | 200ms |
| Task character change | 220ms, enters from 10px offset |
| Drawers (Vera, specialist, sidebar mobile) | 220ms slide |
| Handoff connector (only during a real run) | ≤600ms |
| Working spinner | 1.1s linear loop, only during real runs |
| Character working loops | role-specific, low amplitude, stop at step completion |
| Dismissed: idle breathing/blinking, team-assembly stagger, pulsing glows | not used |

**Reduced motion** (`prefers-reduced-motion: reduce`): no movement (spinners static, drawers appear without sliding, no character motion); keep crossfades and every status marker; no information is conveyed by motion alone.

### 9.6 Copy rules

Finance-official and short. No AI-dashboard language (`Vera is working` → `In progress`). **Decision D6:** `Synthetic environment` appears once, in the top bar. `No funds moved` and `Simulated` appear only next to the specific money or control action where they matter (credit, dispute submission, card controls, charge impact): `— simulated` on the button, `· simulated` in that action's result. Emails, calls, reminders, source-record labels and other panels carry no qualifier. No idempotency keys, request IDs, adapter names or command names outside Run details.

---

## 10. Backend handoff summary

### 10.1 Database entities

ToSpec §10.1 tables, plus additions the design requires (marked **+**):

`cases` (state, step, case_version, owner, due_at, workflow_version, policy_version, current_snapshot) · `case_assignments` · `card_transactions` · `cardholders` (**+** `contact_on_file` with verified_at) · `merchants` · `reports` · `claims` · `evidence_records` · `evidence_versions` · `findings` (**+** conflict status open/resolved/accepted, resolved_by) · `attachments` · `communications` (**+** `communication_drafts` versions, delivery result, overdue_at, reminders) · **+** `identity_verifications` (channel, bound_to, sends, attempts, cooldown_until, expires_at, status, method, history) · `callbacks` (**+** attempt, transcript lines, structured result, reviewer_notes) · `decision_packets` (versioned, snapshot hash) · `policy_evaluations` · `approvals` (binding: case, transaction, snapshot, policy_version, workflow_version; status pending/approved/returned/stale/superseded) · `provisional_credits` (**+** `unconfirmed` flag during uncertain result) · `dispute_packets` (status enum §3.1, submission_id) · `card_controls` (**+** `control_plans` with requested/approved/applied/declined sets) · **+** `closure_checklists` (or computed view) · `workflow_definitions` · `workflow_versions` (immutable graph JSON) · **+** `workflow_drafts` · **+** `workflow_check_runs` (per version + graph hash, per-scenario steps) · `workflow_runs` · `workflow_steps` (**+** run lines for live UI) · `specialist_definitions` (**+** status draft/active, appearance) · **+** `policy_versions` / `policy_drafts` · `idempotency_keys` (key, command, status pending/completed/failed_before/checking, request_id, attempts, first_at, last_at, result) · `audit_events` (append-only; **+** `actor_role` — the single role the command ran under, e.g. `reviewer` vs `card_admin` for the same person) · **+** `conversations` / `conversation_messages` (role-scoped, intent, signature).

### 10.2 API endpoints

Queries and commands listed in §3.2–§3.4. Summary:

- `GET /api/cases`, `/api/cases/summary`, `/api/cases/{id}`, `/evidence`, `/evidence/{rid}`, `/communications`, `/communications/{iid}`, `/decision-packet`, `/activity`, `/runs`, `/executions`, `/conversation`, `/stream`
- `POST /api/cases/{id}/commands/{command}` for all ~45 case commands in §3.3
- `POST /api/cases/{id}/ask`
- `POST /api/reports`; `GET /api/requests/{id}`; `POST /api/requests/{id}/responses`; `POST /api/verifications/{id}/answer`
- `GET/POST/PATCH/DELETE /api/workflows/{id}/…` (versions, drafts, validation, checks, publish)
- `GET/POST/PATCH /api/specialists/…`; `GET/POST /api/policies/{id}/…`

### 10.3 LangGraph nodes

LangGraph is used only for durable orchestration and checkpointing, never authority (ToSpec §10). Each node reads declared records, writes typed outputs, and hands off; consequential steps are interrupt points waiting for a human command.

| Node | Kind | Output | Interrupt / checkpoint |
|---|---|---|---|
| `intake` | trigger | case + claim | — |
| `charge_investigator` | specialist | finding (amount/PO/delivery diff) | — |
| `related_transaction_investigator` | specialist | related-charge finding | — |
| `receipt_document_reviewer` | specialist | evidence assessment, conflicts, extracted fields | — |
| `policy_evidence_sufficiency` (pc1) | deterministic call | policy result → route | — |
| `cardholder_follow_up` | specialist (draft) | communication draft | **interrupt:** `send_communication` |
| `await_cardholder_response` | wait | response or timeout | deadline timer |
| `identity_verification` | wait | verified / declined / expired / locked | **interrupt:** `send_verification_request`, `submit_otp` |
| `live_verification` | specialist + adapter | callback record | **interrupt:** `start_callback` |
| `decision_packet_preparer` | specialist | packet vN | — |
| `analyst_decision` | checkpoint | decision record | **interrupt:** `request_reviewer_approval` / `record_decision` |
| `policy_credit_eligibility` (pc2) | deterministic call | eligible / blocked | — |
| `reviewer_approval` | checkpoint | approval bound to snapshot | **interrupt:** `approve_decision` / `return_decision` |
| `credit_executor` | adapter (once) | credit record | **interrupt:** `issue_provisional_credit`; idempotency gate |
| `prevention_planner` | specialist | control plan | — |
| `admin_approval` | checkpoint | approved controls | **interrupt:** `approve_card_controls`, then `apply_card_control` |
| `dispute_packet_preparer` | specialist | dispute packet | **interrupt:** open/review/submit |
| `final_communication` | specialist (draft) | final message draft | **interrupt:** `send_communication` |
| `retry_within_limits` | deterministic | retry or escalate | — |
| `analyst_handoff` | checkpoint | hold / reassign / unresolved | human command |
| `close_or_monitor` | checkpoint | closed / monitoring | **interrupt:** `close_case` |

### 10.4 Worker jobs

| Job | Trigger | Effect |
|---|---|---|
| `deadline_watcher` | every minute | mark communication overdue once; reviewer deadline passed (enables backup reassignment) |
| `verification_expirer` | at `expires_at` | expire active identity requests |
| `adapter_executor` | command accepted | run simulated adapter after persisting the idempotency key |
| `uncertain_result_reconciler` | `checking` executions | look up by key; resolve to completed/failed |
| `specialist_runner` | workflow step | execute bounded model/tool calls, stream run lines |
| `policy_reevaluator` | evidence version added | evaluate, mark affected checks/approvals stale |
| `workflow_check_runner` | `run_workflow_checks` | dry-run all scenarios on synthetic adapters |
| `dispute_outcome_ingest` | synthetic feed / demo | `record_dispute_outcome` |
| `notification_fanout` | events | role unseen flags, stale-notification copy (US-B04) |

### 10.5 Event types

`report.received` · `report.linked` · `case.opened` · `investigation.started` · `specialist.started` · `specialist.completed` · `evidence.linked` · `evidence.version_added` · `evidence.reassessed` · `conflict.opened` · `conflict.resolved` · `communication.drafted` · `communication.approved` · `communication.sent` · `communication.delivered` · `communication.reminder_sent` · `communication.overdue` · `response.received` · `attachment.stored` · `verification.approved` · `verification.sent` · `verification.resent` · `verification.code_entered` · `verification.code_rejected` · `verification.push_approved` · `verification.declined` · `verification.expired` · `verification.cancelled` · `verification.verified` · `callback.approved` · `callback.started` · `callback.transcript_received` · `callback.result_recorded` · `callback.note_added` · `policy.evaluated` · `packet.prepared` · `decision.recorded` · `approval.requested` · `approval.reminder_sent` · `approval.reassigned` · `approval.approved` · `approval.returned` · `approval.stale` · `approval.superseded` · `credit.issued` · `credit.confirmed` · `credit.finalized` · `credit.reversed` · `execution.failed_before_effect` · `execution.uncertain` · `controls.recommended` · `controls.requested` · `controls.approved` · `controls.applied` · `controls.declined` · `dispute.prepared` · `dispute.opened` · `dispute.reviewed` · `dispute.submitted` · `dispute.submission_failed` · `dispute.outcome_recorded` · `case.held` · `case.resumed` · `case.reassigned` · `case.closed` · `workflow.draft_created` · `workflow.draft_updated` · `workflow.draft_discarded` · `workflow.checks_completed` · `workflow.published` · `specialist.draft_created` · `specialist.draft_updated` · `policy.draft_created` · `policy.published` · `run.step_started` · `run.step_line` · `run.step_completed` (stream only, not audit)

### 10.6 Idempotency keys

| Operation | Key |
|---|---|
| Report | `report:{transaction_id}:{client_nonce}` |
| Start investigation | `inv:{case_id}` |
| Send communication | `msg:{communication_id}` |
| Reminder | `rem:{communication_id}` |
| Cardholder reply | `reply:{request_id}` |
| Review response | `review:{response_id}` |
| Verification send / resend | `idv-send:{case_id}:{n}` |
| OTP attempt (cardholder only) | `idv-check:{verification_id}:{attempt}` |
| Push answer | `idv-push:{verification_id}` |
| Cancel / expire verification | `idv-cancel:{verification_id}` / `idv-expire:{verification_id}` (**new — G1**) |
| Callback attempt | `call:{response_id}:{attempt}` |
| Decision packet | `pkt:{case_id}:{snapshot_hash}` |
| Approval request | `sign:{snapshot_hash}:{returns_count}` |
| Approve / return | `approve:{approval_id}` / `return:{approval_id}` |
| Record decision | `decide:{case_id}:{kind}` |
| Provisional credit | `credit:{transaction_id}` |
| Dispute prepare / open / review / submit | `dsp:{case_id}` / `dsp-open:{id}` / `dsp-review:{id}` / `dsp-sub:{id}` |
| Control request (analyst) / skip (analyst) / approve, decline, apply (card admin) | `ctl-req:{sorted controls}` / `ctl-decline:{case_id}` / `ctl-approve:{plan_id}`, `ctl-decline:{case_id}`, `ctl-apply:{plan_id}` |
| Hold / resume / reassign | `{verb}:{case_id}:{case_version}` |
| Close / outcome | `close:{case_id}` / `outcome:{case_id}` |
| Workflow draft / check / publish | `wfdraft:{id}:{from}` / `wfcheck:{id}:{v}:{graph_hash}` / `wfpub:{id}:{v}` |
| Specialist → workflow | `spec-wf:{specialist_id}:{workflow_id}:{from_version}` |

Keys for money/communication/control/dispute operations are written **before** the adapter call (US-J04). A repeat returns `status: "replayed"` with the original result and adds an `Attempts` increment visible only in Run details.

### 10.7 Eval fixtures

ToSpec §15 fixtures 1–24, each asserting persisted state, `available_actions`, evidence status, findings/claims, policy result, approval validity, event history, idempotency result and recovery action. Design-driven additions:

| # | Fixture | Asserts |
|---|---|---|
| 25 | Identity: push approved | `verify` step, method recorded, policy outcome unchanged |
| 26 | Identity: wrong code ×3 (entered by cardholder) | locked, analyst sees `Verification failed`, routes to follow-up, case not closed, 3 `code_rejected` events attributed to the cardholder role |
| 27 | Identity: expiry + resend | expired event once, resend cooldown enforced, new key |
| 28 | Identity: push denied | analyst sees `Verification denied`, other method available, not treated as fraud |
| 29 | Call before identity | `start_callback` rejected (409) |
| 30 | Phone number in chat | recorded as claim, callback target unchanged, no event |
| 31 | Reviewer chat approval attempt | canned refusal, approval still pending, no event |
| 32 | Repeated "Can we close?" | one Q&A pair, no audit events |
| 33 | Dispute status sequence | prepared → ready_for_review → ready_to_submit → submitted; task/button/chat/activity agree |
| 34 | Dispute submission failure + retry | `failed` then `submitted` once |
| 35 | Control approve vs apply | apply before approve rejected; apply twice replays; analyst `approve_card_controls` and `apply_card_controls` → 403; `reviewer`-only grant → 403 |
| 36 | Credit-issued case | step is never an earlier task; rail never says `Credit issued` while next task is controls |
| 37 | Role switching | no commands, no events, same `case_version` |
| 38 | Refresh mid-run | same step, same selected tab/item, run resumes or shows interrupted |
| 39 | Specialist draft → workflow | draft created, active version unchanged, case still pinned |
| 40 | Required control removal | patch rejected for Policy Controller / checkpoint / recheck / decision record / idempotency gate |
| 41 | Workflow publish gates | blocked without checks on this draft; blocked on any failing scenario |
| 42 | D8 analyst never sees the code | no analyst read model, response, event payload, log line or rendered text contains the OTP; analyst `submit_otp` → 403 |
| 43 | D8 cardholder completes verification | code entered in the cardholder view → `Identity verified`; event `who=cardholder`; demo control labeled `Synthetic demo · acts as the cardholder` |
| 44 | D3 parallel tracks | after credit, the dispute can be prepared while the control plan is unsent; sending the plan does not reset the dispute; `final` is blocked until both tracks reach an outcome |
| 45 | D2 audit role separation | SIGN approval event has `role=reviewer`; CTL approve/apply events have `role=card_admin`; same actor `Dana Okafor` |
| 46 | D4 node kinds | every node in v3 has a `kind`; LangGraph build reads `kind`; changing the visual category does not change behavior |

Workflow dry-run scenarios already in the prototype: `Missing receipt · confirmed by callback`, `Cardholder recognizes it · receipt attached`, `Contradictory receipt`, `Cardholder does not respond`, `Unanswered callback`, `Reviewer returns case`.

Playwright role journeys (from the prototype regression suites; 174 checks across 6 suites at v35): analyst happy path, side paths (overdue, call failures, authorized path, credit timeout/interrupt), communications, identity states, specialists, workflow panels, layout widths 1440/1200/900/390.

### 10.8 Decisions (resolved Nov 10) and remaining open items

| ID | Decision | Resolution | Prototype (v35) |
|---|---|---|---|
| D1 | Cases table | Five-column `Case queue`: Case · What's blocking it · Next action · Owner · Due. Broad state in the case subtitle; waiting states stay as filters. | Implemented |
| D2 | Card administrator | `card_admin` is a separate backend role. Dana may hold both `reviewer` and `card_admin` in the demo, but permissions stay separate in authorization and in every audit event (`role` field). | Implemented: control commands require `card_admin`; events carry `role`; Activity shows `Dana Okafor · card admin` |
| D3 | After provisional credit | Dispute packet and prevention/control plan run in parallel. Controls still need card-admin approval. Closure waits for the required dispute, control and communication outcomes. | Implemented: parallel-track strip with `Work on this next`; final update waits for both |
| D4 | Workflow node types | Store the canonical behavior type (`kind`) on every node; map it to five visual categories in the builder. | Implemented: `kind` on nodes; inspector shows `Node type` |
| D5 | Vera drawer breakpoint | 1280px. Below that, Vera is a right-side drawer. | Implemented |
| D6 | Synthetic qualifier | `Synthetic environment` once in the top bar; `No funds moved` / `Simulated` only at the specific money or control action. | Implemented: qualifiers removed from email, call, reminder and source-record labels |
| D7 | Who applies card controls | Analyst recommends and submits the plan. Card admin approves **and** applies. The analyst cannot apply controls, even after approval. | Implemented: `Apply approved controls — simulated` lives in the card-admin view; analyst attempt → role rejection |
| D8 | OTP entry | Cardholder enters the code in the cardholder view or approved app flow. Analyst sees only: verification requested, awaiting cardholder, identity verified, failed, expired, denied. A labeled synthetic-demo control may simulate cardholder completion. | Implemented: analyst view has no code field or code text; `submit_otp` is cardholder-only |

Still open (ToSpec §18):

| ID | Decision | Options | Prototype today |
|---|---|---|---|
| ToSpec §18 #1 | Simulated control set | lock, replace, virtual card, merchant block, 30-day monitor | All five |
| ToSpec §18 #2 | Credit display | Immediate synthetic ledger credit | Immediate, labeled simulated |
| ToSpec §18 #3 | Transcript retention | Full transcript + structured record | Both, append-only |
| ToSpec §18 #4–7 | Runtime, Langfuse in CI, auth model, retention/redaction | Open | — |

**Gaps found in the prototype** (fix in the build; not design changes):

- **G1** `expire_verification_request` and `cancel_verification_request` have no idempotency key.
- **G2** `return_decision` collects only a note; US-F04 also requires requested next step and owner.
- **G3** `hold_case` uses a default reason; US-J05 requires the analyst to enter reason and next owner.
- **G4** Workflow publish, policy publish and specialist create run outside the command pipeline (no role/idempotency/audit stages).
- **G5** Send confirmation shows recipient and body only; US-D02 also requires channel, subject, attachments and case ID.
- **G6** Notifications/deep links with stale-task copy (US-B04) are not implemented beyond unseen-role dots.
- **G7** Attachment validation checks size (10 MB) but not file type (US-C06).
- **G8** No `expected_case_version` concurrency check exists in the prototype (single browser); required for US-J06.

### 10.9 Assumptions

1. Vera_ToSpec.md v1.1 wins on behavior; the latest design briefs win on layout and copy where ToSpec is silent or older; conflicts are listed in §10.8.
2. One synthetic tenant, one live case (CHG-1042); the other queue rows are display fixtures and are not openable.
3. Identity verification (OTP/push) is simulated and proves channel control only; it is not bank-grade authentication.
4. The analyst holds the admin role for Automations in the demo.
5. Times are on a demo clock starting Nov 10, 9:08 AM; deadline/expiry jobs can be fast-forwarded by demo controls that exist only in the synthetic environment.
6. Characters are appearance-only; their GLB assets are out of scope for the backend.
7. Q&A answers are generated from `CaseView` and cited records; a model may phrase them but cannot add facts or trigger commands.
