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
    """Inputs to derive_step. A hold stores inputs, never a saved (state, step)."""

    opened_at: datetime | None = None
    closed: bool = False
    hold: Hold | None = None
    owner_id: str
    due_at: datetime | None = None
    # Status of the case's latest investigation run, read from workflow_runs (never model text).
    investigation_run_status: Literal["none", "running", "failed", "succeeded"] = "none"


def derive_step(facts: CaseFacts) -> tuple[CaseState, CaseStep]:
    """The ONLY source of state/step."""
    if facts.closed:
        return CaseState.CLOSED, CaseStep.CLOSED
    if facts.hold is not None:
        return CaseState.HELD, CaseStep.ONHOLD
    if facts.opened_at is not None:
        status = facts.investigation_run_status
        if status in ("running", "failed"):  # a failed step keeps the case in its step
            return CaseState.INVESTIGATING, CaseStep.WORKING
        if status == "succeeded":  # Handoff 4.2 row 3: run complete -> draft
            return CaseState.INVESTIGATING, CaseStep.DRAFT
        return CaseState.INVESTIGATING, CaseStep.INTAKE
    return CaseState.REPORTED, CaseStep.INTAKE
