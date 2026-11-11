"""Investigation (VER-003): start/retry effects and the `specialist_runner` job.

The worker runs workflow v3's investigation segment through LangGraph on the shared
SpecialistRunner. Each specialist reads only its permitted records through the ToolGateway;
validated findings are written by `record_finding` as a specialist service principal. Case
state/step change only through gateway commands (derive_step); policy only through the Policy
Controller. A failed step stops the graph at that node (checkpoint kept) and waits for an
explicit `retry_specialist_step`; LIVE never falls back to REPLAY on its own.
"""

import argparse
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from vera_domain.clock import Clock, default_demo_clock
from vera_domain.commands import FailedStep
from vera_domain.enums import EventType, Role
from vera_domain.errors import CommandError
from vera_domain.evidence import RECEIPT_THRESHOLD_CENTS
from vera_domain.investigation import (
    INVESTIGATION_V3,
    PROMPT_VERSION,
    SPECIALISTS,
    DraftFinding,
    TransactionIdentity,
    build_spec,
    specialist_input,
)
from vera_domain.specialists import ExecutionMode, FailureReason, StepStatus

from vera_api import gateway
from vera_api import policy as policy_service
from vera_api.auth import Actor
from vera_api.evidence import _current, read_evidence_field
from vera_api.graph import build_graph, postgres_checkpointer, run_graph
from vera_api.intake import _emit
from vera_api.model_client import (
    DEFAULT_RECORDINGS,
    PROBE_TOOL,
    LiveModelClient,
    ModelClient,
    RecordedModelClient,
    default_mode,
)
from vera_api.models import Case, IdempotencyKey
from vera_api.models_runs import WorkflowRun, WorkflowStep
from vera_api.runner import SpecialistRunner, create_run
from vera_api.worker import FAILURE_HOOKS, Touch, enqueue, register

JOB_KIND = "specialist_runner"
SYSTEM = Actor("svc-orchestrator", "Orchestrator", Role.SYSTEM, frozenset({Role.SYSTEM}))

# Test seams (never switched by product code): live transport and recordings root.
LIVE_TRANSPORT: httpx.BaseTransport | None = None
LIVE_SLEEP: Callable[[float], None] = time.sleep
RECORDINGS_ROOT: Path | None = None
CLOCK: Clock | None = None


def recordings_root() -> Path:
    if RECORDINGS_ROOT is not None:
        return RECORDINGS_ROOT
    return Path(os.environ.get("VERA_RECORDINGS_DIR") or DEFAULT_RECORDINGS)


def client_for(mode: ExecutionMode, case_id: str) -> ModelClient:
    """One client per step, chosen only by mode; no fallback between them."""
    if mode is ExecutionMode.LIVE:
        return LiveModelClient(transport=LIVE_TRANSPORT, sleep=LIVE_SLEEP)
    return RecordedModelClient(recordings_root(), case_id=case_id)


def _clock() -> Clock:
    return CLOCK or default_demo_clock()


def specialist_actor(name: str) -> Actor:
    return Actor(f"specialist:{name}", name, Role.SPECIALIST, frozenset({Role.SPECIALIST}))


# ---- facts and keys (read by the gateway) ------------------------------------------------------


def latest_run(session: Session, case_id: str) -> WorkflowRun | None:
    return session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.case_id == case_id)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
    ).first()


def run_status(session: Session, case_id: str) -> str:
    run = latest_run(session, case_id)
    if run is None:
        return "none"
    return run.status if run.status in ("running", "failed", "succeeded") else "running"


def _retries(session: Session, run_id: str, step_key: str) -> int:
    return int(
        session.scalars(
            select(func.count())
            .select_from(IdempotencyKey)
            .where(IdempotencyKey.key.like(f"retry:{run_id}:{step_key}:%"))
        ).one()
    )


def key_context(session: Session, case: Case, step_key: str) -> dict[str, object]:
    run = latest_run(session, case.id)
    run_id = run.id if run else "none"
    return {"run_id": run_id, "attempt_no": _retries(session, run_id, step_key) + 1}


def failed_steps(session: Session, case_id: str) -> list[FailedStep]:
    run = latest_run(session, case_id)
    if run is None or run.status != "failed":
        return []
    rows = session.scalars(
        select(WorkflowStep)
        .where(WorkflowStep.run_id == run.id, WorkflowStep.status == StepStatus.FAILED.value)
        .order_by(WorkflowStep.step_key)
    ).all()
    return [
        FailedStep(run.id, s.step_key, _retries(session, run.id, s.step_key) + 1, run.mode)
        for s in rows
    ]


