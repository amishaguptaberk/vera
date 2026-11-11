"""derive_step is total: one case per row of the state/step table, plus precedence."""

from datetime import UTC, datetime
from typing import Any

import pytest
from vera_domain.enums import CaseState as S
from vera_domain.enums import CaseStep as T
from vera_domain.facts import CaseFacts, Hold, derive_step

NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
HOLD = Hold(reason="waiting", next_owner_id="u2", held_by="u1", held_at=NOW)
RESP = {"investigation_run_status": "succeeded", "followup_status": "responded"}
CALL = {**RESP, "response_review": "conflicting", "identity_status": "verified"}
PACKET = {**CALL, "callback_status": "confirmed", "packet_status": "ready"}
APPROVED = {**PACKET, "decision": "credit", "approval_status": "approved"}
ISSUED = {**APPROVED, "credit_status": "issued"}
DONE = {**ISSUED, "controls_status": "applied", "dispute_status": "submitted"}

# (id, facts on top of an opened case, expected state, expected step)
ROWS: list[tuple[str, dict[str, Any], S, T]] = [
    ("row1-reported", {"opened_at": None}, S.REPORTED, T.INTAKE),
    ("opened", {}, S.INVESTIGATING, T.INTAKE),
    ("row2-run-started", {"investigation_run_status": "running"}, S.INVESTIGATING, T.WORKING),
    ("row2-run-failed", {"investigation_run_status": "failed"}, S.INVESTIGATING, T.WORKING),
    ("row3-run-complete", {"investigation_run_status": "succeeded"}, S.INVESTIGATING, T.DRAFT),
    ("row3-drafted", {"followup_status": "drafted"}, S.INVESTIGATING, T.DRAFT),
    ("row4-sent", {"followup_status": "sent"}, S.WAITING_ON_CARDHOLDER, T.WAITING),
    ("row4-reminded", {"followup_status": "reminded"}, S.WAITING_ON_CARDHOLDER, T.WAITING),
    ("row5-overdue", {"followup_status": "overdue"}, S.WAITING_ON_CARDHOLDER, T.NORESP1),
    (
        "row5-overdue-after-followup",
        {"followup_status": "overdue", "followups_sent": 1},
        S.WAITING_ON_CARDHOLDER,
        T.NORESP2,
    ),
    (
        "row6-unresolved",
        {"followup_status": "overdue", "followups_sent": 1, "decision": "unresolved"},
        S.REMEDIATION_PENDING,
        T.FINALPREP,
    ),
    ("row7-responded", RESP, S.RESPONSE_RECEIVED, T.RESPONSE),
    ("row8-conflict", {**RESP, "response_review": "conflicting"}, S.CALLBACK_PENDING, T.IDV),
    ("row8-incomplete", {**RESP, "response_review": "incomplete"}, S.CALLBACK_PENDING, T.IDV),
    ("row8-supported", {**RESP, "response_review": "complete"}, S.DECISION_PENDING, T.PACKET),
    ("row9-requested", {**CALL, "identity_status": "requested"}, S.CALLBACK_PENDING, T.IDV),
    ("row10-verified", CALL, S.CALLBACK_PENDING, T.VERIFY),
    ("row11-failed", {**CALL, "identity_status": "failed"}, S.CALLBACK_PENDING, T.IDV),
    ("row12-expired", {**CALL, "identity_status": "expired"}, S.CALLBACK_PENDING, T.IDV),
    ("row12-declined", {**CALL, "identity_status": "declined"}, S.CALLBACK_PENDING, T.IDV),
    ("row12-cancelled", {**CALL, "identity_status": "cancelled"}, S.CALLBACK_PENDING, T.IDV),
    ("row13-call", {**CALL, "callback_status": "in_progress"}, S.CALLBACK_PENDING, T.WORKING),
    ("row13-approved", {**CALL, "callback_status": "approved"}, S.CALLBACK_PENDING, T.WORKING),
    ("row14-confirmed", {**CALL, "callback_status": "confirmed"}, S.DECISION_PENDING, T.PACKET),
    ("row14-packet-ready", PACKET, S.DECISION_PENDING, T.DECIDE),
    (
        "row15-contradicted",
        {**CALL, "callback_status": "contradicted"},
        S.CALLBACK_PENDING,
        T.CALLFAIL,
    ),
    ("row15-no-answer", {**CALL, "callback_status": "no_answer"}, S.CALLBACK_PENDING, T.CALLFAIL),
    ("row15-voicemail", {**CALL, "callback_status": "voicemail"}, S.CALLBACK_PENDING, T.CALLFAIL),
    ("row15-incomplete", {**CALL, "callback_status": "incomplete"}, S.CALLBACK_PENDING, T.CALLFAIL),
    (
        "row16-requested",
        {**PACKET, "decision": "credit", "approval_status": "requested"},
        S.REVIEWER_PENDING,
        T.WAITRV,
    ),
    ("row17-clear", {**PACKET, "decision": "clear"}, S.REMEDIATION_PENDING, T.FINALPREP),
    ("row17-violation", {**PACKET, "decision": "violation"}, S.REMEDIATION_PENDING, T.FINALPREP),
    ("row17-dispute", {**PACKET, "decision": "dispute"}, S.DISPUTE_PREPARED, T.DSP_PREPARE),
    ("row18-approved", APPROVED, S.CREDIT_APPROVED, T.ISSUE),
    (
        "row19-returned",
        {**PACKET, "decision": "credit", "approval_status": "returned"},
        S.DECISION_PENDING,
        T.RETURNED,
    ),
    (
        "row20-stale",
        {**PACKET, "decision": "credit", "approval_status": "stale"},
        S.DECISION_PENDING,
        T.STALE,
    ),
    ("row21-issued-dispute-first", ISSUED, S.DISPUTE_PREPARED, T.DSP_PREPARE),
    (
        "row21-dispute-submitted-controls-none",
        {**ISSUED, "dispute_status": "submitted"},
        S.CREDIT_ISSUED,
        T.CTL_PREP,
    ),
    (
        "row23-uncertain-stale",
        {**PACKET, "approval_status": "stale", "credit_status": "uncertain"},
        S.CREDIT_APPROVED,
        T.CREDIT_CHECK,
    ),
    (
        "row23-uncertain-returned",
        {**PACKET, "approval_status": "returned", "credit_status": "uncertain"},
        S.CREDIT_APPROVED,
        T.CREDIT_CHECK,
    ),
    (
        "row23-uncertain-requested",
        {**PACKET, "approval_status": "requested", "credit_status": "uncertain"},
        S.CREDIT_APPROVED,
        T.CREDIT_CHECK,
    ),
    ("row21-plan-ready", {**ISSUED, "controls_status": "recommended"}, S.CREDIT_ISSUED, T.CONTROLS),
    ("row22-failed", {**APPROVED, "credit_status": "failed"}, S.CREDIT_APPROVED, T.ISSUE),
    (
        "row23-uncertain",
        {**APPROVED, "credit_status": "uncertain"},
        S.CREDIT_APPROVED,
        T.CREDIT_CHECK,
    ),
    (
        "row24-proposed",
        {**ISSUED, "controls_status": "proposed"},
        S.DISPUTE_PREPARED,
        T.DSP_PREPARE,
    ),
    ("row24-skipped", {**ISSUED, "controls_status": "skipped"}, S.DISPUTE_PREPARED, T.DSP_PREPARE),
    (
        "row25-prepared",
        {**ISSUED, "controls_status": "proposed", "dispute_status": "prepared"},
        S.DISPUTE_PREPARED,
        T.DSP_OPEN,
    ),
    (
        "row25-opened",
        {**ISSUED, "controls_status": "proposed", "dispute_status": "opened"},
        S.DISPUTE_PREPARED,
        T.DSP_REVIEW,
    ),
    (
        "row25-reviewed",
        {**ISSUED, "controls_status": "proposed", "dispute_status": "reviewed"},
        S.DISPUTE_PREPARED,
        T.DSP_SUBMIT,
    ),
    (
        "row25-failed",
        {**ISSUED, "controls_status": "proposed", "dispute_status": "failed"},
        S.DISPUTE_PREPARED,
        T.DSP_FAILED,
    ),
    (
        "row26-awaiting-card-admin",
        {**ISSUED, "controls_status": "proposed", "dispute_status": "submitted"},
        S.CREDIT_ISSUED,
        T.WAITCTL,
    ),
    (
        "row26-approved",
        {**ISSUED, "controls_status": "approved", "dispute_status": "submitted"},
        S.CREDIT_ISSUED,
        T.CTL_APPLY,
    ),
    (
        "row26-declined",
        {**ISSUED, "controls_status": "declined", "dispute_status": "submitted"},
        S.REMEDIATION_PENDING,
        T.FINALPREP,
    ),
    ("row27-applied", DONE, S.REMEDIATION_PENDING, T.FINALPREP),
    (
        "row27-applied-dispute-open",
        {**ISSUED, "controls_status": "applied", "dispute_status": "opened"},
        S.DISPUTE_PREPARED,
        T.DSP_REVIEW,
    ),
    ("row28-drafted", {**DONE, "final_message_status": "drafted"}, S.REMEDIATION_PENDING, T.FINAL),
    ("row28-sent", {**DONE, "final_message_status": "sent"}, S.REMEDIATION_PENDING, T.CLOSE),
    (
        "row29-monitoring",
        {**DONE, "final_message_status": "sent", "monitoring": True},
        S.MONITORING,
        T.MONITORING,
    ),
    ("row30-closed", {**DONE, "final_message_status": "sent", "closed": True}, S.CLOSED, T.CLOSED),
    ("row31-held", {**PACKET, "hold": HOLD}, S.HELD, T.ONHOLD),
]


