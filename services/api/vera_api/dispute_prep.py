"""Dispute Packet Preparer job: runs the `dispute_packet_preparer` specialist once the dispute
packet is prepared and stores its validated reason code and cited narrative on the packet through
the `record_dispute_narrative` service command.

The step runs on the case's latest workflow run (the investigation run's status is not touched)
with that run's pinned mode. A failed step emits `specialist.failed` and is recovered only by the
analyst's explicit `retry_dispute_narrative`; the dispute track never waits for the narrative.
"""

import json
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from vera_domain import dispute_prep as dom
from vera_domain.enums import EventType
from vera_domain.errors import CommandError
from vera_domain.specialists import ExecutionMode, FailureReason, StepStatus

from vera_api import gateway
from vera_api.auth import Actor
from vera_api.gateway import EffectContext
from vera_api.model_client import PROBE_TOOL
from vera_api.models import Case, IdempotencyKey
from vera_api.models_comms import Communication
from vera_api.models_evidence import Finding
from vera_api.models_money import DisputePacket
from vera_api.models_runs import WorkflowRun, WorkflowStep
from vera_api.runner import SpecialistRunner
from vera_api.worker import FAILURE_HOOKS, Touch, enqueue, register

JOB_KIND = "dispute_packet_preparer"
NarrativeStatus = str  # pending | ready | failed


# vera_api.investigation imports the gateway, which loads this feature: import it on use.
def _inv() -> ModuleType:
    from vera_api import investigation

    return investigation


# ---- reads --------------------------------------------------------------------------------------


def packet(session: Session, case_id: str) -> DisputePacket | None:
    return session.scalars(select(DisputePacket).where(DisputePacket.case_id == case_id)).first()


def latest_step(session: Session, case_id: str) -> WorkflowStep | None:
    """The preparer step of the case's most recent run that has one."""
    return session.scalars(
        select(WorkflowStep)
        .join(WorkflowRun, WorkflowRun.id == WorkflowStep.run_id)
        .where(WorkflowRun.case_id == case_id, WorkflowStep.step_key == dom.PREPARER)
        .order_by(WorkflowRun.seq.desc())
    ).first()


def narrative_status(session: Session, row: DisputePacket) -> NarrativeStatus:
    if row.narrative is not None:
        return "ready"
    step = latest_step(session, row.case_id)
    if step is not None and step.status == StepStatus.FAILED.value:
        return "failed"
    return "pending"


def _views(
    session: Session, case_id: str
) -> tuple[dict[str, tuple[str, list[str]]], dict[tuple[str, str], Any]]:
    """Open findings and the response review as read-only records (version 1): their ids, kinds
    and field names for the prompt, and their values for read_field."""
    records: dict[str, tuple[str, list[str]]] = {}
    values: dict[tuple[str, str], Any] = {}
    findings = session.scalars(
        select(Finding)
        .where(Finding.case_id == case_id, Finding.status == "open")
        .order_by(Finding.id)
    ).all()
    for f in findings:
        records[f.id] = (dom.FINDING_KIND, list(dom.FINDING_FIELDS))
        values[(f.id, "kind")] = f.kind
        values[(f.id, "statement")] = f.statement
    comm = session.scalars(
        select(Communication)
        .where(Communication.case_id == case_id)
        .order_by(Communication.created_at.desc(), Communication.id.desc())
    ).first()
    if comm is not None and comm.response_review != "none":
        records[comm.id] = (dom.REVIEW_KIND, list(dom.REVIEW_FIELDS))
        values[(comm.id, "outcome")] = comm.response_review
    return records, values


def _records_and_reader(session: Session, case_id: str) -> tuple[dict[str, Any], Any]:
    register_ = _inv()._register(session, case_id)
    views, values = _views(session, case_id)
    base = _inv()._reader(session, case_id)

    def read(record_id: str, field: str) -> tuple[Any, int]:
        if (record_id, field) in values:
            return values[(record_id, field)], 1
        if record_id in views:
            raise LookupError(f"{record_id} has no '{field}'.")
        return base(record_id, field)  # type: ignore[no-any-return]

    return {**register_, **views}, read


# ---- command effects ----------------------------------------------------------------------------


def _wrong(message: str) -> CommandError:
    return CommandError("invalid_step", 409, message, blocked_reason=message)


def _record_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    """Stores the runner's VALIDATED step output (never text passed by the caller)."""
    row = session.get(DisputePacket, p.packet_id)
    run = session.get(WorkflowRun, p.run_id)
    if row is None or row.case_id != case.id or run is None or run.case_id != case.id:
        raise CommandError("packet_not_found", 404, "No such dispute packet run.")
    step = session.get(WorkflowStep, (p.run_id, dom.PREPARER))
    if step is None or step.output is None:
        raise CommandError("precondition_failed", 422, "The preparer has no validated output.")
    out = dom.PreparerOutput.model_validate(step.output)
    row.reason_code = out.reason_code
    row.narrative = [s.model_dump(mode="json") for s in out.statements]
    row.updated_at = now
    session.flush()
    return {
        "dispute_id": f"DSP-{row.id}",
        "reason_code": out.reason_code,
        "statements": len(out.statements),
        "run_id": p.run_id,
        "execution_mode": step.execution_mode,
    }


def _retry_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    """Explicit recovery: rerun the failed preparer step live or from the recording."""
    row = packet(session, case.id)
    step = _failed_preparer(session, case)
    if row is None or step is None:
        raise _wrong("The dispute narrative has no failed preparation to retry.")
    job_id = enqueue(
        session,
        JOB_KIND,
        {"case_id": case.id, "packet_id": row.id, "run_id": step.run_id, "mode": p.mode},
        now=now,
    )
    return {
        "dispute_id": f"DSP-{row.id}",
        "run_id": step.run_id,
        "mode": p.mode,
        "job_id": job_id,
        "prior_failure": step.failure_reason,
    }