# ---- command effects (run by the gateway inside its transaction) -------------------------------

COMMANDS = frozenset({"start_investigation", "retry_specialist_step", "complete_investigation"})


def run_effect(session: Session, case: Case, command: str, model: Any) -> dict[str, Any]:
    now = _clock().now()
    if command == "start_investigation":
        try:
            mode = default_mode()
        except (RuntimeError, ValueError) as exc:
            raise CommandError("execution_mode_unset", 503, str(exc)) from None
        run_id = create_run(session, case_id=case.id, mode=mode, now=now, commit=False)
        job_id = enqueue(session, JOB_KIND, {"run_id": run_id, "case_id": case.id}, now=now)
        return {
            "run": {
                "run_id": run_id,
                "job_id": job_id,
                "mode": mode.value,
                "workflow_version": case.workflow_version,
                "policy_version": case.policy_version,
            }
        }
    if command == "retry_specialist_step":
        run = latest_run(session, case.id)
        step = (
            session.get(WorkflowStep, (run.id, model.step_key), with_for_update=True)
            if run
            else None
        )
        if run is None or step is None or step.status != StepStatus.FAILED.value:
            raise CommandError(
                "invalid_step", 409, f"{model.step_key} has no failed step to retry."
            )
        run.status = "running"
        run.updated_at = now
        payload = {"run_id": run.id, "case_id": case.id, "modes": {model.step_key: model.mode}}
        job_id = enqueue(session, JOB_KIND, payload, now=now)
        attempt = _retries(session, run.id, model.step_key)  # this key is already pending
        return {
            "run": {
                "run_id": run.id,
                "step_key": model.step_key,
                "mode": model.mode,
                "attempt_no": attempt,
                "job_id": job_id,
                "prior_mode": step.execution_mode,
            }
        }
    run = session.get(WorkflowRun, model.run_id)
    if run is None or run.case_id != case.id:
        raise CommandError("run_not_found", 404, f"No run '{model.run_id}' on this case.")
    return {"run_status": run.status}


# ---- worker ------------------------------------------------------------------------------------


class StepFailed(Exception):
    """Controlled stop: the graph halts at this node and keeps its checkpoint."""

    def __init__(self, step_key: str, reason: str) -> None:
        super().__init__(f"{step_key} failed: {reason}")
        self.step_key = step_key
        self.reason = reason


def _reader(session: Session, case_id: str) -> Callable[[str, str], tuple[Any, int]]:
    def read(record_id: str, field: str) -> tuple[Any, int]:
        try:
            return read_evidence_field(session, case_id, record_id, field)
        except CommandError as exc:
            raise LookupError(exc.message) from None

    return read


def _transaction(session: Session, case_id: str) -> TransactionIdentity:
    from vera_api.models import CardTransaction, Merchant

    case = session.get(Case, case_id)
    assert case is not None
    txn = session.get(CardTransaction, case.transaction_id)
    assert txn is not None
    merchant = session.get(Merchant, txn.merchant_id)
    return TransactionIdentity(
        transaction_id=case.id,
        merchant=merchant.name if merchant else "",
        amount_cents=txn.amount_cents,
        currency=txn.currency,
        cardholder_id=txn.cardholder_id,
        posted_at=txn.posted_at.isoformat(),
    )


def _register(session: Session, case_id: str) -> dict[str, tuple[str, list[str]]]:
    return {r.id: (r.kind, list(v.fields)) for r, v in _current(session, case_id)}


def _execute_retrying(
    factory: sessionmaker[Session],
    case_id: str,
    command: str,
    key: str,
    payload: dict[str, Any],
    actor: Actor,
) -> None:
    """Service command with a fresh expected version; parallel nodes may race on the version."""
    for _ in range(8):
        with factory() as s:
            version = s.scalars(select(Case.case_version).where(Case.id == case_id)).one()
            s.rollback()
            try:
                gateway.execute_command(
                    s,
                    now=_clock().now(),
                    case_id=case_id,
                    command=command,
                    key=key,
                    expected_version=version,
                    payload=payload,
                    actor=actor,
                    request_id=f"worker:{key}",
                )
                return
            except CommandError as exc:
                if exc.code != "stale_case_version":
                    raise
    raise RuntimeError(f"{command} kept racing on the case version")


