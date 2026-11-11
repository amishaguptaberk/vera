from collections.abc import Mapping
from typing import Any, Literal

from vera_domain.enums import CaseState, CaseStep, StateKind

# (state, step) -> (state_label, state_kind, next_action). Grows with later tickets.
_LABELS: dict[tuple[CaseState, CaseStep], tuple[str, StateKind, str]] = {
    (CaseState.REPORTED, CaseStep.INTAKE): (
        "New report",
        StateKind.IDLE,
        "Open the case and start the investigation",
    ),
    (CaseState.INVESTIGATING, CaseStep.INTAKE): (
        "Needs investigation",
        StateKind.WORKING,
        "Start the investigation",
    ),
    (CaseState.INVESTIGATING, CaseStep.WORKING): (
        "Investigating",
        StateKind.WORKING,
        "Specialists are reviewing the charge",
    ),
    (CaseState.INVESTIGATING, CaseStep.DRAFT): (
        "Investigation complete",
        StateKind.REVIEW,
        "Review the findings and draft the cardholder request",
    ),
    (CaseState.HELD, CaseStep.ONHOLD): (
        "On hold",
        StateKind.WAITING,
        "Resume when the next owner is ready",
    ),
}


def describe(state: CaseState, step: CaseStep) -> tuple[str, StateKind, str]:
    found = _LABELS.get((state, step))
    if found:
        return found
    return (state.value.replace("_", " ").capitalize(), StateKind.IDLE, "Review the case")


# --- VER-016: queue and activity display labels (spec prototype tables) ---

# step -> what is blocking the case (prototype `BLK`).
BLOCKER_BY_STEP: dict[CaseStep, str] = {
    CaseStep.INTAKE: "Not investigated",
    CaseStep.DRAFT: "Request not sent",
    CaseStep.WAITING: "Reply pending",
    CaseStep.NORESP1: "Reply overdue",
    CaseStep.NORESP2: "Reply overdue",
    CaseStep.RESPONSE: "Reply not reviewed",
    CaseStep.IDV: "Identity not verified",
    CaseStep.VERIFY: "Evidence conflict",
    CaseStep.CALLFAIL: "Callback unanswered",
    CaseStep.PACKET: "Decision needed",
    CaseStep.DECIDE: "Decision needed",
    CaseStep.RETURNED: "Returned by reviewer",
    CaseStep.WAITRV: "Reviewer approval",
    CaseStep.STALE: "Approval out of date",
    CaseStep.ISSUE: "Credit not issued",
    CaseStep.CREDIT_CHECK: "Credit result unconfirmed",
    CaseStep.CONTROLS: "Control plan not sent",
    CaseStep.CTL_PREP: "Controls not prepared",
    CaseStep.DSP_PREPARE: "Dispute not prepared",
    CaseStep.DSP_OPEN: "Dispute not reviewed",
    CaseStep.DSP_REVIEW: "Dispute not reviewed",
    CaseStep.DSP_SUBMIT: "Dispute not submitted",
    CaseStep.DSP_FAILED: "Submission failed",
    CaseStep.WAITCTL: "Control approval",
    CaseStep.CTL_APPLY: "Controls not applied",
    CaseStep.FINALPREP: "Final update not sent",
    CaseStep.FINAL: "Final update not sent",
    CaseStep.MONITORING: "Dispute outcome",
    CaseStep.ONHOLD: "On hold",
}

# step -> the party the step waits on (prototype `PHASE[step][2]`); the queue filter chips.
WaitKind = Literal["cardholder", "reviewer"]
WAIT_KIND_BY_STEP: dict[CaseStep, WaitKind] = {
    CaseStep.WAITING: "cardholder",
    CaseStep.NORESP1: "cardholder",
    CaseStep.NORESP2: "cardholder",
    CaseStep.WAITRV: "reviewer",
    CaseStep.WAITCTL: "reviewer",
}

# audit event type -> human sentence for the activity feed. Covers every EventType and
# RunEventType value (a unit test enumerates the enums).
EVENT_SUMMARIES: dict[str, str] = {
    "report.received": "Report received from the cardholder",
    "case.created": "Case created",
    "report.linked": "Report linked to the case",
    "case.opened": "Case opened",
    "case.held": "Case put on hold",
    "case.resumed": "Case resumed",
    "case.reassigned": "Case reassigned",
    "evidence.linked": "Evidence linked",
    "evidence.version_added": "New evidence version added",
    "claim.recorded": "Claim recorded",
    "finding.recorded": "Finding recorded",
    "finding.stale": "Finding marked out of date",
    "approval.stale": "Approval marked out of date",
    "policy.evaluated": "Policy evaluated",
    "investigation.started": "Investigation started",
    "investigation.completed": "Investigation complete",
    "specialist.retried": "Specialist step retried",
    "specialist.failed": "Specialist step failed",
    "specialist.replayed": "Replayed result (recorded reference output)",
    "run.step_started": "Specialist step started",
    "run.step_succeeded": "Specialist step finished",
    "run.step_failed": "Specialist step failed",
    "adapter.succeeded": "External action completed",
    "adapter.failed": "External action failed before taking effect",
    "adapter.uncertain": "External action result is being checked",
}


def _register(table: dict[Any, Any], entries: Mapping[Any, Any], what: str) -> None:
    for key, value in entries.items():
        if key in table and table[key] != value:
            raise ValueError(f"{what} '{key}' is already registered")
        table[key] = value


def register_event_summaries(entries: Mapping[str, str]) -> None:
    """Activity-feed sentence per event type. A feature module calls this at import."""
    _register(EVENT_SUMMARIES, entries, "event summary")


def register_blockers(entries: Mapping[CaseStep, str]) -> None:
    _register(BLOCKER_BY_STEP, entries, "blocker")


def register_wait_kinds(entries: Mapping[CaseStep, WaitKind]) -> None:
    _register(WAIT_KIND_BY_STEP, entries, "wait kind")


def register_labels(
    entries: Mapping[tuple[CaseState, CaseStep], tuple[str, StateKind, str]],
) -> None:
    """(state, step) -> (state_label, state_kind, next_action)."""
    _register(_LABELS, entries, "state label")


def event_summary(event_type: str) -> str:
    """Label for an event type. Types appended later (`x.y`) read as "X y" until labelled."""
    found = EVENT_SUMMARIES.get(event_type)
    if found:
        return found
    subject, dot, verb = event_type.partition(".")
    if dot and subject and verb:
        return f"{subject.replace('_', ' ').capitalize()} {verb.replace('_', ' ')}"
    return event_type
