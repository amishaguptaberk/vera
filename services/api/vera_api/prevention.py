"""Prevention Planner job (VER-010): runs the `prevention_planner` specialist after a credit is
issued and stores its recommendation through the `recommend_card_controls` service command.

The step runs on the case's latest workflow run (so the investigation run's status is not
touched), with that run's pinned mode. A failed step emits `specialist.failed`; the case is not
blocked and humans can still propose or skip controls themselves.
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker
from vera_domain.enums import EventType
from vera_domain.errors import CommandError
from vera_domain.prevention import PLANNER, build_spec, planner_input
from vera_domain.specialists import ExecutionMode, StepStatus

from vera_api import gateway
from vera_api import investigation as inv
from vera_api.models import Case
from vera_api.runner import SpecialistRunner
from vera_api.worker import Touch, register

JOB_KIND = "prevention_planner"


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
                    now=inv._clock().now(),
                    case_id=case_id,
                    command="recommend_card_controls",
                    key=f"ctl-rec:{case_id}:{version}",
                    expected_version=version,
                    payload=payload,
                    actor=inv.specialist_actor(PLANNER),
                    request_id=f"worker:ctl-rec:{case_id}",
                )
                return
            except CommandError as exc:
                if exc.code != "stale_case_version":
                    raise
    raise RuntimeError("recommend_card_controls kept racing on the case version")


@register(JOB_KIND)
def run_planner(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    case_id = str(payload["case_id"])
    run = inv.latest_run(session, case_id)
    if run is None:
        session.rollback()
        return
    run_id, mode = run.id, ExecutionMode(run.mode)
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    factory = sessionmaker(engine, expire_on_commit=False)
    session.rollback()
    with factory() as s:
        register_ = inv._register(s, case_id)
        spec = build_spec({rid: kind for rid, (kind, _) in register_.items()})
        inputs = planner_input(case_id, register_)

        def apply(output: BaseModel) -> None:
            try:
                _recommend(factory, case_id, recommend_payload(output))
            except CommandError as exc:
                if exc.code not in ("invalid_step", "case_closed"):
                    raise  # a human already decided the controls: the recommendation is moot

        runner = SpecialistRunner(inv.client_for, inv._reader(s, case_id), inv._clock())
        outcome = runner.run_step(s, run_id, PLANNER, spec, inputs, mode, apply, touch)
    if outcome.status != StepStatus.SUCCEEDED.value:
        reason = outcome.failure_reason or "failed"
        inv._emit_once(
            factory,
            case_id,
            EventType.SPECIALIST_FAILED,
            run_id,
            PLANNER,
            f"{PLANNER} failed: {reason}. Propose or skip controls manually.",
            {"reason": reason},
        )
