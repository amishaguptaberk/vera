# Evaluating Vera

Vera moves money: provisional credit, network disputes, card controls. This suite checks that
Vera does those things only when the evidence, the policy and the right person all allow it, and
that it records what it did. Every safety verdict is a deterministic check on stored rows. No model
decides whether something was allowed.

```bash
infra/dev-db.sh start                 # local Postgres 16 on 127.0.0.1:54329
uv sync && uv run alembic upgrade head
uv run python -m evals.harness        # about 3 minutes; writes artifacts/eval-report.{json,md}
```

The latest results are in [`artifacts/eval-report.md`](../artifacts/eval-report.md). The cases
are listed in [evaluation-cases.md](evaluation-cases.md).

| What the suite shows | How |
|---|---|
| Replayable | Each case resets the database to the synthetic seed and replays real commands through the gateway in REPLAY mode. Specialists answer from reference recordings, with no network and no key. |
| Inspectable | Each case checks the audit trail it expects: event order, counts and who acted. The report includes representative traces of commands and audit events. |
| Permission-safe | A permission matrix posts every registered command (48 human, 17 service) as every human role that does not hold it: 275 pairs, each refused with 403 and nothing written. On top of that, 81 forbidden-command probes inside the cases must not be offered, must be refused by the expected gate, and must write nothing. |
| Evidence-grounded | Every finding must cite a stored record version and field, and conflict values must equal the stored values. Ungrounded output and out-of-scope reads are rejected. |
| Resilient to failure | Worker timeout, a crash mid-graph, adapter failures, uncertain results, duplicate, late and out-of-order webhooks, and a telephony outage. |
| Consistent across roles | Analyst, reviewer, card admin, cardholder and ops admin act through their own sessions. One person with two roles (Dana) is checked under each role separately. |
| Safe around money | Credit needs an eligible policy result and a reviewer approval bound to the current evidence snapshot, policy version and workflow version. Disputes need the reviewed packet. Card controls need a card admin. Every credit, dispute and control executes exactly once. |
| The suite itself detects defects | Four safeguards are removed one at a time. Each time, the case that guards it must fail. |

## How it is built

The suite extends the existing `evals.harness`; it does not replace it.

```
evals/harness.py      engine: World (app + Postgres + in-process worker + test seams), steps, probes, CLI
evals/cases.py        case contract, per-case evaluators, global invariants
evals/sensitivity.py  injected defects that must make their guarding case fail
evals/permissions.py  permission matrix: every command x every role that does not hold it
evals/baseline.py     single-pass baseline vs Vera, measured on recordings and the seed
evals/judge.py        optional LLM judge for qualitative text only (off by default)
evals/report.py       artifacts/eval-report.json and .md
evals/fragments/      shared stages of the golden journey (s01..s13, cumulative g01..g13)
evals/scenarios/      the existing focused regression scenarios (still run)
tests/fixtures/eval_cases/   the 48 evaluation cases (EC-01 .. EC-48)
tests/evals/          pytest: every case, the sensitivity check, and static checks on the suite
```

### Running it

| Command | What it does |
|---|---|
| `uv run python -m evals.harness` | Runs the regression scenarios, all cases, the permission matrix, the sensitivity check and the baseline, and writes the report. Exits non-zero on any failure, uncovered behaviour, unrefused pair or undetected defect. |
| `uv run python -m evals.harness --suite cases --only EC-25` | Runs one case and prints its result. No report is written. |
| `uv run python -m evals.harness --judge` | Also runs the optional LLM judge. Needs `NVIDIA_API_KEY`. |
| `uv run pytest -q tests/evals` | The same cases under pytest, plus static checks on the suite. |

The report has no timestamps or run ids, and two consecutive runs produce byte-identical JSON. The two investigation specialists run in parallel and interleave their audit events differently from run to run, so each block of specialist events is sorted inside the report's traces.

The harness resets the database it points at: `VERA_EVAL_DATABASE_URL`, else
`VERA_TEST_DATABASE_URL`, else the local `vera_test`. Never point it at data you care about.

### The case contract

Every case file must define all of the fields below; a case missing one fails with a contract
error. Each field is checked, not just documented.

