# Vera — Comprehensive User Stories

## Purpose

This document translates Vera’s product behavior into testable user stories. It is a companion to `Vera_ToSpec.md` and is the behavioral contract for frontend, backend, workflow, policy, and evaluation work.

The canonical product is a post-report corporate-card investigation workspace. The older supplier-payment/bank-detail flow is not the primary product contract.

Every story includes acceptance criteria. Stories marked **critical** must be implemented and covered by automated tests before the demo is considered complete.

---

## Personas

### Cardholder

A person whose corporate card was charged. They need a simple, private way to answer finance questions and attach supporting material.

### Finance analyst

Owns the investigation. They inspect records, request information, approve bounded verification actions, prepare decisions, coordinate follow-up, and manage the case.

### Finance reviewer

Independently reviews the current decision packet and approves or returns consequential decisions.

### Card administrator

Approves and applies card controls such as locking/replacing a card or blocking a merchant.

### Finance operations administrator

Configures bounded specialists, workflows, policies, test fixtures, and access. They do not receive unrestricted authority.

### Vera and finance specialists

AI-assisted investigators that retrieve permitted data, compare records, draft work, recommend findings, and hand off. They are not decision-makers.

---

## Product-wide acceptance rules

These rules apply to every story:

- A claim is not a verified fact until supported by permitted evidence.
- Every consequential action has an explicit actor, role, timestamp, target, and result.
- Every source record is versioned and traceable.
- Material changes stale affected checks and approvals only.
- Agent output never satisfies a deterministic policy rule by itself.
- The UI never exposes an action that the backend would reject.
- Repeating an idempotent action does not create a duplicate side effect.
- A failed or uncertain action never appears as successful.
- Every blocked state names the reason, owner, and next recovery action.
- Simulated actions are clearly labeled and never imply real money or external messages moved.
- Related transactions are visible but never implicitly included in the current decision.

---

# Epic A — Intake and case creation

## US-A01 — Submit a suspicious-charge report **critical**

**As a** cardholder, **I want to** report a charge I do not recognize, **so that** finance can investigate it.

### Acceptance criteria

- The report captures transaction, card, merchant, amount, posting date, cardholder, statement, and optional attachments.
- The report is stored as a claim, not as a confirmed fraud finding.
- A stable report ID is created, such as `REP-1042`.
- A case is created or linked to the correct transaction.
- The cardholder receives a confirmation with the case reference and expected next step.
- The report cannot be submitted twice by refreshing or double-clicking.

## US-A02 — Authenticate the reporting cardholder **critical**

**As a** finance system, **I want to** associate the report with an authenticated cardholder, **so that** unauthorized users cannot create or answer a case as someone else.

### Acceptance criteria

- The report records the authenticated profile used for intake.
- An unauthenticated report is either rejected or placed in a clearly marked intake queue.
- A claim cannot be treated as authenticated merely because it contains a name or email address.
- The authentication event is recorded in case history.

## US-A03 — Identify the posted transaction **critical**

**As a** finance analyst, **I want to** see the exact posted transaction attached to the report, **so that** the investigation is bound to one financial event.

### Acceptance criteria

- The case shows transaction ID, merchant, amount, card ending, posted date, and currency.
- Ambiguous matches require analyst selection.
- A case cannot enter financial decision work without a transaction target.
- The target transaction cannot silently change after a decision is prepared.

## US-A04 — Open an existing case instead of duplicating it **critical**

**As a** finance analyst, **I want to** see that a report already belongs to an open case, **so that** duplicate investigations are avoided.

### Acceptance criteria

- Matching reports display the existing case.
- The system records the new report as a related intake event.
- A duplicate case is not created unless an authorized user explicitly chooses to separate it.
- The case history shows why the reports were linked or separated.

## US-A05 — Preserve the initial report exactly **critical**

**As a** reviewer, **I want to** see the original report unchanged, **so that** later explanations do not overwrite the initial allegation.

### Acceptance criteria

- The initial statement remains immutable.
- Later cardholder messages are separate records.
- The UI labels the initial statement as a claim.
- A later response may support, clarify, conflict with, or leave the report unresolved.

---

# Epic B — Analyst case overview

## US-B01 — See the amount and exposure at a glance **critical**