def enqueue_preparer(session: Session, case_id: str, now: datetime) -> None:
    """Called by money's prepare_dispute_packet after-effect, inside its transaction."""
    row = packet(session, case_id)
    assert row is not None
    run_id, _created = _inv().run_for_step(session, case_id, now)
    enqueue(session, JOB_KIND, {"case_id": case_id, "packet_id": row.id, "run_id": run_id}, now=now)


gateway.register_commands(
    __name__,
    human=dom.HUMAN,
    service=dom.SERVICE,
    effects={dom.RECORD.name: _record_effect, dom.RETRY.name: _retry_effect},
)


def _failed_preparer(session: Session, case: Case) -> WorkflowStep | None:
    """The preparer step the retry would rerun: the packet has no narrative and it failed."""
    row = packet(session, case.id)
    step = latest_step(session, case.id)
    if row is None or row.narrative is not None or step is None:
        return None
    return step if step.status == StepStatus.FAILED.value else None


def _nothing_to_retry(session: Session, case: Case) -> CommandError | None:
    if _failed_preparer(session, case) is None:
        return _wrong("The dispute narrative has no failed preparation to retry.")
    return None


def _retry_defaults(session: Session, case: Case) -> dict[str, Any]:
    step = _failed_preparer(session, case)
    run = session.get(WorkflowRun, step.run_id) if step is not None else None
    return {"mode": run.mode} if run is not None else {}


gateway.register_actions(
    __name__,
    defaults={dom.RETRY.name: _retry_defaults},
    guards={dom.RETRY.name: _nothing_to_retry},
    hidden_when_refused=[dom.RETRY.name],
)

# ---- worker -------------------------------------------------------------------------------------


@register(JOB_KIND)
def run_preparer(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    case_id, packet_id = str(payload["case_id"]), int(payload["packet_id"])
    inv = _inv()
    run = (
        session.get(WorkflowRun, str(payload["run_id"]))
        if payload.get("run_id")
        else inv.latest_run(session, case_id)
    )
    if run is None:
        session.rollback()
        return
    run_id = run.id
    mode = ExecutionMode(str(payload.get("mode") or run.mode))
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    factory = sessionmaker(engine, expire_on_commit=False)
    session.rollback()
    with factory() as s:
        records, read = _records_and_reader(s, case_id)
        spec = dom.build_spec({rid: kind for rid, (kind, _) in records.items()})
        inputs = dom.preparer_input(case_id, records)

        def apply(output: BaseModel) -> None:
            try:
                inv._execute_retrying(
                    factory,
                    case_id,
                    dom.RECORD.name,
                    f"dspnarr:{case_id}:{packet_id}",
                    {"packet_id": packet_id, "run_id": run_id},
                    inv.specialist_actor(dom.PREPARER),
                )
            except CommandError as exc:
                if exc.code != "case_closed":
                    raise  # closed meanwhile: the narrative is moot

        runner = SpecialistRunner(inv.client_for, read, inv._clock())
        outcome = runner.run_step(s, run_id, dom.PREPARER, spec, inputs, mode, apply, touch)
    succeeded = outcome.status == StepStatus.SUCCEEDED.value
    inv.settle_step_run(factory, run_id, dom.PREPARER, succeeded)
    if not succeeded:
        _failed(factory, case_id, run_id, outcome.failure_reason or "failed")


def _failed(factory: sessionmaker[Session], case_id: str, run_id: str, reason: str) -> None:
    with factory() as s:
        retries = s.scalars(
            select(func.count())
            .select_from(IdempotencyKey)
            .where(IdempotencyKey.key.like(f"{dom.RETRY.key_template.split(':')[0]}:{case_id}:%"))
        ).one()
    _inv()._emit_once(
        factory,
        case_id,
        EventType.SPECIALIST_FAILED,
        run_id,
        dom.PREPARER,
        f"{dom.PREPARER} failed: {reason}. Retry the dispute narrative; the dispute packet can "
        "still be opened, reviewed and submitted.",
        {"reason": reason, "attempt": int(retries) + 1},
    )


def on_job_failed(session: Session, payload: dict[str, Any], error: str) -> None:
    """Out of attempts: a step still `running` fails explicitly (apply_failed, output kept)."""
    case_id = str(payload["case_id"])
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        step = latest_step(s, case_id)
        if step is None or step.status != StepStatus.RUNNING.value:
            return
        run_id = step.run_id
        step = s.get(WorkflowStep, (run_id, dom.PREPARER), with_for_update=True)
        assert step is not None
        step.status = StepStatus.FAILED.value
        step.failure_reason = FailureReason.APPLY_FAILED.value
        step.error = error[:500]
        step.finished_at = _inv()._clock().now()
        s.commit()
    _inv().settle_step_run(factory, run_id, dom.PREPARER, False)
    _failed(factory, case_id, run_id, FailureReason.APPLY_FAILED.value)


FAILURE_HOOKS[JOB_KIND] = on_job_failed


# ---- request file for recording on a networked machine ------------------------------------------


def dump_request(session: Session, case_id: str, root: Path) -> Path:
    """Writes evals/requests/dispute_packet_preparer/v1/{case_id}.json for the case as stored."""
    records, _read = _records_and_reader(session, case_id)
    spec = dom.build_spec({rid: kind for rid, (kind, _) in records.items()})
    inputs = dom.preparer_input(case_id, records)
    path = Path(root) / dom.PREPARER / dom.PROMPT_VERSION / f"{case_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "messages": spec.build_messages(inputs),
        "response_schema": spec.output_schema.model_json_schema(),
        "tools": [PROBE_TOOL],
    }
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return path