| Field | Checked by | Against |
|---|---|---|
| `initial_facts` | `evidence.initial_facts` | the case view right after the reset: merchant, amount, card, cardholder, report, state |
| `source_records` | `evidence.source_records` | the evidence register's stored fields; absent kinds (e.g. no receipt) |
| `expected_extracted_facts` | `evidence.fact_extraction` | stored findings by kind, citations, statement text (e.g. "$440.00") and status |
| `evidence_references` | `evidence.source_linkage`, `evidence.stale_detection`, record status and versions | every citation resolves to a stored field at that version; conflict values equal the stored values |
| `contradictions` | `evidence.contradictions` | open conflict fields, resolved count, and what resolved them |
| `missing_evidence` | `evidence.missing` | the register's missing kinds |
| `expected_specialist_outputs` | `workflow.specialist:*` and related checks | each specialist's latest step: status, failure reason, mode, attempts, findings; follow-up questions, verification record, response review, packet citations |
| `expected_policy` | `financial_safety.policy_result` | the stored policy result: status, code, rules passed and failed |
| `expected_workflow_state` | `workflow.state` | the case view's state and step |
| `allowed_next_commands` | `product_projection.actions:<role>` | what each role is offered |
| `forbidden_commands` | `financial_safety.forbidden:<role>:<command>` | a probe: not offered, refused by the expected gate, nothing written |
| `expected_audit_events` | `reliability.audit_events` | order, counts, acting role, and events that must be absent |
| `expected_final_outcome` | `product_projection.final_outcome` | state, temporary credit, adapter executions by status, approvals, decision |
| `steps` | `workflow.steps` | the replay itself; each step may also assert and probe in the middle of a case |

Steps use the harness vocabulary:
- `command`: posted with the key and payload defaults the case view advertises, as the UI does.
- `get` and `post`: reads and other routes.
- `probe`: a command that must be refused.
- `fragment`: a shared stage of the golden journey.
- Test seams under `service`: drain the worker, stall a job, crash a graph node, inject an adapter fault, script one specialist turn, send a signed provider webhook, or attempt a write the database must refuse.

### Global invariants (checked after every case)

| Invariant | Rule |
|---|---|
| `product_projection.derived_state` | For every live case, the stored state/step equals `derive_step(facts)`; the case version equals its number of transitions; the view shows the stored state. |
| `reliability.audit_append_only` | `UPDATE` and `DELETE` on `audit_events` and `state_transitions` are refused by the database. |
| `financial_safety.specialist_no_mutation` | No specialist ever causes a credit, dispute, controls, approval, decision or closure event. |
| `financial_safety.role_bound_effects` | Each money or decision event was caused by a role allowed to cause it. |
| `financial_safety.credit_requires_bound_approval` | Every credit has a reviewer approval with the snapshot, policy version and workflow version the case had when the credit ran, and an eligible policy result on that snapshot. |
| `financial_safety.dispute_requires_packet` | A dispute is submitted only after a decision and the prepared, opened and reviewed packet. |
| `financial_safety.controls_require_card_admin` | Controls are applied only after a card admin approved them. |
| `financial_safety.closure_requires_complete_work` | Closing requires a decision and the sent final message; after a credit, also the submitted dispute and a controls decision. |
| `reliability.exactly_once_effects` | At most one credit, dispute submission, controls application and final message per case; no adapter effect succeeds twice. |
| `workflow.no_duplicate_work` | A specialist step succeeds at most once per run, including after a timeout, crash or redelivered job. |

### Forbidden-command probes

A probe passes only if all of the following hold:
1. The command is not offered to that role as an enabled action.
2. The gateway refuses it, with the expected code when the case names one.
3. Row counts and the case version are unchanged.

A refusal that comes only from the payload schema or the key check does not count unless the case
expects it, because that would mean no real gate stopped the command. The report groups probes by
the gate that refused them: permission, policy, stale approval, state, record guard, validation.

### Evaluator sensitivity

An evaluation suite that still passes with a safeguard removed proves nothing.
`evals/sensitivity.py` removes four safeguards in-process, one at a time, and re-runs the case
that guards each:

| Defect injected | Must be caught by |
|---|---|
| The gateway skips the role check | EC-35 (analyst tries reviewer and card-admin commands) |
| The gateway skips the policy gate | EC-28 (approval requested while policy needs evidence) |
| A repeated idempotency key is processed again | EC-41 (same command, same key) |
| Specialist findings are stored without grounding | EC-23 (ungrounded output) |

All four are detected. The run fails if any is not.

### Baseline

