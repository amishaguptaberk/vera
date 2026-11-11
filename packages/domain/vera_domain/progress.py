"""Workflow progress steps for display only (spec prototype `SD` and `PHASE[step][3]`).

Pure: takes the stored step and facts, returns labels. It never sets state or step.
"""

from typing import Literal

from pydantic import BaseModel

from vera_domain.enums import CaseStep

StepStatus = Literal["done", "current", "upcoming", "blocked"]

PROGRESS: tuple[tuple[str, str], ...] = (
    ("report_received", "Report received"),
    ("investigate", "Investigate"),
    ("request_info", "Request info"),
    ("review_response", "Review response"),
    ("verify", "Verify"),
    ("prepare_decision", "Prepare decision"),
    ("reviewer_decision", "Reviewer decision"),
    ("credit_dispute", "Credit & dispute"),
    ("card_controls", "Card controls"),
    ("final_followup", "Final follow-up"),
    ("close_or_monitor", "Close or monitor"),
)

# CaseStep -> 1-based position in PROGRESS. ONHOLD and CLOSED are handled separately.
_POSITION: dict[CaseStep, int] = {
    CaseStep.INTAKE: 2,
    CaseStep.WORKING: 2,
    CaseStep.DRAFT: 3,
    CaseStep.WAITING: 3,
    CaseStep.NORESP1: 3,
    CaseStep.NORESP2: 6,
    CaseStep.RESPONSE: 4,
    CaseStep.IDV: 5,
    CaseStep.VERIFY: 5,
    CaseStep.CALLFAIL: 5,
    CaseStep.PACKET: 6,
    CaseStep.DECIDE: 6,
    CaseStep.RETURNED: 6,
    CaseStep.WAITRV: 7,
    CaseStep.STALE: 7,
    CaseStep.ISSUE: 8,
    CaseStep.CREDIT_CHECK: 8,
    CaseStep.DSP_PREPARE: 8,
    CaseStep.DSP_OPEN: 8,
    CaseStep.DSP_REVIEW: 8,
    CaseStep.DSP_SUBMIT: 8,
    CaseStep.DSP_FAILED: 8,
    CaseStep.CONTROLS: 9,
    CaseStep.CTL_PREP: 9,
    CaseStep.WAITCTL: 9,
    CaseStep.CTL_APPLY: 9,
    CaseStep.FINALPREP: 10,
    CaseStep.FINAL: 10,
    CaseStep.CLOSE: 11,
    CaseStep.MONITORING: 11,
}


class ProgressStep(BaseModel):
    key: str
    label: str
    status: StepStatus


def progress_steps(
    step: CaseStep, *, held_step: CaseStep | None = None, run_failed: bool = False
) -> list[ProgressStep]:
    """`held_step` is the step the case derives to without its hold (used when ONHOLD)."""
    if step == CaseStep.CLOSED:
        return [ProgressStep(key=k, label=lbl, status="done") for k, lbl in PROGRESS]
    held = step == CaseStep.ONHOLD
    base = (held_step or CaseStep.INTAKE) if held else step
    current = _POSITION.get(base, 1)
    blocked = held or run_failed

    def status(n: int) -> StepStatus:
        if n < current:
            return "done"
        if n > current:
            return "upcoming"
        return "blocked" if blocked else "current"

    return [
        ProgressStep(key=k, label=lbl, status=status(n))
        for n, (k, lbl) in enumerate(PROGRESS, start=1)
    ]