def facts(extra: dict[str, Any]) -> CaseFacts:
    return CaseFacts.model_validate({"opened_at": NOW, "owner_id": "u1", **extra})


@pytest.mark.parametrize(("extra", "state", "step"), [pytest.param(*r[1:], id=r[0]) for r in ROWS])
def test_transition_table_row(extra: dict[str, Any], state: S, step: T) -> None:
    assert derive_step(facts(extra)) == (state, step)


def test_every_case_step_is_reachable_from_a_tested_fact_set() -> None:
    assert {r[3] for r in ROWS} == set(T)


def test_closed_beats_monitoring_beats_hold() -> None:
    assert (
        derive_step(facts({**DONE, "closed": True, "monitoring": True, "hold": HOLD}))[1]
        == T.CLOSED
    )
    assert derive_step(facts({**DONE, "monitoring": True, "hold": HOLD}))[1] == T.MONITORING
    assert derive_step(facts({**DONE, "final_message_status": "sent", "hold": HOLD}))[1] == T.ONHOLD


def test_hold_restores_the_step_underneath() -> None:
    held = facts({**APPROVED, "hold": HOLD})
    assert derive_step(held)[1] == T.ONHOLD
    assert derive_step(held.model_copy(update={"hold": None}))[1] == T.ISSUE


def test_later_stage_beats_earlier_stage() -> None:
    # A stale approval beats a ready packet; an issued credit beats the approval's status.
    assert derive_step(facts({**PACKET, "approval_status": "stale"}))[1] == T.STALE
    assert derive_step(facts({**ISSUED, "approval_status": "stale"}))[1] == T.DSP_PREPARE
    # A failed callback beats the verified identity; a verified identity beats the review.
    assert derive_step(facts({**CALL, "callback_status": "no_answer"}))[1] == T.CALLFAIL
    # An unopened case stays reported whatever else is stored.
    assert derive_step(facts({**DONE, "opened_at": None})) == (S.REPORTED, T.INTAKE)


def test_defaults_keep_todays_behaviour() -> None:
    assert derive_step(CaseFacts(owner_id="u1")) == (S.REPORTED, T.INTAKE)
    assert derive_step(CaseFacts(owner_id="u1", opened_at=NOW)) == (S.INVESTIGATING, T.INTAKE)
