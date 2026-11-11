"""Command gateway: role -> schema -> replay -> version -> closed -> step -> policy -> permission
-> transaction. Every case write goes through execute_command (or apply_reduction for intake)."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.commands import (
    REGISTRY,
    CommandSpec,
    ReduceContext,
    Reduction,
    blocked_reason,
    check_role,
    policy_gate,
    resolve_key,
)
from vera_domain.enums import CaseState, CaseStep, Role
from vera_domain.errors import CommandError
from vera_domain.evidence import SERVICE_REGISTRY
from vera_domain.facts import CaseFacts, Hold, derive_step
from vera_domain.policy import PolicyResult

from vera_api import policy as policy_service
from vera_api.auth import HUMAN_ROLES, STAFF_ROLES, Actor
from vera_api.intake import _emit
from vera_api.models import (
    Case,
    CaseAssignment,
    IdempotencyKey,
    Report,
    StateTransition,
    User,
    UserRole,
)


@dataclass(frozen=True)
class Outcome:
    status: str  # recorded | replayed
    result: dict[str, Any]
    event_ids: list[str]


def facts_of(case: Case) -> CaseFacts:
    return CaseFacts(
        opened_at=case.opened_at,
        closed=case.state == CaseState.CLOSED.value,
        hold=Hold.model_validate(case.hold) if case.hold else None,
        owner_id=case.owner_id,
        due_at=case.due_at,
    )


def _lock_case(session: Session, case_id: str) -> Case:
    case = session.scalars(
        select(Case)
        .where(Case.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if case is None:
        raise CommandError("case_not_found", 404, "No such case.")
    if not case.live:
        raise CommandError(
            "case_not_openable", 404, "This row is display-only and cannot be opened."
        )
    return case


def _resolver(session: Session) -> Any:
    def resolve(ref: str) -> tuple[str, str] | None:
        # Only staff can own a case; a cardholder never resolves (id or name).
        users = session.scalars(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(UserRole.role.in_([r.value for r in STAFF_ROLES]))
            .distinct()
        ).all()
        for u in users:
            if u.id == ref or u.name.lower() == ref.strip().lower():
                return u.id, u.name
        return None

    return resolve


def request_hash(command: str, user_id: str, role: Role, payload: dict[str, Any]) -> str:
    body = json.dumps([command, user_id, role.value, payload], sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def find_key(
    session: Session, key: str, case_id: str, command: str, req_hash: str
) -> IdempotencyKey | None:
    row = session.get(IdempotencyKey, key)
    if row is None:
        return None
    if row.case_id != case_id or row.command != command or row.request_hash != req_hash:
        raise CommandError(
            "idempotency_key_conflict",
            409,
            "That key was already used for a different command, user, role or payload.",
        )
    return row


def replay(row: IdempotencyKey, now: datetime) -> Outcome:
    if row.status == "checking":
        raise CommandError("adapter_uncertain", 504, "Checking the existing result.")
    if row.status != "completed":
        raise CommandError("idempotency_key_conflict", 409, f"Key is {row.status}.")
    row.attempts += 1
    row.last_at = now
    return Outcome("replayed", dict(row.result or {}), [str(e) for e in row.event_ids])


def apply_reduction(
    session: Session,
    case: Case,
    spec: CommandSpec,
    red: Reduction,
    *,
    key: str,
    req_hash: str,
    actor_id: str,
    actor_role: Role,
    request_id: str,
    now: datetime,
) -> Outcome:
    """Stage 9: key, reducer output, derive_step, version+1, transition row and events."""
    declared = tuple(e.type for e in red.events)
    if declared != spec.events:
        raise RuntimeError(f"{spec.name} reducer emitted {declared}, declared {spec.events}")
    session.add(
        IdempotencyKey(
            key=key,
            command=spec.name,
            case_id=case.id,
            status="pending",
            request_id=request_id,
            request_hash=req_hash,
            attempts=1,
            first_at=now,
            last_at=now,
            event_ids=[],
        )
    )
    prior_state, prior_step = case.state, case.step
    new = red.facts
    state, step = derive_step(new)
    case.state, case.step = state.value, step.value
    case.opened_at = new.opened_at
    case.hold = new.hold.model_dump(mode="json") if new.hold else None
    if new.owner_id != case.owner_id:
        session.add(CaseAssignment(case_id=case.id, user_id=new.owner_id, assigned_at=now))
    case.owner_id = new.owner_id
    case.due_at = new.due_at
    case.case_version += 1
    event_ids = [
        _emit(session, e.type, case, actor_id, actor_role, now, e.record_ids, e.summary, e.detail)
        for e in red.events
    ]
    session.add(
        StateTransition(
            case_id=case.id,
            prior_state=prior_state,
            prior_step=prior_step,
            next_state=case.state,
            next_step=case.step,
            actor_id=actor_id,
            actor_role=actor_role.value,
            reason=red.reason,
            case_version=case.case_version,
            workflow_version=case.workflow_version,
            policy_version=case.policy_version,
            evidence_snapshot=case.evidence_snapshot,
            event_id=event_ids[0],
            at=now,
        )
    )
    ids = [f"EVT-{i}" for i in event_ids]
    row = session.get(IdempotencyKey, key)
    if row is None:
        raise RuntimeError("idempotency key row vanished inside the transaction")
    row.status = "completed"
    row.result = red.result
    row.event_ids = ids
    session.flush()
    return Outcome("recorded", red.result, ids)


def _recheck_role(session: Session, actor: Actor) -> None:
    """Do not trust the cookie's claim: the database must say the user holds the active role."""
    if actor.active_role not in actor.roles:
        raise CommandError("role_forbidden", 403, "The session does not hold that role.")
    if actor.active_role in HUMAN_ROLES:
        held = session.get(UserRole, (actor.user_id, actor.active_role.value))
        if held is None:
            raise CommandError("role_forbidden", 403, "The session does not hold that role.")