**As a** finance analyst, **I want to** see financial values on the Cases dashboard, **so that** I can prioritize work by both urgency and exposure.

### Acceptance criteria

- The dashboard shows open exposure, due-today amount, overdue amount, and temporary credits issued.
- Amounts are calculated from current case state.
- The dashboard does not call the amounts losses or savings.
- Synthetic qualifiers are shown once at the environment or metric level.

## US-B02 — Find cases needing action **critical**

**As a** finance analyst, **I want to** see current state, next action, owner, waiting party, amount, and due date for each case, **so that** I know what to do next.

### Acceptance criteria

- The Work to review table contains Case, Current state, Next action, Owner, Waiting on, Due, and amount.
- A case row opens the correct case.
- Non-interactive fixture rows do not look clickable.
- Due formats are consistent.

## US-B03 — Filter cases by urgency and responsibility

**As a** finance analyst, **I want to** filter by due today, overdue, waiting on me, waiting on cardholder, and waiting on reviewer, **so that** I can focus my queue.

### Acceptance criteria

- Filters do not change case state.
- Counts reflect current data.
- Selected filters are visible.
- Clearing filters returns to the complete permitted case list.

## US-B04 — Open the relevant task from a notification **critical**

**As a** finance analyst, **I want to** open the exact case task from activity or notification, **so that** I do not need to search manually.

### Acceptance criteria

- A notification links to the case and current task.
- Stale notifications explain that the task has changed.
- Opening a notification does not perform the action.

---

# Epic C — Investigation and evidence

## US-C01 — Start a bounded investigation **critical**

**As a** finance analyst, **I want to** start the investigation for the selected charge, **so that** Vera can inspect permitted records.

### Acceptance criteria

- The run is bound to one case, transaction, workflow version, and policy version.
- The analyst sees useful intermediate findings.
- A run cannot read records outside its declared scope.
- The run is safe to retry.

## US-C02 — Compare charge and purchase records **critical**

**As a** finance analyst, **I want to** see differences between the card charge, purchase order, receipt, and delivery record, **so that** I understand the discrepancy.

### Acceptance criteria

- Each comparison cites the source record and field.
- Missing evidence is distinct from conflicting evidence.
- The result is a finding, not an automatic fraud conclusion.
- The analyst can open the original records.

## US-C03 — Link related transactions safely **critical**

**As a** finance analyst, **I want to** find related charges, **so that** I can identify patterns without accidentally combining cases.

### Acceptance criteria

- Relatedness requires a full synthetic transaction identity plus source support.
- Matching last four digits alone is insufficient.
- Related charges show separate status, amount, and case scope.
- A decision on one charge does not approve or credit another.

## US-C04 — Distinguish claim, finding, and fact **critical**

**As a** reviewer, **I want to** know whether a statement is a claim or supported finding, **so that** I do not mistake a model summary for proof.

### Acceptance criteria

- Reports and replies are labeled Claim until corroborated.
- Findings link to source records.
- A specialist’s agreement is not evidence.
- The UI explains why a claim remains unresolved.

## US-C05 — Detect conflicting statements **critical**

**As a** reviewer, **I want to** see when the initial report conflicts with a later response, **so that** the contradiction is resolved deliberately.

### Acceptance criteria

- The initial and later statements remain separate.
- The system creates a structured conflict finding.
- The conflict has a status: open, resolved by evidence, or accepted as unresolved.
- If policy requires clarification, approval and credit remain blocked.
- The case shows a next action to resolve the conflict.

## US-C06 — Add an attachment as evidence **critical**

**As a** cardholder, **I want to** attach a receipt or explanation, **so that** finance can review it.

### Acceptance criteria

- File type and size are validated.
- The attachment is linked to the case and sender.
- A new evidence version is created.
- The attachment is marked pending review until assessed.
- Uploading a file does not automatically verify the report.

## US-C07 — Preserve contradictory documents **critical**

**As a** reviewer, **I want to** see conflicting documents instead of having one disappear, **so that** I can judge the inconsistency.

### Acceptance criteria

- Both documents remain accessible.
- Each has a source, version, timestamp, and status.
- The conflict appears in the decision packet and activity history.
- Replacing a document creates a new version rather than overwriting the original.

---

# Epic D — Cardholder communication

## US-D01 — Draft a focused request **critical**

