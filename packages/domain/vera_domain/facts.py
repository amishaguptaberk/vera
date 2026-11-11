"""Case facts and the single derivation of (state, step)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from vera_domain.enums import CaseState, CaseStep


class Hold(BaseModel):
    reason: str
    next_owner_id: str
    due_at: datetime | None = None
    held_by: str
    held_at: datetime


class CaseFacts(BaseModel, frozen=True):
    """Inputs to derive_step. A hold stores inputs, never a saved (state, step).

    Every field is read from STORED ROWS by a fact provider (gateway.FACT_PROVIDERS), never from
    model text. Each describes the CURRENT cycle: a provider reports a superseded row (an old
    callback after a newer follow-up, an approval replaced by a new packet) as "none".
    """

    opened_at: datetime | None = None
    closed: bool = False
    hold: Hold | None = None
    owner_id: str
    due_at: datetime | None = None
    # Status of the case's latest investigation run, read from workflow_runs (never model text).
    investigation_run_status: Literal["none", "running", "failed", "succeeded"] = "none"
    # Cardholder request: drafted = draft stored; sent/reminded = waiting on reply;
    # overdue = reply deadline passed; responded = cardholder reply stored.
    followup_status: Literal["none", "drafted", "sent", "reminded", "overdue", "responded"] = "none"
    # Follow-up requests sent after the first request (0 -> noresp1 when overdue, >=1 -> noresp2).
    followups_sent: int = 0
    # Analyst review of the stored reply: complete = supported; incomplete/conflicting -> identity.
    response_review: Literal["none", "complete", "incomplete", "conflicting"] = "none"
    # Identity verification request. Only "verified" unlocks the callback.
    identity_status: Literal[
        "none", "requested", "verified", "failed", "expired", "declined", "cancelled"
    ] = "none"
    # Verification callback: approved/in_progress = call running; confirmed = resolved;
    # contradicted/voicemail/no_answer/incomplete = failed attempt (callfail).
    callback_status: Literal[
        "none",
        "approved",
        "in_progress",
        "confirmed",
        "contradicted",
        "voicemail",
        "no_answer",
        "incomplete",
    ] = "none"
    # Callback attempts started (at most 2; start_callback is offered while < 2).
    callback_attempts: int = 0
    # Decision packet: draft = being prepared (packet); ready = current (decide).
    packet_status: Literal["none", "draft", "ready"] = "none"
    # Recorded decision. credit = credit path with reviewer approval;
    # dispute = dispute without credit; clear/violation/unresolved go straight to the final update.
    decision: Literal["none", "credit", "dispute", "clear", "violation", "unresolved"] = "none"
    # Reviewer approval of the current packet.
    approval_status: Literal["none", "requested", "approved", "returned", "stale"] = "none"
    # Provisional credit execution: uncertain = adapter result being checked.
    credit_status: Literal["none", "requested", "uncertain", "issued", "failed"] = "none"
    # Dispute track.
    dispute_status: Literal["none", "prepared", "opened", "reviewed", "submitted", "failed"] = (
        "none"
    )
    # Card-control track: recommended = plan prepared, not sent; proposed = sent to the
    # card admin (awaiting approval); skipped/declined/applied end the track.
    controls_status: Literal[
        "none", "recommended", "proposed", "skipped", "approved", "declined", "applied"
    ] = "none"
    # Final cardholder update.
    final_message_status: Literal["none", "drafted", "sent"] = "none"
    # close_case ran while the dispute outcome is pending.
    monitoring: bool = False


_CALL_FAILED = ("contradicted", "voicemail", "no_answer", "incomplete")
_DISPUTE_STEP: dict[str, CaseStep] = {
    "none": CaseStep.DSP_PREPARE,
    "prepared": CaseStep.DSP_OPEN,
    "opened": CaseStep.DSP_REVIEW,
    "reviewed": CaseStep.DSP_SUBMIT,
    "failed": CaseStep.DSP_FAILED,
}


def _tracks(f: CaseFacts) -> tuple[CaseState, CaseStep] | None:
    """Rows 21, 24-27: the dispute and card-control tracks after the credit / dispute decision.

    Same focus as the prototype's `tracks()`: a control plan that is already recommended is sent
    first (controls); otherwise the dispute is worked to submission (dsp_*, starting at
    dsp_prepare); only then the control track: none -> ctl_prep, proposed -> waitctl, approved ->
    ctl_apply (the card admin applies; the analyst's copy for that step is "Waiting on card admin
    to apply controls"). None = both tracks are finished (finalprep).
    """
    ctl_state = (
        CaseState.CREDIT_ISSUED if f.credit_status == "issued" else CaseState.DISPUTE_PREPARED
    )
    if f.controls_status == "recommended":
        return ctl_state, CaseStep.CONTROLS
    if f.dispute_status != "submitted":
        return CaseState.DISPUTE_PREPARED, _DISPUTE_STEP[f.dispute_status]
    if f.controls_status == "none":
        return ctl_state, CaseStep.CTL_PREP
    if f.controls_status == "proposed":
        return ctl_state, CaseStep.WAITCTL
    if f.controls_status == "approved":
        return ctl_state, CaseStep.CTL_APPLY
    return None


def _pre_decision(f: CaseFacts) -> tuple[CaseState, CaseStep]:
    """Rows 2-15: investigation, cardholder request, identity, callback, packet."""
    if f.packet_status == "ready":
        return CaseState.DECISION_PENDING, CaseStep.DECIDE
    if f.packet_status == "draft" or f.callback_status == "confirmed":
        return CaseState.DECISION_PENDING, CaseStep.PACKET
    if f.callback_status in ("approved", "in_progress"):
        return CaseState.CALLBACK_PENDING, CaseStep.WORKING
    if f.callback_status in _CALL_FAILED:
        return CaseState.CALLBACK_PENDING, CaseStep.CALLFAIL
    if f.identity_status == "verified":
        return CaseState.CALLBACK_PENDING, CaseStep.VERIFY
    if f.identity_status != "none":
        return CaseState.CALLBACK_PENDING, CaseStep.IDV
    if f.response_review == "complete":
        return CaseState.DECISION_PENDING, CaseStep.PACKET
    if f.response_review in ("incomplete", "conflicting"):
        return CaseState.CALLBACK_PENDING, CaseStep.IDV
    if f.followup_status == "responded":
        return CaseState.RESPONSE_RECEIVED, CaseStep.RESPONSE
    if f.followup_status == "overdue":
        step = CaseStep.NORESP2 if f.followups_sent >= 1 else CaseStep.NORESP1
        return CaseState.WAITING_ON_CARDHOLDER, step
    if f.followup_status in ("sent", "reminded"):
        return CaseState.WAITING_ON_CARDHOLDER, CaseStep.WAITING
    status = f.investigation_run_status
    if status in ("running", "failed"):  # a failed step keeps the case in its step
        return CaseState.INVESTIGATING, CaseStep.WORKING
    if status == "succeeded" or f.followup_status == "drafted":  # row 3: run complete -> draft
        return CaseState.INVESTIGATING, CaseStep.DRAFT
    return CaseState.INVESTIGATING, CaseStep.INTAKE


def derive_step(facts: CaseFacts) -> tuple[CaseState, CaseStep]:
    """The ONLY source of state/step. Total; the latest stage reached wins.

    Precedence: closed > monitoring > hold > not opened > final update (close, final) >
    no-credit decision (finalprep) > credit/dispute tracks > unconfirmed credit (credit_check) >
    approval (stale, returned, waitrv, issue) > packet > callback > identity > response review >
    cardholder request > investigation.
    """
    f = facts
    if f.closed:
        return CaseState.CLOSED, CaseStep.CLOSED
    if f.monitoring:
        return CaseState.MONITORING, CaseStep.MONITORING
    if f.hold is not None:
        return CaseState.HELD, CaseStep.ONHOLD
    if f.opened_at is None:
        return CaseState.REPORTED, CaseStep.INTAKE
    if f.final_message_status == "sent":  # row 28
        return CaseState.REMEDIATION_PENDING, CaseStep.CLOSE
    if f.final_message_status == "drafted":
        return CaseState.REMEDIATION_PENDING, CaseStep.FINAL
    if f.decision in ("clear", "violation", "unresolved"):  # rows 6, 17
        return CaseState.REMEDIATION_PENDING, CaseStep.FINALPREP
    if f.decision == "dispute" or f.credit_status == "issued":  # rows 17, 21, 24-27
        return _tracks(f) or (CaseState.REMEDIATION_PENDING, CaseStep.FINALPREP)
    if f.credit_status == "uncertain":  # row 23: an unconfirmed credit result outranks approval
        return CaseState.CREDIT_APPROVED, CaseStep.CREDIT_CHECK
    if f.approval_status == "stale":  # row 20
        return CaseState.DECISION_PENDING, CaseStep.STALE
    if f.approval_status == "returned":  # row 19
        return CaseState.DECISION_PENDING, CaseStep.RETURNED
    if f.approval_status == "requested":  # row 16
        return CaseState.REVIEWER_PENDING, CaseStep.WAITRV
    if f.approval_status == "approved":  # rows 18, 22, 23
        return CaseState.CREDIT_APPROVED, CaseStep.ISSUE
    return _pre_decision(f)