def execute_command(
    session: Session,
    *,
    now: datetime,
    case_id: str,
    command: str,
    key: str,
    expected_version: int,
    payload: dict[str, Any],
    actor: Actor,
    request_id: str,
) -> Outcome:
    try:
        return _execute(
            session, now, case_id, command, key, expected_version, payload, actor, request_id
        )
    except CommandError as err:
        if err.case_version is None:
            session.rollback()
            err.case_version = session.scalars(
                select(Case.case_version).where(Case.id == case_id)
            ).first()
        raise


def _execute(
    session: Session,
    now: datetime,
    case_id: str,
    command: str,
    key: str,
    expected_version: int,
    payload: dict[str, Any],
    actor: Actor,
    request_id: str,
) -> Outcome:
    spec = REGISTRY.get(command) or SERVICE_REGISTRY.get(command)
    if spec is None:
        raise CommandError("unknown_command", 404, f"Unknown command '{command}'.")
    # 1 role
    _recheck_role(session, actor)
    check_role(spec, actor.active_role)
    # 2 schema
    try:
        model = spec.payload_model.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "payload"
        raise CommandError("schema_invalid", 422, f"{where}: {first['msg']}") from None
    case = _lock_case(session, case_id)
    body = model.model_dump(mode="json")
    req_hash = request_hash(spec.name, actor.user_id, actor.active_role, body)
    # 3 idempotency replay (before the version gate: a completed key replays even if stale)
    existing = find_key(session, key, case_id, command, req_hash)
    if existing is not None:
        out = replay(existing, now)
        session.commit()
        return out
    # 4 case version
    if expected_version != case.case_version:
        raise CommandError(
            "stale_case_version",
            409,
            "The case changed since you loaded it. Refresh and review before retrying.",
            case_version=case.case_version,
        )
    # 5-8 closed, step; policy and permission are no-op hooks for now
    gate = blocked_reason(spec, CaseState(case.state), CaseStep(case.step))
    if gate is not None:
        raise gate
    if spec.requires_policy is not None:  # stage 7
        gate = policy_gate(spec, policy_service.current_state(session, case))
        if gate is not None:
            raise gate
    # The client key must equal the server-resolved template (case, actor, payload).
    expected_key = resolve_key(
        spec,
        {
            "case_id": case.id,
            "case_version": case.case_version,
            "user_id": actor.user_id,
            **(
                policy_service.key_context(session, case)
                if "{snapshot_hash}" in spec.key_template
                else {}
            ),
            **body,
        },
    )
    if key != expected_key:
        raise CommandError(
            "idempotency_key_mismatch", 422, f"idempotency_key must be '{expected_key}'."
        )
    out = write_command(
        session,
        case,
        spec,
        model,
        key=key,
        req_hash=req_hash,
        actor_id=actor.user_id,
        actor_name=actor.name,
        actor_role=actor.active_role,
        request_id=request_id,
        now=now,
    )
    session.commit()
    return out