**As a** finance analyst, **I want Vera to** draft a focused request for the missing information, **so that** the cardholder is not asked to repeat resolved questions.

### Acceptance criteria

- The draft names the transaction and asks only unresolved questions.
- The draft shows the requested evidence and reply deadline.
- The draft is editable.
- Nothing is sent until an authorized user explicitly sends it.

## US-D02 — Review before sending **critical**

**As a** finance analyst, **I want to** review a draft before sending it, **so that** Vera cannot communicate externally without my action.

### Acceptance criteria

- The send action shows recipient, channel, subject, body, attachments, and case ID.
- The analyst can edit or discard the draft.
- Sending creates one communication record and one activity event.
- Double-send returns the original result.

## US-D03 — Cardholder sees a simple task

**As a** cardholder, **I want to** see only the charge context and question I need to answer, **so that** I am not exposed to internal finance architecture.

### Acceptance criteria

- The cardholder does not see internal IDs, policy rules, specialists, or run traces.
- The page supports response options, note, attachment, deadline, and send.
- The submitted response is visible to finance as a new evidence record.

## US-D04 — Handle no response **critical**

**As a** finance analyst, **I want to** see when the cardholder misses a deadline, **so that** I can send a reminder, reassign, hold, or continue through another permitted path.

### Acceptance criteria

- The case becomes waiting/overdue with a clear owner.
- The missed deadline is recorded once.
- A reminder is a separate explicit communication.
- The case does not silently advance.

---

# Epic E — Verification and callback

## US-E01 — Request a verification action **critical**

**As a** finance analyst, **I want to** review the proposed callback target and questions, **so that** the verification is limited to the open issue.

### Acceptance criteria

- The target contact source is shown.
- The approved question set is shown.
- The analyst explicitly authorizes the simulated callback.
- The callback cannot be started from model prose alone.

## US-E02 — Record a structured callback result **critical**

**As a** finance analyst, **I want to** see a structured callback result, **so that** the result can be evaluated by policy.

### Acceptance criteria

- The record includes target, attempt, outcome, answered questions, unresolved questions, and actor.
- No-answer, non-confirming, and confirming outcomes are distinct.
- A transcript or structured summary is linked to the call record.
- The callback result does not overwrite prior attempts.

## US-E03 — Retry an unsuccessful callback **critical**

**As a** finance analyst, **I want to** retry or hold after an unanswered callback, **so that** the case does not get stuck.

### Acceptance criteria

- The failed attempt remains in history.
- “Call again” creates a new attempt ID.
- The retry still requires the configured permission/checkpoint.
- A non-confirming retry does not pass the check.

---

# Epic F — Decision packet and reviewer

## US-F01 — Prepare a decision packet **critical**

**As a** finance analyst, **I want to** create a packet summarizing the current evidence, **so that** a reviewer can decide without reconstructing the case.

### Acceptance criteria

- The packet includes exact transaction, recommendation, supporting evidence, conflicts, open gaps, policy result, and requested action.
- Source records are separate from findings and claims.
- The packet records evidence snapshot, workflow version, and policy version.
- Creating a packet does not approve or execute anything.

## US-F02 — Ask Vera about the packet **critical**

**As a** reviewer, **I want to** ask case-scoped questions about the packet, **so that** I can understand the recommendation quickly.

### Acceptance criteria

- “Who do I call?”, “What is missing?”, “Why is credit blocked?”, “What supports this?”, “What changed?”, and “Related charges?” return direct answers.
- Answers cite permitted source records.
- The chat does not approve, issue credit, or edit evidence.
- The same question does not create duplicate activity events.

## US-F03 — Approve a current packet **critical**

**As a** finance reviewer, **I want to** approve a complete current packet, **so that** the proposed action becomes eligible for the next controlled step.

### Acceptance criteria

- Approval is a dedicated action, not a chat interpretation.
- The reviewer identity is recorded.
- Approval is bound to case, transaction, evidence snapshot, policy version, and workflow version.
- Double-clicking approval creates one approval.
- Approval does not itself issue credit.

## US-F04 — Return a packet **critical**

**As a** reviewer, **I want to** return a packet with a reason and requested evidence, **so that** the analyst can address the problem.

### Acceptance criteria