def finding_payloads(run_id: str, step_key: str, findings: list[DraftFinding]) -> list[Any]:
    out = []
    for n, f in enumerate(findings, start=1):
        body: dict[str, Any] = {
            "finding_id": f"FND-{run_id}-{step_key}-{n}",
            "kind": f.kind,
            "statement": f.statement,
            "links": [
                {"record_id": c.record_id, "version": c.version, "field": c.field}
                for c in f.citations
            ],
        }
        if f.conflict_field:
            body["conflict_field"] = f.conflict_field
        out.append(body)
    return out


def _emit_once(
    factory: sessionmaker[Session],
    case_id: str,
    type_: EventType,
    run_id: str,
    step_key: str,
    summary: str,
    detail: dict[str, Any],
) -> None:
    """Emit unless an event with the same type and detail exists (a re-delivered job repeats
    nothing)."""
    from vera_api.models import AuditEvent

    body = {"run_id": run_id, "step_key": step_key, **detail}
    with factory() as s:
        case = s.get(Case, case_id, with_for_update=True)
        assert case is not None
        seen = s.scalars(
            select(AuditEvent.id).where(
                AuditEvent.case_id == case_id,
                AuditEvent.type == type_.value,
                AuditEvent.detail.contains(body),
            )
        ).first()
        if seen is None:
            _emit(
                s,
                type_,
                case,
                SYSTEM.user_id,
                Role.SYSTEM,
                _clock().now(),
                [case_id],
                summary,
                body,
            )
        s.commit()


# Test seam: called at the start of every node (crash injection).
NODE_HOOK: Callable[[str], None] | None = None


def make_node_fn(
    factory: sessionmaker[Session],
    run_id: str,
    case_id: str,
    pinned: ExecutionMode,
    overrides: dict[str, str],
    touch: Touch,
) -> Callable[[str, str, dict[str, Any]], None]:
    def node_fn(key: str, kind: str, state: dict[str, Any]) -> None:
        if NODE_HOOK is not None:
            NODE_HOOK(key)
        with factory() as s:
            if kind == "policy_check":
                policy_service.evaluate_and_store(
                    s, case_id, policy_service.POLICY_CONTROLLER, _clock().now()
                )
                s.commit()
                return
            row = s.get(WorkflowStep, (run_id, key))
            if row is not None and row.status == StepStatus.FAILED.value and key not in overrides:
                # Another failed step: it waits for its own explicit retry, no provider call.
                raise StepFailed(key, row.failure_reason or "failed")
            s.rollback()
            mode = ExecutionMode(overrides.get(key, pinned.value))
            register = _register(s, case_id)
            spec = build_spec(key, {rid: kind_ for rid, (kind_, _) in register.items()})
            inputs = specialist_input(
                key, case_id, _transaction(s, case_id), register, RECEIPT_THRESHOLD_CENTS
            )

            def apply(output: BaseModel) -> None:
                actor = specialist_actor(key)
                for body in finding_payloads(run_id, key, list(getattr(output, "findings", []))):
                    _execute_retrying(
                        factory,
                        case_id,
                        "record_finding",
                        f"finding:{body['finding_id']}",
                        body,
                        actor,
                    )

            runner = SpecialistRunner(client_for, _reader(s, case_id), _clock())
            outcome = runner.run_step(s, run_id, key, spec, inputs, mode, apply, touch)
        if outcome.status != StepStatus.SUCCEEDED.value:
            raise StepFailed(key, outcome.failure_reason or "failed")
        with factory() as s:
            row = s.get(WorkflowStep, (run_id, key))
            stored_mode = row.execution_mode if row else None
        if stored_mode == ExecutionMode.REPLAY.value and pinned is ExecutionMode.LIVE:
            _emit_once(
                factory,
                case_id,
                EventType.SPECIALIST_REPLAYED,
                run_id,
                key,
                f"{key}: replayed result (recorded reference output, not live inference)",
                {"execution_mode": "replay"},
            )

    return node_fn


def _db_url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