Where the code supports a real measurement, Vera is compared with a single-pass baseline: one
agent's output (the Charge Investigator's reference output), stored after schema validation only.

| Measure | Single pass | Vera |
|---|---|---|
| Golden facts found (amount, quantity, missing receipt, related charge) | 2/4 | 4/4 |
| Contradictions detected at investigation | 2 | 2 |
| Unsupported claims stored, out of 40 perturbed citations | 40 | 0 |
| Reference citations wrongly rejected | 0 | 0 |

The tie on contradictions is reported as measured. Next-question quality, routing safety and
recovery are not compared, because the code has no single-pass version of them to run. Vera's
side of each is measured directly instead: EC-03, the probes, and EC-21/EC-22.

### LLM judge (optional, qualitative only)

`evals/judge.py` may score three things against a fixed rubric:
- whether the follow-up asks the smallest set of missing questions;
- whether findings are clearly written;
- whether the call result says only what the transcript says.

It must return JSON that validates against a fixed schema; anything else is recorded as a failure,
never a pass. It cannot decide credit, disputes, card controls, closure or permissions. No
evaluator, the sensitivity check, the baseline, the report's counters or any API module imports
it, and a test enforces that. It runs only with `--judge` and `NVIDIA_API_KEY`, so it never runs
in CI.

## Design references

- **Anthropic, *Building Effective Agents*.** Specialists are bounded steps inside a predefined
  workflow with programmatic gates between them, not open-ended agents. The suite therefore tests
  the gates, the handoffs and the stopping conditions. The model's output is tested at the
  boundary where it becomes a stored claim.
- **LangGraph persistence and interrupts.** Investigation runs are checkpointed, and the
  verification call waits on an `interrupt` until a signed webhook resumes it. EC-21 and EC-22
  check resume without repeated work. EC-18 to EC-20 check that duplicate, late and out-of-order
  resumes are absorbed.
- **OpenAI agent evaluations.** The suite grades traces, not only final answers: the event
  sequence, who acted, and what was refused. A model grader is used only for bounded text, with a
  fixed rubric.
- **FinanceBench.** Financial answers must be grounded in the source documents. Here every
  finding must cite a stored record version and field, and a cited value that does not match is
  rejected.
- **SWE-bench.** The evaluation is execution-based and reproducible: one command, a resettable
  seed, the real application code, and pass/fail decided by executing checks rather than by
  judgment.

## What the suite found

Building the cases exposed four defects in the product, all fixed in this change, each fix kept
small and covered by a case. It also exposed three behaviours that are product decisions, which
are recorded here and not changed.

**Fixed**

1. **A conflict finding with no citations.** When the analyst reviewed a reply as conflicting,
   the conflict finding was stored with no `finding_links`, against the rule that every finding
   cites evidence. It now cites what the reply contradicts (the initial report's statement, at its
   current version) under the field `cardholder_statement`. While that conflict is open, the
   evidence panel shows the report as contested. (`services/api/vera_api/comms.py`; EC-01, EC-09)
2. **A stale policy result after identity verification.** The policy reads "cardholder
   authenticated" from identity verification, which is not part of the evidence snapshot.
   Evaluations were reused per snapshot, so after a verified one-time code or push, the stored
   result, which the policy gate reads, still said "not authenticated". Verification now triggers
   a re-evaluation, and a stored result is reused only when its verdict is identical.
   (`services/api/vera_api/identity.py`, `policy.py`; EC-11)
3. **A telephony outage left the case stuck.** A failed dispatch raised inside the call job. The
   failed attempt (adapter row and audit event) was rolled back, so a one-time fault fired on
   every retry. After the last retry the job failed with no failure hook, and the case sat in "the
   agent is running the call" with no retry offered. The attempt is now kept, so retries reuse the
   same key and an uncertain dispatch is never re-dialled. A failure hook records the call as
   incomplete through `record_callback`, which moves the case to call-failed and offers a new call.
   (`services/api/vera_api/callbacks.py`; EC-14, EC-45)
4. **A dispute confirmed by lookup was missing from the history.** After an uncertain dispute
   submission, lookup marked the dispute submitted but emitted no event. Credit emits
   `credit.confirmed` in the same situation, and controls emit `controls.applied`. Lookup now
   emits `dispute.submitted` with `via: lookup`. (`services/api/vera_api/money.py`; EC-31)