def write_command(
    session: Session,
    case: Case,
    spec: CommandSpec,
    model: Any,
    *,
    key: str,
    req_hash: str,
    actor_id: str,
    actor_name: str,
    actor_role: Role,
    request_id: str,
    now: datetime,
) -> Outcome:
    """Stage 9 for a locked case, shared with intake. Re-runs the closed and step gates."""
    gate = blocked_reason(spec, CaseState(case.state), CaseStep(case.step))
    if gate is not None:
        raise gate
    first_report = _first_report(session, case.id)
    if spec.name == "link_report":
        _record_linked_report(session, case, model, first_report, now)
    extra: dict[str, Any] = {}
    if spec.name in SERVICE_REGISTRY:  # evidence side effects run inside this transaction
        from vera_api.evidence import run_effect

        extra = run_effect(
            session, case, spec.name, model, now=now, actor_id=actor_id, actor_role=actor_role
        )
    ctx = ReduceContext(
        case_id=case.id,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_role=actor_role,
        now=now,
        resolve_user=_resolver(session),
        first_report_id=first_report.id if first_report else None,
        extra=extra,
    )
    if spec.name == "evaluate_policy":
        ctx.extra["policy"] = policy_service.compute(session, case).model_dump(mode="json")
    red = spec.reducer(facts_of(case), model, ctx)
    out = apply_reduction(
        session,
        case,
        spec,
        red,
        key=key,
        req_hash=req_hash,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
        now=now,
    )
    if spec.name in SERVICE_REGISTRY:  # follow-on events after the command's own event
        from vera_api.evidence import after_effect

        after_effect(
            session, case, spec.name, extra, now=now, actor_id=actor_id, actor_role=actor_role
        )
    if spec.name == "evaluate_policy":
        policy_service.store(
            session,
            case,
            PolicyResult.model_validate(ctx.extra["policy"]),
            int(out.event_ids[0][4:]),
            now,
        )
    return out


def _first_report(session: Session, case_id: str) -> Report | None:
    return session.scalars(
        select(Report)
        .where(Report.case_id == case_id)
        .order_by(Report.received_at, Report.created_at, Report.id)
    ).first()


def _record_linked_report(
    session: Session, case: Case, model: Any, original: Report | None, now: datetime
) -> None:
    """link_report creates the linked report row itself; an existing id is rejected."""
    if original is None:
        raise CommandError("case_not_openable", 409, "The case has no report to link to.")
    if session.get(Report, model.report_id) is not None:
        raise CommandError(
            "schema_invalid", 422, f"report_id: '{model.report_id}' is already a stored report."
        )
    session.add(
        Report(
            id=model.report_id,
            case_id=case.id,
            cardholder_id=original.cardholder_id,
            statement=model.statement,
            received_at=now,
        )
    )
    session.flush()
