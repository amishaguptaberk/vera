# Evaluation fixtures

Fixtures 1-24 are ToSpec section 15; 25-46 are Handoff section 10.7. Scenario files are data under `evals/scenarios/`;
the runner reports `pending` scenarios as SKIPPED with the ticket that will implement them, never as passed.
Run: `uv run python -m evals.harness [--only NN]`.

| # | Title | Scenario file | Status |
|---|---|---|---|
| 1 | Recognized charge with receipt | `evals/scenarios/01_recognized_charge_with_receipt.json` | pending (VER-005) |
| 2 | Unrecognized charge with missing receipt: receipt missing, policy needs evidence | `evals/scenarios/02_unrecognized_charge_missing_receipt.json` | implemented |
| 3 | Cardholder no response | `evals/scenarios/03_cardholder_no_response.json` | pending (VER-005) |
| 4 | Incomplete response | `evals/scenarios/04_incomplete_response.json` | pending (VER-005) |
| 5 | Conflicting cardholder statements | `evals/scenarios/05_conflicting_cardholder_statements.json` | pending (VER-005) |
| 6 | Contradictory purchase order / delivery record opens a conflict and blocks policy | `evals/scenarios/06_contradictory_documents.json` | implemented |
| 7 | Related transaction is a finding on CHG-1051 and never changes the primary case | `evals/scenarios/07_related_transaction.json` | implemented |
| 8 | Callback confirmed | `evals/scenarios/08_callback_confirmed.json` | pending (VER-007) |
| 9 | Callback unanswered | `evals/scenarios/09_callback_unanswered.json` | pending (VER-007) |
| 10 | Callback retry | `evals/scenarios/10_callback_retry.json` | pending (VER-007) |
| 11 | Reviewer approval | `evals/scenarios/11_reviewer_approval.json` | pending (VER-009) |
| 12 | Reviewer return without note | `evals/scenarios/12_reviewer_return_without_note.json` | pending (VER-009) |
| 13 | Reviewer return with note | `evals/scenarios/13_reviewer_return_with_note.json` | pending (VER-009) |
| 14 | Material evidence change after approval | `evals/scenarios/14_material_evidence_change_after_approval.json` | pending (VER-009) |
| 15 | Amount/merchant change after approval | `evals/scenarios/15_amount_merchant_change_after_approval.json` | pending (VER-009) |
| 16 | Duplicate credit request | `evals/scenarios/16_duplicate_credit_request.json` | pending (VER-010) |
| 17 | Uncertain credit adapter result | `evals/scenarios/17_uncertain_credit_adapter_result.json` | pending (VER-010) |
| 18 | Repeated communication | `evals/scenarios/18_repeated_communication.json` | pending (VER-005) |
| 19 | A change to a record the case does not hold is rejected and changes nothing | `evals/scenarios/19_unsupported_source_record_change.json` | implemented |
| 20 | Actions on a closed case are rejected with a reason and write nothing | `evals/scenarios/20_closed_case_action.json` | implemented |
| 21 | Message text claiming policy is satisfied does not change the stored policy result | `evals/scenarios/21_policy_bypass_attempt.json` | implemented |
| 22 | The run and the case stay pinned to workflow v3 / policy v1 | `evals/scenarios/22_workflow_version_pinning.json` | implemented (pinning only; publish-time immutability needs VER-014) |
| 23 | Card control recommendation and approval | `evals/scenarios/23_card_control_recommendation_and_approval.json` | pending (VER-010) |
| 24 | Final communication and closure | `evals/scenarios/24_final_communication_and_closure.json` | pending (VER-011) |
| 25 | Identity: push approved | `evals/scenarios/25_identity_push_approved.json` | pending (VER-006) |
| 26 | Identity: wrong code x3 (entered by cardholder) | `evals/scenarios/26_identity_wrong_code_x3_entered_by_cardho.json` | pending (VER-006) |
| 27 | Identity: expiry + resend | `evals/scenarios/27_identity_expiry_resend.json` | pending (VER-006) |
| 28 | Identity: push denied | `evals/scenarios/28_identity_push_denied.json` | pending (VER-006) |
| 29 | Call before identity | `evals/scenarios/29_call_before_identity.json` | pending (VER-007) |
| 30 | Phone number in chat | `evals/scenarios/30_phone_number_in_chat.json` | pending (VER-012-F9) |
| 31 | Reviewer chat approval attempt | `evals/scenarios/31_reviewer_chat_approval_attempt.json` | pending (VER-012-F9) |
| 32 | Repeated 'Can we close?' | `evals/scenarios/32_repeated_can_we_close.json` | pending (VER-012-F9) |
| 33 | Dispute status sequence | `evals/scenarios/33_dispute_status_sequence.json` | pending (VER-010) |
| 34 | Dispute submission failure + retry | `evals/scenarios/34_dispute_submission_failure_retry.json` | pending (VER-010) |
| 35 | Control approve vs apply | `evals/scenarios/35_control_approve_vs_apply.json` | pending (VER-010) |
| 36 | Credit-issued case | `evals/scenarios/36_credit_issued_case.json` | pending (VER-010) |
| 37 | Role switching writes no command, no event and keeps the same case_version | `evals/scenarios/37_role_switching.json` | implemented |
| 38 | A worker crash mid-run resumes: same step, no duplicate steps or findings | `evals/scenarios/38_refresh_mid_run.json` | implemented |
| 39 | Specialist draft -> workflow | `evals/scenarios/39_specialist_draft_workflow.json` | pending (VER-014) |
| 40 | Required control removal | `evals/scenarios/40_required_control_removal.json` | pending (VER-014) |
| 41 | Workflow publish gates | `evals/scenarios/41_workflow_publish_gates.json` | pending (VER-014) |
| 42 | D8 analyst never sees the code | `evals/scenarios/42_d8_analyst_never_sees_the_code.json` | pending (VER-006) |
| 43 | D8 cardholder completes verification | `evals/scenarios/43_d8_cardholder_completes_verification.json` | pending (VER-006) |
| 44 | D3 parallel tracks | `evals/scenarios/44_d3_parallel_tracks.json` | pending (VER-010) |
| 45 | D2 audit role separation | `evals/scenarios/45_d2_audit_role_separation.json` | pending (VER-010) |
| 46 | D4 node kinds | `evals/scenarios/46_d4_node_kinds.json` | pending (VER-014) |

