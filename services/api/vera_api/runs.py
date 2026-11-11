"""GET /api/cases/{id}/runs: runs with their specialist steps."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from vera_domain.errors import CommandError

from vera_api.models import Case
from vera_api.models_runs import WorkflowRun, WorkflowStep

router = APIRouter(prefix="/api")


class StepOut(BaseModel):
    step_key: str
    specialist: str
    status: str
    execution_mode: str | None
    model_id: str | None
    prompt_version: str | None
    usage: dict[str, Any]
    attempts: int
    failure_reason: str | None
    started_at: datetime | None
    finished_at: datetime | None
    # True when this step's result came from a recording on a LIVE run: an explicit
    # retry_specialist_step {mode: "replay"}, shown as "Replayed result", never as live.
    replayed: bool = False


class RunOut(BaseModel):
    id: str
    case_id: str
    workflow_version: int
    policy_version: int
    status: str
    mode: str
    created_at: datetime
    steps: list[StepOut]


@router.get("/cases/{case_id}/runs")
def list_runs(case_id: str, request: Request) -> list[RunOut]:
    with request.app.state.session_factory() as session:
        if session.get(Case, case_id) is None:
            raise CommandError("case_not_found", 404, "No such case.")
        runs = session.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.case_id == case_id)
            .order_by(WorkflowRun.created_at)
        ).all()
        out: list[RunOut] = []
        for run in runs:
            steps = session.scalars(
                select(WorkflowStep)
                .where(WorkflowStep.run_id == run.id)
                .order_by(WorkflowStep.started_at, WorkflowStep.step_key)
            ).all()
            out.append(
                RunOut(
                    id=run.id,
                    case_id=run.case_id,
                    workflow_version=run.workflow_version,
                    policy_version=run.policy_version,
                    status=run.status,
                    mode=run.mode,
                    created_at=run.created_at,
                    steps=[
                        StepOut.model_validate(s, from_attributes=True).model_copy(
                            update={
                                "replayed": run.mode == "live" and s.execution_mode == "replay"
                            }
                        )
                        for s in steps
                    ],
                )
            )
        return out