- A return requires a reason.
- A requested next step and owner are recorded.
- The original packet remains immutable.
- A new packet version can be prepared after the gap is addressed.

## US-F05 — Invalidate stale approval **critical**

**As a** policy controller, **I want to** invalidate affected approval after a material evidence change, **so that** old approval cannot authorize a new financial action.

### Acceptance criteria

- The original approval remains visible as stale.
- The changed field and new evidence version are recorded.
- Only affected checks reopen.
- Credit/dispute/card-control actions are blocked until required reapproval.

---

# Epic G — Credit, dispute, and remediation

## US-G01 — Evaluate provisional-credit eligibility **critical**

**As a** finance analyst, **I want to** see whether provisional credit is eligible, **so that** I understand what is required before requesting it.

### Acceptance criteria

- Eligibility is a deterministic policy result.
- The result lists passed and failed rules.
- A model recommendation cannot make an ineligible case eligible.
- The UI shows the next missing requirement.

## US-G02 — Issue provisional credit safely **critical**

**As a** finance analyst, **I want to** issue approved simulated credit exactly once, **so that** the case reflects the financial action without duplicate credit.

### Acceptance criteria

- Current evidence, policy eligibility, decision packet, reviewer approval, and role are checked.
- The credit is bound to one transaction.
- The operation is idempotent.
- The result is labeled simulated.
- The charge remains visible and the current exposure is recalculated.
- An uncertain adapter result is looked up before retry.

## US-G03 — Prepare a dispute packet **critical**

**As a** finance analyst, **I want to** prepare a dispute packet from the current evidence, **so that** the dispute can be reviewed before simulated submission.

### Acceptance criteria

- The packet includes transaction, report, verification, supporting evidence, merchant history, and recommended reason.
- The packet status distinguishes prepared, ready for review, ready to submit, submitted, and failed.
- No external card network is contacted.
- Submission is a separate explicit action.

## US-G04 — Record simulated dispute submission

**As a** finance analyst, **I want to** record that the dispute packet was submitted in the synthetic environment, **so that** the case can move forward without implying a real network action.

### Acceptance criteria

- The action is labeled simulated.
- The submission is idempotent.
- The submission ID and timestamp are recorded.
- Repeating the action returns the original submission.

## US-G05 — Recommend card controls

**As a** prevention specialist, **I want to** recommend targeted card controls, **so that** the finance team can reduce future exposure.

### Acceptance criteria

- Recommendations are tied to the case and evidence.
- The specialist cannot apply controls.
- Each control has a reason, scope, owner, and approval requirement.
- The recommendation does not claim prevention has already occurred.

## US-G06 — Approve and apply card controls **critical**

**As a** card administrator, **I want to** approve and apply a control plan explicitly, **so that** card changes cannot happen silently.

### Acceptance criteria

- Controls have a clear admin owner.
- Approval and application are separate events.
- Applying before approval is rejected.
- The applied control and timestamp are recorded.
- Repeating application is idempotent.

## US-G07 — Send final communication

**As a** finance analyst, **I want to** send a final status update, **so that** the cardholder knows what happened.

### Acceptance criteria

- The message reflects only recorded actions.
- It does not claim credit, dispute, or card control actions that did not occur.
- The message is reviewable before sending.
- It creates one communication event.

## US-G08 — Close or monitor a case **critical**

**As a** finance analyst, **I want to** close or monitor only when required work is complete, **so that** unresolved work is not hidden.

### Acceptance criteria

- A single closure checklist shows all applicable requirements.
- Open requirements block closure.
- Each open requirement has owner and next action.
- Closing records final outcome, actor, timestamp, and evidence snapshot.
- A closed case rejects new actions unless explicitly reopened by policy.

---

# Epic H — Workflow and specialist configuration

## US-H01 — Browse bounded specialists

**As an** operations administrator, **I want to** see which specialists exist and where they are used, **so that** I understand the workflow without reading implementation details.

### Acceptance criteria

- The list shows name, narrow purpose, status, and workflow usage.
- Statuses distinguish Available, Used in workflow, Not in workflow, Draft, and Required control.
- Policy Controller is shown as a required deterministic control, not an ordinary autonomous specialist.

## US-H02 — View a specialist contract

**As an** operations administrator, **I want to** inspect a specialist’s reads, tools, writes, handoff, and prohibitions, **so that** its authority is inspectable.