Totals: 9 implemented, 37 pending of 46.

## Additional scenarios (backend capabilities not numbered as fixtures)

| Scenario file | What it asserts |
|---|---|
| `evals/scenarios/51_hold_and_resume.json` | Hold and resume: transitions and events (VER-002 first fixture) |
| `evals/scenarios/52_cases_queue.json` | Cases queue is staff-readable and totals match the seed |
| `evals/scenarios/53_duplicate_report.json` | Duplicate report links to the case, adds one claim, no second case |
| `evals/scenarios/54_role_forbidden.json` | A role without the command gets 403 and nothing is written |
| `evals/scenarios/55_stale_version.json` | A stale expected_case_version is rejected and nothing is written |
| `evals/scenarios/56_command_replay.json` | The same key replays: one effect, attempts counted |
| `evals/scenarios/58_evidence_register.json` | Evidence register on the seed: source records, statuses, no findings |
| `evals/scenarios/59_material_change.json` | Material change appends a version, supersedes the old one, stales the matching check |
| `evals/scenarios/60_findings_need_citations.json` | Findings must cite a record version and field |
| `evals/scenarios/61_specialist_cannot_mutate_source.json` | Source records cannot be mutated by humans or specialists |
| `evals/scenarios/62_investigation_replay.json` | Investigation runs in REPLAY: grounded findings, draft step, policy evaluated after specialists |
| `evals/scenarios/63_ungrounded_output_fails_then_retry.json` | Ungrounded specialist output fails the step; replay retry resumes |
| `evals/scenarios/64_scope_violation.json` | A tool call outside the specialist's scope is a recorded scope violation |
| `evals/scenarios/65_live_failure_not_replaced.json` | A LIVE failure stays failed until an explicit replay retry |
| `evals/scenarios/66_missing_recording.json` | A missing REPLAY recording is an explicit error, never a silent pass |
| `evals/scenarios/68_policy_matrix.json` | Policy result follows persisted evidence: needs evidence, then blocked by an open conflict |
| `evals/scenarios/70_policy_reevaluated_on_evidence_change.json` | Evidence change re-evaluates policy with a new snapshot |
| `evals/scenarios/71_exposure_gross_net.json` | Exposure: gross, temporary credit and net on the seed; finalizing credit reduces net |
| `evals/scenarios/72_staff_only_reads.json` | Queue, summary, evidence and users are staff-only |
| `evals/scenarios/73_two_session_cookies.json` | Two session cookies resolve to no session (default analyst), never a privilege |
