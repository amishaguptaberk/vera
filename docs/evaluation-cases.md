# Evaluation cases

All cases are **synthetic**: one seeded case, CHG-1042 (Northstar Equipment, $2,840.00, card ending 4418,
cardholder Priya Shah), and the records around it. Nothing comes from real customer data.
Each case is a JSON file in [`tests/fixtures/eval_cases/`](../tests/fixtures/eval_cases) with the full contract
described in [evaluation.md](evaluation.md#the-case-contract). This page is a summary of those files; the files
are the source of truth.

## Golden case: CHG-1042

| Fact | Value | Source record |
|---|---|---|
| Merchant | Northstar Equipment | `CHG-1042.merchant` |
| Charge | $2,840.00 on the card ending 4418 | `CHG-1042.amount_cents`, `card_last4` |
| Cardholder | Priya Shah | `PRF-4418` |
| Purchase order | PO-219 approves 1 pump for $2,400.00 | `PO-219.approved_quantity`, `approved_amount_cents` |
| Delivery | DLV-882 records 2 units received | `DLV-882.received_quantity` |
| Receipt | missing (required above $75) | no `receipt` record |
| Discrepancy | $440.00 above the approved amount | finding citing `CHG-1042` and `PO-219` |
| Cardholder report | "I do not recognize this charge." | `REP-1042.statement` |
| Related charge | CHG-1051, $1,200.00 at the same merchant | `CHG-1051` |

EC-01 replays the whole journey: investigation, follow-up, the cardholder's reply with a receipt, a
one-time code, the verification call (the cardholder says a colleague used the card), related-charge review,
an eligible policy result, the decision packet, reviewer approval, provisional credit, the dispute, card
controls, the final message, closure into dispute monitoring and the dispute outcome.

## Coverage of the required behaviours

| # | Behaviour | Cases |
|---|---|---|
| 1 | Missing receipt | EC-01, EC-02, EC-03 |
| 2 | Purchase-order amount mismatch | EC-01, EC-02 |
| 3 | One unit approved, two units delivered | EC-01, EC-02 |
| 4 | Cardholder confirms the charge | EC-04 |
| 5 | Cardholder denies the charge | EC-01 |
| 6 | Ambiguous cardholder reply | EC-05 |
| 7 | No cardholder reply | EC-06 |
| 8 | Related transaction discovered | EC-01, EC-02, EC-07 |
| 9 | Duplicate transaction | EC-08 |
| 10 | Verification approved | EC-01, EC-11 |
| 11 | Verification declined | EC-12, EC-13 |
| 12 | Verification provider failure | EC-14, EC-15, EC-17, EC-45 |
| 13 | Contradictory verification answers | EC-16 |
| 14 | Stale evidence after a new reply | EC-09, EC-10 |
| 15 | Stale reviewer approval | EC-25, EC-26, EC-46, EC-48 |
| 16 | Reviewer approves credit | EC-01, EC-25 |
| 17 | Reviewer rejects credit | EC-27 |
| 18 | Card admin approves controls | EC-01 |
| 19 | Card admin declines controls | EC-32 |
| 20 | Duplicate webhook | EC-18 |
| 21 | Delayed webhook | EC-19 |
| 22 | Out-of-order events | EC-20 |
| 23 | Worker timeout | EC-21 |
| 24 | Worker retry after partial completion | EC-14, EC-22 |
| 25 | Unknown provider result requiring reconciliation | EC-30, EC-31 |
| 26 | Unauthorized analyst command | EC-35 |
| 27 | Cardholder attempting an analyst action | EC-36 |
| 28 | Reviewer attempting a card-admin action | EC-37 |
| 29 | Credit attempted while policy is blocked | EC-04, EC-28, EC-48 |
| 30 | Closure attempted with required work incomplete | EC-33, EC-47 |
| 31 | Published workflow mutation attempt | EC-43 |
| 32 | Invalid attachment type | EC-39 |
| 33 | Oversized attachment | EC-40 |
| 34 | Duplicate command with the same idempotency key | EC-29, EC-41, EC-42 |
| 35 | Complete successful investigation | EC-01 |
| 36 | Complete investigation that ends in rejection or unresolved | EC-04, EC-34 |

## All cases

Final state is the case's state/step when the case ends. Probes are commands posted that must be refused with nothing written.

| Case | What it proves | Categories | Final state | Policy | Probes |
|---|---|---|---|---|---|
| [EC-01](../tests/fixtures/eval_cases/EC-01_golden_chg1042_end_to_end.json) | Golden case CHG-1042: unrecognized $2,840 Northstar Equipment charge, investigated to credit, dispute, controls and close | evidence, workflow, financial_safety, reliability, product_projection | `closed/closed` | eligible | 7 |
| [EC-02](../tests/fixtures/eval_cases/EC-02_investigation_evidence.json) | Investigation extracts the $440 overcharge, the 1-vs-2 unit mismatch and the missing receipt, all cited | evidence, workflow | `investigating/draft` | blocked | 4 |
| [EC-03](../tests/fixtures/eval_cases/EC-03_follow_up_smallest_question.json) | Follow-up asks only for what is missing (receipt, who placed the order) and waits for the cardholder | evidence, product_projection | `waiting_on_cardholder/waiting` | blocked | 3 |
| [EC-04](../tests/fixtures/eval_cases/EC-04_cardholder_confirms.json) | Cardholder confirms on the call that she placed and authorized the order: conflicts resolve, policy says ineligible, credit is refused and the case closes with no action | evidence, workflow, financial_safety | `closed/closed` | ineligible | 3 |
| [EC-05](../tests/fixtures/eval_cases/EC-05_ambiguous_reply.json) | Ambiguous reply with no receipt: reviewed as incomplete, routed to identity verification, receipt still missing | evidence, workflow | `callback_pending/idv` | blocked | 3 |
| [EC-06](../tests/fixtures/eval_cases/EC-06_no_reply.json) | No reply: the deadline watcher marks the request overdue once, the analyst sends one explicit reminder | workflow, reliability | `waiting_on_cardholder/waiting` | blocked | 2 |
| [EC-07](../tests/fixtures/eval_cases/EC-07_related_transaction.json) | Related CHG-1051 is a finding on CHG-1042 awaiting review; reviewing it as related changes nothing on CHG-1051 | evidence, workflow | `decision_pending/packet` | eligible | 1 |
| [EC-08](../tests/fixtures/eval_cases/EC-08_duplicate_report.json) | The same charge reported twice links to the existing case: one case, one claim, no second investigation | evidence, reliability | `investigating/draft` | blocked | 1 |
| [EC-09](../tests/fixtures/eval_cases/EC-09_stale_evidence_new_reply.json) | A reply with a receipt changes the evidence snapshot; policy is re-evaluated on the new snapshot and the old result is no longer current | evidence, financial_safety | `callback_pending/idv` | blocked | 1 |
| [EC-10](../tests/fixtures/eval_cases/EC-10_material_change_stale_checks.json) | A corrected delivery record (1 unit) appends version 2, supersedes the quantity conflict and marks the purchase-records check stale | evidence, reliability | `investigating/draft` | blocked | 0 |
| [EC-11](../tests/fixtures/eval_cases/EC-11_verification_push_approved.json) | Push verification approved by the cardholder: identity verified, the call is offered next | workflow, product_projection | `callback_pending/verify` | blocked | 2 |
| [EC-12](../tests/fixtures/eval_cases/EC-12_verification_push_declined.json) | Push verification declined: recorded as declined (not fraud), the call stays locked and a new request is offered | workflow, financial_safety | `callback_pending/idv` | blocked | 2 |
| [EC-13](../tests/fixtures/eval_cases/EC-13_otp_three_wrong_codes.json) | Three wrong one-time codes lock the request; a fourth attempt is refused, nothing is verified, and staff never see the code | financial_safety, reliability | `callback_pending/idv` | blocked | 2 |
| [EC-14](../tests/fixtures/eval_cases/EC-14_telephony_failure_retry.json) | Telephony provider fails once before dispatch: the worker retries the same key and places exactly one call | reliability, workflow | `decision_pending/packet` | needs_evidence | 0 |
| [EC-15](../tests/fixtures/eval_cases/EC-15_voice_busy_then_retry.json) | Voice provider reports the call failed (busy): case goes to call-failed, a second consented call succeeds | reliability, workflow, product_projection | `decision_pending/packet` | needs_evidence | 0 |
| [EC-16](../tests/fixtures/eval_cases/EC-16_contradicted_call.json) | The cardholder contradicts herself on the call: the call is recorded as failed, conflicts stay open and policy stays blocked | evidence, financial_safety | `callback_pending/callfail` | blocked | 2 |
| [EC-17](../tests/fixtures/eval_cases/EC-17_voicemail_then_retry.json) | Voicemail on the first call: recorded, attempt preserved; the retry reaches the cardholder and resolves the conflicts | workflow, reliability | `decision_pending/packet` | needs_evidence | 0 |
| [EC-18](../tests/fixtures/eval_cases/EC-18_duplicate_webhook.json) | The provider delivers the same signed transcript webhook twice: one transcript version, one recorded result | reliability, product_projection | `decision_pending/packet` | needs_evidence | 0 |
| [EC-19](../tests/fixtures/eval_cases/EC-19_delayed_webhook.json) | A transcript webhook that arrives after the call timed out is recorded as stale and changes nothing | reliability, workflow | `callback_pending/callfail` | blocked | 1 |
| [EC-20](../tests/fixtures/eval_cases/EC-20_out_of_order_webhooks.json) | A failure event arriving after the transcript, and an event for an unknown call, never rewind or corrupt the case | reliability, product_projection | `decision_pending/packet` | needs_evidence | 0 |
| [EC-21](../tests/fixtures/eval_cases/EC-21_worker_timeout.json) | A worker claims the investigation job and dies: the job is reclaimed only after the visibility timeout and runs once | reliability, workflow | `investigating/draft` | blocked | 0 |
| [EC-22](../tests/fixtures/eval_cases/EC-22_worker_crash_resume.json) | The worker crashes after two specialists finished: the checkpointed graph resumes at the receipt review and repeats nothing | reliability, workflow | `investigating/draft` | blocked | 0 |
| [EC-23](../tests/fixtures/eval_cases/EC-23_ungrounded_output_rejected.json) | A specialist cites a value that is not in the evidence: the output is rejected, nothing is stored, and a replay retry recovers | evidence, workflow | `investigating/draft` | blocked | 0 |
| [EC-24](../tests/fixtures/eval_cases/EC-24_scope_violation_rejected.json) | A specialist tries to read the cardholder's phone number, outside its scope: recorded as a scope violation, nothing stored | evidence, financial_safety | `investigating/working` | not evaluated | 1 |
| [EC-25](../tests/fixtures/eval_cases/EC-25_stale_approval_after_approval.json) | Demo: the reviewer approved a $2,840 credit, then the delivery record changed. Vera refuses the old approval, explains why, and issues the credit once after re-evaluation and fresh approval | financial_safety, workflow, reliability | `dispute_prepared/dsp_prepare` | eligible | 3 |
| [EC-26](../tests/fixtures/eval_cases/EC-26_stale_approval_before_review.json) | Evidence changes while the approval request waits: the reviewer's approve is refused as stale and nothing moves money | financial_safety | `decision_pending/stale` | eligible | 3 |
| [EC-27](../tests/fixtures/eval_cases/EC-27_reviewer_returns_credit.json) | Reviewer rejects the credit decision with a reason: returned to the analyst, credit refused, packet kept | financial_safety, workflow | `decision_pending/returned` | eligible | 4 |
| [EC-28](../tests/fixtures/eval_cases/EC-28_credit_while_policy_blocked.json) | Packet prepared while a related charge still awaits review: policy needs evidence, so approval cannot be requested and credit cannot run | financial_safety | `decision_pending/decide` | needs_evidence | 4 |
| [EC-29](../tests/fixtures/eval_cases/EC-29_credit_adapter_fails_then_retry.json) | Credit adapter fails before dispatch: nothing is issued; the analyst's retry issues exactly one credit under the same key | reliability, financial_safety | `dispute_prepared/dsp_prepare` | eligible | 1 |
| [EC-30](../tests/fixtures/eval_cases/EC-30_credit_uncertain_reconcile.json) | Credit result lost in transit (uncertain): the case waits in credit check, re-issue is refused, lookup confirms one credit | reliability, financial_safety | `dispute_prepared/dsp_prepare` | eligible | 1 |
| [EC-31](../tests/fixtures/eval_cases/EC-31_dispute_uncertain_lookup.json) | Dispute submission result uncertain: resolved by lookup without resending the dispute | reliability, financial_safety | `credit_issued/controls` | eligible | 1 |
| [EC-32](../tests/fixtures/eval_cases/EC-32_controls_declined.json) | Card admin declines the proposed controls: nothing is applied and apply is refused; the dispute track continues | financial_safety, workflow | `dispute_prepared/dsp_prepare` | eligible | 2 |
| [EC-33](../tests/fixtures/eval_cases/EC-33_closure_with_incomplete_work.json) | Closing while the dispute, controls and final message are open is refused; the checklist names the open items | financial_safety, product_projection | `credit_issued/controls` | eligible | 4 |
| [EC-34](../tests/fixtures/eval_cases/EC-34_unresolved_outcome.json) | Investigation ends unresolved: no credit, no dispute, final message sent and the case closes | workflow, financial_safety | `closed/closed` | eligible | 2 |
| [EC-35](../tests/fixtures/eval_cases/EC-35_analyst_unauthorized.json) | Analyst tries reviewer and card-admin commands: every one is refused as role_forbidden and nothing is written | financial_safety | `reviewer_pending/waitrv` | eligible | 6 |
| [EC-36](../tests/fixtures/eval_cases/EC-36_cardholder_analyst_actions.json) | Cardholder tries analyst actions and staff reads: refused, and the cardholder sees no internal data | financial_safety, product_projection | `waiting_on_cardholder/waiting` | blocked | 6 |
| [EC-37](../tests/fixtures/eval_cases/EC-37_reviewer_card_admin_action.json) | Dana holds reviewer and card-admin roles: while acting as reviewer she cannot approve or apply card controls | financial_safety | `dispute_prepared/dsp_prepare` | eligible | 4 |
| [EC-38](../tests/fixtures/eval_cases/EC-38_approval_via_chat_refused.json) | Asking Vera in chat to approve the credit is refused with a pointer to the reviewer action; nothing is written | financial_safety, product_projection | `reviewer_pending/waitrv` | eligible | 0 |
| [EC-39](../tests/fixtures/eval_cases/EC-39_invalid_attachment_type.json) | An executable attached to the reply is rejected; the request stays open and nothing is stored | evidence, reliability | `waiting_on_cardholder/waiting` | blocked | 0 |
| [EC-40](../tests/fixtures/eval_cases/EC-40_oversized_attachment.json) | A 10 MB + 1 byte attachment is rejected by the schema; nothing is stored and the cardholder can still reply | evidence, reliability | `response_received/response` | blocked | 0 |
| [EC-41](../tests/fixtures/eval_cases/EC-41_duplicate_command.json) | The same command sent twice with the same key replays the first result; a different payload under that key is refused | reliability | `waiting_on_cardholder/waiting` | blocked | 0 |
| [EC-42](../tests/fixtures/eval_cases/EC-42_duplicate_credit_command.json) | Issue credit posted three times with the server key: one credit, one adapter call, later attempts replay | reliability, financial_safety | `dispute_prepared/dsp_prepare` | eligible | 0 |
| [EC-43](../tests/fixtures/eval_cases/EC-43_published_workflow_immutable.json) | A published workflow version cannot be edited through commands or directly in the database; the case stays pinned to v3 | reliability, financial_safety | `investigating/draft` | blocked | 0 |
| [EC-44](../tests/fixtures/eval_cases/EC-44_hold_resume_rederives.json) | Hold mid-investigation blocks money actions; resume re-derives the exact step from stored facts | product_projection, workflow | `decision_pending/decide` | eligible | 1 |
| [EC-45](../tests/fixtures/eval_cases/EC-45_telephony_permanent_failure.json) | Telephony keeps failing: after the worker's retries the call is recorded as incomplete, the case leaves 'in progress' and a new call is offered | reliability, workflow, product_projection | `callback_pending/callfail` | blocked | 1 |
| [EC-46](../tests/fixtures/eval_cases/EC-46_non_material_change_keeps_approval.json) | A non-material re-key of the purchase order appends a version but does not stale the approval: credit proceeds once | financial_safety, evidence | `dispute_prepared/dsp_prepare` | eligible | 1 |
| [EC-47](../tests/fixtures/eval_cases/EC-47_complete_review_cannot_close.json) | Reply reviewed as complete while purchase-record conflicts are open: no credit, decision recorded, but closure stays refused because only a verification call resolves conflicts | financial_safety, workflow | `remediation_pending/close` | blocked | 2 |
| [EC-48](../tests/fixtures/eval_cases/EC-48_late_conflict_invalidates_approval.json) | A specialist records a new conflict after the reviewer approved: the snapshot moves, the approval goes stale and the credit is refused | financial_safety, evidence, reliability | `decision_pending/stale` | blocked | 2 |

## Shared journeys

Cases reach a stage of the golden journey through fragments in [`evals/fragments/`](../evals/fragments):
`sNN_*` files are single stages and `gNN_*` files chain stages 01..NN from a fresh seed.

| Stage | Fragment | What it does |
|---|---|---|
| 01 | `s01_investigate` | Open CHG-1042 and run the three investigation specialists (replay) |
| 02 | `s02_follow_up` | Follow-up drafted by the specialist, then approved and sent by the analyst |
| 03 | `s03_reply` | Cardholder replies with a receipt; the Response Reviewer runs (replay) |
| 04 | `s04_review_reply` | Analyst reviews the reply as conflicting with the report; receipt accepted |
| 05 | `s05_identity` | One-time code sent and entered by the cardholder |
| 06 | `s06_call` | Approved questions, consented verification call, Live Verification Agent (replay) |
| 07 | `s07_packet` | Related charges ruled out, policy re-evaluated, decision packet prepared (replay) |
| 08 | `s08_request_approval` | Analyst records a credit decision and requests reviewer approval |
| 09 | `s09_approve` | Reviewer approves the decision bound to the current evidence snapshot |
| 10 | `s10_credit` | Provisional credit issued through the simulated credit adapter |
| 11 | `s11_dispute` | Dispute packet prepared (narrative specialist), opened, reviewed and submitted |
| 12 | `s12_controls` | Card controls proposed by the analyst, approved and applied by the card admin |
| 13 | `s13_close` | Final message drafted and sent; case closed into dispute monitoring |