### Acceptance criteria

- The contract is concise by default.
- Detailed permission limits are available in one drawer.
- The page does not repeat the full guardrail explanation everywhere.

## US-H03 — Configure a specialist safely

**As an** operations administrator, **I want to** configure the specialist’s purpose and permitted tools, **so that** I can adapt the workflow without granting unsafe authority.

### Acceptance criteria

- Configurable fields are limited to approved fields.
- Arbitrary code, unrestricted tools, money movement, approval authority, policy overrides, and source-record mutation are impossible.
- Changes create a workflow draft/version.
- Active workflow versions remain unchanged.

## US-H04 — Build a workflow from approved nodes **critical**

**As an** operations administrator, **I want to** assemble a workflow from finance nodes, **so that** I can customize the sequence while preserving required controls.

### Acceptance criteria

- Nodes come from an approved library.
- Connections and branches are explicit.
- Required Policy Controller, human checkpoint, current-evidence recheck, decision record, and idempotency gate cannot be removed from money-affecting workflows.
- Invalid workflows cannot be published.

## US-H05 — Validate a workflow before publishing **critical**

**As an** operations administrator, **I want to** see precise validation errors, **so that** I can fix unsafe or incomplete workflows.

### Acceptance criteria

- Errors name the node and rule.
- Examples include missing reviewer approval, removed policy controller, missing human checkpoint, unreachable node, invalid cycle, and unbound money action.
- Validation runs on edit, save, and activation.

## US-H06 — Test a workflow in a dry run **critical**

**As an** operations administrator, **I want to** run synthetic scenarios, **so that** I can see state transitions and failure recovery before activation.

### Acceptance criteria

- The run does not call production adapters.
- Each step shows action, result, records, and policy effect.
- A node selection opens an inspector.
- A trace row selects the corresponding node.
- The canvas, trace, and inspector are expandable/resizable.

## US-H07 — Publish immutable versions

**As an** operations administrator, **I want to** publish a validated workflow version, **so that** running cases remain reproducible.

### Acceptance criteria

- Published versions cannot be edited in place.
- New changes create a draft/version.
- Running cases remain pinned to their start version.
- New cases use the active version.

---

# Epic I — Policy and governance

## US-I01 — Inspect the active policy

**As an** analyst or reviewer, **I want to** see the rules that affect the current case, **so that** blocked actions are understandable.

### Acceptance criteria

- The policy shows version, owner, effective date, and enforcement status.
- The current case’s failed and passed rules are linked.
- The policy page does not expose implementation noise in the main case flow.

## US-I02 — Create a policy draft

**As an** authorized administrator, **I want to** create a new policy draft, **so that** active controls remain stable while changes are reviewed.

### Acceptance criteria

- Active policies are immutable.
- Draft changes are validated and versioned.
- A draft cannot silently affect existing cases.
- Activation records actor, timestamp, reason, and effective version.

## US-I03 — Enforce policy independently of agents **critical**

**As a** finance organization, **I want** policy enforcement outside model responses, **so that** a prompt or agent error cannot authorize money.

### Acceptance criteria

- All money-affecting commands call Policy Controller.
- The controller evaluates current evidence and approval binding.
- A blocked policy result cannot be overridden by a UI or chat command.
- Policy results are persisted and traceable.

---

# Epic J — Activity, observability, and recovery

## US-J01 — View concise case activity

**As a** finance analyst, **I want to** see grouped human-readable activity, **so that** I understand what happened without reading raw event logs.

### Acceptance criteria

- Draft/approval/delivery events can be grouped.
- Primary rows use human language.
- Raw IDs, adapter calls, token data, and implementation details live in Run details.
- Events link to their case and source records.

## US-J02 — Inspect an execution trace

**As an** operator, **I want to** inspect exact workflow steps, **so that** I can debug a failure or explain a decision.

### Acceptance criteria

- Trace includes run, workflow version, step, specialist, inputs, outputs, policy effect, duration, retries, and errors.
- Trace details show state before and after.
- Technical details are not forced into the primary case view.

## US-J03 — See cost and token observability

**As an** operations administrator, **I want to** see model/tool usage and estimated synthetic cost, **so that** I can understand run efficiency.

### Acceptance criteria

