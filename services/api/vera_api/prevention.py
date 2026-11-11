"""Prevention Planner job: runs the `prevention_planner` specialist after a credit is
issued and stores its recommendation through the `recommend_card_controls` service command.

The step runs on the case's latest workflow run (so the investigation run's status is not
touched), with that run's pinned mode. A failed step emits `specialist.failed`; the case is not
blocked and humans can still propose or skip controls themselves.
"""

from datetime import datetime
from types import ModuleType
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker
from vera_domain.enums import EventType
from vera_domain.errors import CommandError
from vera_domain.prevention import PLANNER, build_spec, planner_input
from vera_domain.specialists import ExecutionMode, StepStatus

from vera_api import gateway
from vera_api.models import Case
from vera_api.models_runs import WorkflowRun
from vera_api.runner import SpecialistRunner
from vera_api.worker import Touch, enqueue, register

JOB_KIND = "prevention_planner"


# vera_api.investigation imports the gateway, which loads this feature: import it on use.
def _inv() -> ModuleType:
    from vera_api import investigation

    return investigation


def recommend_payload(output: BaseModel) -> dict[str, Any]:
    controls = list(getattr(output, "controls", []))
    reason = " ".join(f"{c.control}: {c.reason}" for c in controls)
    return {"controls": [c.control for c in controls], "reason": reason[:500]}


def _recommend(factory: sessionmaker[Session], case_id: str, payload: dict[str, Any]) -> None:
    """The command's key is bound to the case version, so it is rebuilt on each version race."""
    for _ in range(8):
        with factory() as s:
            version = s.scalars(select(Case.case_version).where(Case.id == case_id)).one()
            s.rollback()
            try:
                gateway.execute_command(
                    s,
                    now=_inv()._clock().now(),
                    case_id=case_id,
                    command="recommend_card_controls",
                    key=f"ctl-rec:{case_id}:{version}",
                    expected_version=version,
                    payload=payload,
                    actor=_inv().specialist_actor(PLANNER),
                    request_id=f"worker:ctl-rec:{case_id}",
                )
                return
            except CommandError as exc:
                if exc.code != "stale_case_version":
                    raise
    raise RuntimeError("recommend_card_controls kept racing on the case version")


def enqueue_planner(session: Session, case_id: str, now: datetime) -> None:
    """Called after a credit is issued, inside that command's transaction. The planner runs on
    the case's latest run, or on one created for it. With no run and no execution mode the job
    still runs and fails explicitly: the credit that was just issued is never rolled back."""
    try:
        run_id: str | None = _inv().run_for_step(session, case_id, now)[0]
    except CommandError:
        run_id = None
    enqueue(session, JOB_KIND, {"case_id": case_id, "run_id": run_id}, now=now)


@register(JOB_KIND)
def run_planner(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    case_id = str(payload["case_id"])
    run = (
        session.get(WorkflowRun, str(payload["run_id"]))
        if payload.get("run_id")
        else _inv().latest_run(session, case_id)
    )
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    factory = sessionmaker(engine, expire_on_commit=False)
    if run is None:
        session.rollback()
        _inv()._emit_once(
            factory,
            case_id,
            EventType.SPECIALIST_FAILED,
            "none",
            PLANNER,
            f"{PLANNER} could not run: the case has no workflow run and no execution mode is "
            "set. Propose or skip controls manually.",
            {"reason": "no_run"},
        )
        return
    run_id, mode = run.id, ExecutionMode(run.mode)
    session.rollback()
    with factory() as s:
        register_ = _inv()._register(s, case_id)
        spec = build_spec({rid: kind for rid, (kind, _) in register_.items()})
        inputs = planner_input(case_id, register_)

        def apply(output: BaseModel) -> None:
            try:
                _recommend(factory, case_id, recommend_payload(output))
            except CommandError as exc:
                if exc.code not in ("invalid_step", "case_closed"):
                    raise  # a human already decided the controls: the recommendation is moot

        runner = SpecialistRunner(_inv().client_for, _inv()._reader(s, case_id), _inv()._clock())
        outcome = runner.run_step(s, run_id, PLANNER, spec, inputs, mode, apply, touch)
    succeeded = outcome.status == StepStatus.SUCCEEDED.value
    _inv().settle_step_run(factory, run_id, PLANNER, succeeded)
    if not succeeded:
        reason = outcome.failure_reason or "failed"
        _inv()._emit_once(
            factory,
            case_id,
            EventType.SPECIALIST_FAILED,
            run_id,
            PLANNER,
            f"{PLANNER} failed: {reason}. Propose or skip controls manually.",
            {"reason": reason},
        )