@register(JOB_KIND)
def run_investigation(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    run_id, case_id = str(payload["run_id"]), str(payload["case_id"])
    overrides = {str(k): str(v) for k, v in dict(payload.get("modes") or {}).items()}
    run = session.get(WorkflowRun, run_id)
    if run is None or run.status != "running":
        session.rollback()
        return  # succeeded already, or failed and waiting for an explicit retry
    pinned = ExecutionMode(run.mode)
    session.rollback()
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    factory = sessionmaker(engine, expire_on_commit=False)
    node_fn = make_node_fn(factory, run_id, case_id, pinned, overrides, touch)
    try:
        with postgres_checkpointer(_db_url(engine)) as saver:
            run_graph(build_graph(INVESTIGATION_V3, node_fn, saver), run_id)
    except StepFailed:
        _fail_run(factory, run_id, case_id)
        return  # the job completes; recovery is an explicit analyst command
    _finish(factory, run_id, "succeeded")
    try:
        _execute_retrying(
            factory,
            case_id,
            "complete_investigation",
            f"invdone:{run_id}",
            {"run_id": run_id},
            SYSTEM,
        )
    except CommandError as exc:
        if exc.code not in ("invalid_step", "case_closed"):
            raise  # held/closed meanwhile: derive_step picks the run status up on resume


def _fail_run(factory: sessionmaker[Session], run_id: str, case_id: str) -> None:
    """Mark the run failed and emit specialist.failed once per failed step (and attempt)."""
    _finish(factory, run_id, "failed")
    with factory() as s:
        rows = s.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.run_id == run_id, WorkflowStep.status == StepStatus.FAILED.value)
            .order_by(WorkflowStep.step_key)
        ).all()
        failed = [
            (r.step_key, r.failure_reason or "failed", _retries(s, run_id, r.step_key))
            for r in rows
        ]
    for step_key, reason, attempt in failed:
        _emit_once(
            factory,
            case_id,
            EventType.SPECIALIST_FAILED,
            run_id,
            step_key,
            f"{step_key} failed: {reason}. Retry or hold the case.",
            {"reason": reason, "attempt": attempt},
        )


def on_job_failed(session: Session, payload: dict[str, Any], error: str) -> None:
    """Safety net: the job is out of attempts. Any step still `running` becomes failed with
    apply_failed (its validated output is kept), so the case offers retry and hold."""
    run_id, case_id = str(payload["run_id"]), str(payload["case_id"])
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        run = s.get(WorkflowRun, run_id, with_for_update=True)
        if run is None or run.status != "running":
            return
        for step in s.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.run_id == run_id, WorkflowStep.status == StepStatus.RUNNING.value)
            .with_for_update()
        ):
            step.status = StepStatus.FAILED.value
            step.failure_reason = FailureReason.APPLY_FAILED.value
            step.error = error[:500]
            step.finished_at = _clock().now()
        s.commit()
    _fail_run(factory, run_id, case_id)


FAILURE_HOOKS[JOB_KIND] = on_job_failed


def _finish(factory: sessionmaker[Session], run_id: str, status: str) -> None:
    with factory() as s:
        run = s.get(WorkflowRun, run_id, with_for_update=True)
        assert run is not None
        run.status = status
        run.updated_at = _clock().now()
        s.commit()


# ---- request files for recording on a networked machine ----------------------------------------


def dump_requests(session: Session, case_id: str, root: Path) -> list[Path]:
    register = _register(session, case_id)
    txn = _transaction(session, case_id)
    out = []
    for name in SPECIALISTS:
        spec = build_spec(name, {rid: k for rid, (k, _) in register.items()})
        inputs = specialist_input(name, case_id, txn, register, RECEIPT_THRESHOLD_CENTS)
        path = root / name / PROMPT_VERSION / f"{case_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "messages": spec.build_messages(inputs),
            "response_schema": spec.output_schema.model_json_schema(),
            "tools": [PROBE_TOOL],
        }
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    from vera_api.config import Settings
    from vera_api.db import make_engine

    p = argparse.ArgumentParser(prog="python -m vera_api.investigation")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump-requests", help="write evals/requests/{specialist}/v1/{case}.json")
    d.add_argument("--case-id", default="CHG-1042")
    d.add_argument("--root", default="evals/requests")
    args = p.parse_args(argv)
    with sessionmaker(make_engine(Settings().database_url))() as session:
        for path in dump_requests(session, args.case_id, Path(args.root)):
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