- Usage attaches to a run and step.
- Costs are labeled estimated/synthetic.
- Cost data never acts as financial evidence or policy input.
- Missing usage data does not break the case.

## US-J04 — Recover from an uncertain adapter result **critical**

**As a** finance system, **I want to** look up an uncertain operation before retrying, **so that** a credit or communication is not duplicated.

### Acceptance criteria

- The idempotency key is persisted before adapter invocation.
- A retry first looks up the key/result.
- The UI shows checking/recovery rather than false success.
- The final result is exactly once.

## US-J05 — Preserve history on hold/resume **critical**

**As a** finance analyst, **I want to** hold and resume a case, **so that** a temporary pause does not erase failures or evidence.

### Acceptance criteria

- Hold requires a reason and next owner.
- Resume preserves previous failed/blocked results.
- The case returns to the appropriate next task.
- Hold and resume create durable events.

## US-J06 — Reload without losing progress **critical**

**As a** user, **I want to** refresh or revisit Vera, **so that** the case and conversation remain intact.

### Acceptance criteria

- Case state, messages, evidence, actions, approvals, and history persist.
- The user returns to the same case and role-safe view.
- A stale browser view is refreshed before executing a consequential action.

---

# Epic K — Evaluation and release quality

## US-K01 — Test actual state, not just text **critical**

**As a** developer, **I want to** run fixtures that assert persisted state and available actions, **so that** a fluent response cannot hide a broken workflow.

### Acceptance criteria

- Each fixture checks case state, evidence, policy, approvals, actions, events, and recovery.
- Tests cover both successful and failed paths.
- Conversation assertions include source IDs and action safety.

## US-K02 — Run role-based end-to-end tests **critical**

**As a** release owner, **I want to** test analyst, cardholder, reviewer, and card-admin journeys, **so that** role boundaries work in the actual UI.

### Acceptance criteria

- The successful CHG-1042 flow passes.
- No-response, conflict, reviewer-return, stale-approval, duplicate-action, and closure-blocked paths pass.
- Role switching does not execute actions.
- Refresh and back navigation do not lose state.

## US-K03 — Prevent regressions in CI **critical**

**As a** developer, **I want** formatting, typing, unit, integration, policy, idempotency, API, and Playwright checks in CI, **so that** changes do not reintroduce known failures.

### Acceptance criteria

- CI fails on any critical scenario regression.
- Fixtures are deterministic.
- Test output identifies case, workflow version, step, and failed invariant.
- The demo seed is resettable.

---

## Cross-story acceptance matrix

| Capability | Analyst | Cardholder | Reviewer | Card admin | Specialist | Policy |
|---|---:|---:|---:|---:|---:|---:|
| View case amount/state | Yes | Own request only | Yes | Relevant cases | Scoped | Yes |
| Create claim | Yes | Yes | No | No | No direct user claim | No |
| Add evidence | Yes | Own attachments | No | No | Evidence links only | Reads |
| Send communication | Explicit analyst action | Submit own response | No | No | Draft only | No |
| Start callback | Approves request | No | No | No | Recommends | Gates |
| Approve decision | No | No | Yes | No | No | Validates |
| Issue credit | Requests/executed if permitted | No | Approves prerequisite | No | No | Gates |
| Apply card controls | Requests | No | No unless card-admin role | No | Recommends | Gates |
| Change source record | No | No | No | Authorized admin only | No | No |
| Close case | Analyst after checklist | No | No | No | No | Validates |

---

## Definition of done

Vera is ready for the technical demo when:

1. The CHG-1042 successful journey completes from report through simulated credit, dispute preparation, remediation, final communication, and monitoring/closure.
2. The cardholder, analyst, reviewer, and card-admin views are role-appropriate.
3. The reviewer can ask Vera direct packet/evidence questions and receives sourced answers.
4. The product distinguishes claims, findings, source evidence, checks, approvals, and actions.
5. Material evidence changes stale affected approvals and reopen affected checks.
6. Duplicate and uncertain operations are safe.
7. Every blocked state has a reason, owner, next action, and recovery path.
8. Workflow and policy versions are immutable once active.
9. The UI does not repeat the same fact across every surface or expose raw technical trace in the main reading path.
10. The evaluation suite passes in CI and tests actual resulting state.