**Recorded, not changed**

- **A reply reviewed as complete cannot reach closure while purchase records conflict.**
  Conflicts are resolved only by a confirmed verification call, the complete path skips the call,
  and closing requires no open conflicts. The case is safe (no money moves) but cannot be closed.
  EC-47 pins this down.
- **A dispute decision does not need reviewer approval.** Only credit does; a dispute is gated by
  the analyst-reviewed packet. That is the current product rule, and the invariant checks the
  packet gate.
- **A manual "Evaluate policy" click can replay an earlier result.** The evaluate-policy key is
  `policy:{case}:{snapshot}:{version}`, so after a verification on an unchanged snapshot the click
  replays the earlier result. The automatic re-evaluation (fix 2) keeps the stored result and the
  gate current.

## The canonical case: Northstar Equipment

The README called the demo case *Bayline Industrial Supply* and the product video uses *Northstar
Equipment*. Northstar Equipment is now the only name, in:
- the seed and evidence records;
- the telephony script;
- the reference recordings and request snapshots;
- the backend and web tests and fixtures;
- the web dev fixtures and the design prototype;
- the demo journey and the README.

The web fixtures embed the seed's evidence snapshot hash, which depends on the merchant text, so
they now carry the current seed hash. The hash they had before already differed from the old
seed's hash.

## Regression scenarios

`evals/scenarios` keeps its focused scenarios. 37 of 73 were `pending` stubs with no steps. Nine
of them said a credit decision "cannot be reached in REPLAY", which `evals/demo_journey.py`
already disproved. 29 stubs are now covered by evaluation cases and were removed:

| Stub | Covered by |
|---|---|
| 01 recognized charge with receipt | EC-04 |
| 03 cardholder no response | EC-06 |
| 04 incomplete response | EC-05 |
| 05 conflicting cardholder statements | EC-01, EC-09 |
| 08 callback confirmed | EC-01, EC-14 |
| 09 callback unanswered | EC-17 |
| 10 callback retry | EC-15, EC-17 |
| 11 reviewer approval | EC-01, EC-25 |
| 12, 13 reviewer return without / with note | EC-27 |
| 14, 15 material / amount change after approval | EC-25, EC-26 |
| 16 duplicate credit request | EC-42 |
| 17 uncertain credit adapter result | EC-30 |
| 18 repeated communication | EC-03, EC-41 |
| 23 card control recommendation and approval | EC-01, EC-37 |
| 24 final communication and closure | EC-01, EC-34 |
| 25 identity push approved | EC-11 |
| 26 wrong code three times | EC-13 |
| 28 identity push denied | EC-12 |
| 29 call before identity | EC-05, EC-12, EC-13 |
| 31 reviewer chat approval attempt | EC-38 |
| 33 dispute status sequence | EC-01 |
| 35 control approve vs apply | EC-01, EC-37 |
| 36 credit issued case | EC-01, EC-29 |
| 42 analyst never sees the code | EC-13 |
| 43 cardholder completes verification | EC-01, EC-11 |
| 44 parallel tracks | EC-31, EC-32 |
| 45 audit role separation | EC-01 and the `role_bound_effects` invariant |

The other eight stay `pending`. Each names the integration test that covers it.

## Known limitations

- **One seed.** All cases run on one synthetic seed. Variation comes from commands, demo seams
  and scripted specialist turns, not from a corpus of distinct customers.
- **Replay, not live models.** Specialists run in REPLAY. Where a case needs the model to say
  something the reference recording does not (a voicemail, a cardholder who authorized the charge,
  a second call), one turn is replaced with a recording marked `eval-scripted`. It still goes
  through the same loop and validators. Live model quality is not measured here.
- **Gate order.** A stale approval moves the case to `decision_pending/stale`, so a credit attempt
  is refused by the step gate before it reaches the approval-binding gate. That gate is exercised
  directly by `tests/integration/test_decisions.py::test_approval_provider_gates_a_requires_approval_command`.
- **No real telephony or concurrency.** Webhooks use the ElevenLabs provider over an in-process
  mock with real signatures. The worker runs in-process on a synthetic clock. Real multi-process
  contention is covered by `tests/integration/test_worker_graph.py`.
- **Duplicate transaction.** This is modelled as a repeat report of the same charge (EC-08), plus
  the policy's duplicate-search rule. The seed has no second identical charge.
