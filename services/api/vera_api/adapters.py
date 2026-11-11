"""Adapter execution: exactly-once by idempotency key, with deterministic fault injection.

`execute` runs inside the caller's transaction (a command effect holds the case lock).
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vera_domain.adapters import AdapterResult, FaultMode, SimulatedAdapter
from vera_domain.enums import Role
from vera_domain.errors import CommandError

from vera_api import plugins
from vera_api.db import session_iter
from vera_api.intake import _emit
from vera_api.models import Case
from vera_api.models_adapters import AdapterExecution, AdapterFault

# name -> simulated adapter. Feature modules register theirs; none is registered here.
ADAPTERS: dict[str, SimulatedAdapter] = {}


def register_adapter(name: str, adapter: SimulatedAdapter) -> None:
    if name in ADAPTERS:
        raise ValueError(f"adapter '{name}' is already registered")
    ADAPTERS[name] = adapter


def _view(row: AdapterExecution, *, replayed: bool = False) -> AdapterResult:
    status: Literal["succeeded", "failed", "uncertain"] = (
        "succeeded"
        if row.status == "succeeded"
        else "failed"
        if row.status == "failed"
        else "uncertain"
    )
    # An uncertain result is never shown: the caller must not act on it until lookup resolves it.
    result = dict(row.result or {}) if status == "succeeded" else {}
    return AdapterResult(
        status=status, result=result, error=row.error, execution_id=row.id, replayed=replayed
    )


def _record(session: Session, row: AdapterExecution, now: datetime) -> None:
    row.updated_at = now
    case = session.get(Case, row.case_id)
    if case is None:
        raise CommandError("case_not_found", 404, "No such case.")
    row.event_id = _emit(
        session,
        f"adapter.{row.status}",
        case,
        f"adapter:{row.adapter}",
        Role.ADAPTER,
        now,
        [row.case_id],
        f"{row.adapter}.{row.operation} {row.status} (simulated)",
        {"execution_id": row.id, "idempotency_key": row.idempotency_key, "error": row.error},
    )
    session.flush()


def _take_fault(session: Session, adapter: str, operation: str) -> str | None:
    fault = session.scalars(
        select(AdapterFault)
        .where(
            AdapterFault.adapter == adapter,
            AdapterFault.operation == operation,
            AdapterFault.remaining > 0,
        )
        .order_by(AdapterFault.id)
        .with_for_update()
    ).first()
    if fault is None:
        return None
    fault.remaining -= 1
    return fault.mode


def execute(
    session: Session,
    *,
    case_id: str,
    adapter: str,
    operation: str,
    key: str,
    request: dict[str, Any],
    now: datetime,
) -> AdapterResult:
    """Exactly-once by key. A succeeded or uncertain key returns the stored row without calling
    the adapter again; a failed key (nothing happened) is retried under the same key."""
    impl = ADAPTERS.get(adapter)
    if impl is None:
        raise CommandError("adapter_not_registered", 502, f"No adapter named '{adapter}'.")
    row = session.scalars(
        select(AdapterExecution).where(AdapterExecution.idempotency_key == key).with_for_update()
    ).first()
    if row is not None:
        if (row.case_id, row.adapter, row.operation, row.request) != (
            case_id,
            adapter,
            operation,
            request,
        ):
            raise CommandError(
                "idempotency_key_conflict", 409, "That key was used for a different execution."
            )
        if row.status in ("succeeded", "uncertain"):
            return _view(row, replayed=True)
    else:
        row = AdapterExecution(
            case_id=case_id,
            adapter=adapter,
            operation=operation,
            idempotency_key=key,
            request=request,
            status="pending",
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        try:
            with session.begin_nested():  # savepoint: a lost race must not poison the caller
                session.add(row)
                session.flush()
        except IntegrityError:
            # Another transaction inserted this key first (its commit released our insert).
            # Start over on its row: a succeeded or uncertain result replays, never re-dispatches.
            return execute(
                session,
                case_id=case_id,
                adapter=adapter,
                operation=operation,
                key=key,
                request=request,
                now=now,
            )
    row.attempts += 1
    fault = _take_fault(session, adapter, operation)
    if fault in ("fail", "timeout"):  # failed before the effect: the adapter is not called
        row.status = "failed"
        row.error = "timeout before dispatch" if fault == "timeout" else "injected failure"
    else:
        out = impl.call(operation, request)
        row.result, row.error = out.result, out.error
        # Injected uncertainty: the effect happened, the response was "lost".
        row.status = (
            "uncertain" if fault == "uncertain" and out.status == "succeeded" else out.status
        )
    _record(session, row, now)
    return _view(row)


def lookup(session: Session, key: str, now: datetime | None = None) -> AdapterResult | None:
    """The stored execution for a key. An uncertain one is resolved from the result the adapter
    already produced (succeeded if it has one, failed otherwise); the adapter is never re-called."""
    row = session.scalars(
        select(AdapterExecution).where(AdapterExecution.idempotency_key == key).with_for_update()
    ).first()
    if row is None:
        return None
    if row.status == "uncertain":
        row.status = "succeeded" if row.result is not None and row.error is None else "failed"
        _record(session, row, now or row.updated_at)
    return _view(row, replayed=True)


def inject_fault(
    session: Session, adapter: str, operation: str, mode: FaultMode, times: int = 1
) -> None:
    """The next `times` executions of (adapter, operation) fail / go uncertain / time out."""
    session.add(AdapterFault(adapter=adapter, operation=operation, mode=mode, remaining=times))
    session.flush()


class FaultRequest(BaseModel):
    adapter: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    mode: FaultMode
    times: int = Field(default=1, ge=1, le=10)


router = APIRouter(prefix="/api/demo")


def _session(request: Request) -> Iterator[Session]:
    yield from session_iter(request.app.state.session_factory)


@router.post("/adapter-fault")
def post_adapter_fault(
    body: FaultRequest, session: Annotated[Session, Depends(_session)]
) -> dict[str, Any]:
    if body.adapter not in ADAPTERS:
        raise CommandError("adapter_not_registered", 422, f"No adapter named '{body.adapter}'.")
    inject_fault(session, body.adapter, body.operation, body.mode, body.times)
    session.commit()
    return {"injected": body.model_dump()}


plugins.register_router(router, synthetic_only=True)
plugins.register_reset_tables(["adapter_executions", "adapter_faults"])
