"""Command gateway: role -> schema -> replay -> version -> closed -> step -> policy -> approval
-> key -> transaction. Every case write goes through execute_command (or apply_reduction for
intake). Feature modules plug in through register_commands, FACT_PROVIDERS and APPROVAL_PROVIDER
(docs/extension-seams.md); they never edit the gate sequence in _execute."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain import commands as domain_commands
from vera_domain.commands import (
    ApprovalBinding,
    ApprovalState,
    CommandSpec,
    ReduceContext,
    Reduction,
    approval_gate,
    blocked_reason,
    check_role,
    find_spec,
    policy_gate,
    resolve_key,
)
from vera_domain.enums import CaseState, CaseStep, Role
from vera_domain.errors import CommandError
from vera_domain.evidence import SERVICE_REGISTRY  # registers the evidence service commands
from vera_domain.facts import CaseFacts, Hold, derive_step
from vera_domain.policy import PolicyResult

from vera_api import plugins
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


@dataclass(frozen=True)
class EffectContext:
    """What an effect may read besides its arguments. `extra` is the effect's own output when
    an after-effect runs."""

    command: str
    key: str
    first_report: Report | None
    extra: dict[str, Any] = field(default_factory=dict)


# effect(session, case, actor, payload, now, ctx) -> dict: DB writes inside the command's
# transaction, BEFORE the reducer. The dict becomes ReduceContext.extra.
Effect = Callable[[Session, Case, Actor, Any, datetime, EffectContext], dict[str, Any]]
# after_effect(session, case, actor, payload, now, ctx, outcome): follow-on writes and events
# AFTER the command's own event, same transaction. ctx.extra is the effect's dict.
AfterEffect = Callable[[Session, Case, Actor, Any, datetime, EffectContext, "Outcome"], None]
# key_context(session, case, body) -> extra fields for the command's key template.
KeyContext = Callable[[Session, Case, dict[str, Any]], Mapping[str, object]]
FactProvider = Callable[[Session, Case], dict[str, Any]]
ApprovalProvider = Callable[[Session, Case], ApprovalState | None]

EFFECTS: dict[str, Effect] = {}
AFTER_EFFECTS: dict[str, AfterEffect] = {}
KEY_CONTEXTS: dict[str, KeyContext] = {}
# Each provider returns CaseFacts fields read from stored rows. Two providers may not return
# the same field.
FACT_PROVIDERS: list[FactProvider] = []
# Stage 8. None = no approval feature installed: every requires_approval command is blocked.
APPROVAL_PROVIDER: ApprovalProvider | None = None


def register_commands(
    module_name: str,
    *,
    human: Mapping[str, CommandSpec] | None = None,
    service: Mapping[str, CommandSpec] | None = None,
    effects: Mapping[str, Effect] | None = None,
    after_effects: Mapping[str, AfterEffect] | None = None,
    key_context: KeyContext | None = None,
) -> None:
    """The one call a feature module makes for its commands. Duplicate names raise at import.
    `key_context` applies to every command named in `human` and `service`."""
    domain_commands.register_commands(module_name, human=human, service=service)
    names = {*(human or {}), *(service or {})}
    _register_handlers(module_name, names, effects, after_effects)
    if key_context is not None:
        for name in names:
            KEY_CONTEXTS[name] = key_context


def _register_handlers(
    module_name: str,
    names: set[str],
    effects: Mapping[str, Effect] | None,
    after_effects: Mapping[str, AfterEffect] | None,
) -> None:
    tables: tuple[tuple[dict[str, Any], Mapping[str, Any]], ...] = (
        (EFFECTS, effects or {}),
        (AFTER_EFFECTS, after_effects or {}),
    )
    for table, handlers in tables:
        for name, handler in handlers.items():
            if name not in names:
                raise ValueError(f"{module_name}: handler for '{name}', not one of its commands")
            if name in table:
                raise ValueError(f"{module_name}: '{name}' already has a handler")
            table[name] = handler


def register_fact_provider(provider: FactProvider) -> None:
    if provider not in FACT_PROVIDERS:
        FACT_PROVIDERS.append(provider)


def set_approval_provider(provider: ApprovalProvider) -> None:
    global APPROVAL_PROVIDER
    if APPROVAL_PROVIDER is not None and APPROVAL_PROVIDER is not provider:
        raise ValueError("an approval provider is already registered")
    APPROVAL_PROVIDER = provider


def approval_state(session: Session, case: Case) -> ApprovalState | None:
    return APPROVAL_PROVIDER(session, case) if APPROVAL_PROVIDER is not None else None


def approval_binding(case: Case) -> ApprovalBinding:
    """What an approval must match: the case's current pins and its transaction."""
    return ApprovalBinding(
        snapshot_hash=case.evidence_snapshot,
        policy_version=case.policy_version,
        workflow_version=case.workflow_version,
        transaction_id=case.transaction_id,
    )


def facts_of(case: Case) -> CaseFacts:
    """Base facts from the case row only. Derive state/step from facts_for, not from this."""
    return CaseFacts(
        opened_at=case.opened_at,
        closed=case.state == CaseState.CLOSED.value,
        hold=Hold.model_validate(case.hold) if case.hold else None,
        owner_id=case.owner_id,
        due_at=case.due_at,
    )


def facts_for(session: Session, case: Case) -> CaseFacts:
    """Base facts plus every registered provider's facts (stored rows, never model output)."""
    merged: dict[str, Any] = {}
    for provider in FACT_PROVIDERS:
        for name, value in provider(session, case).items():
            if name in merged or name not in CaseFacts.model_fields:
                raise RuntimeError(
                    f"fact provider {provider.__qualname__}: bad or duplicate fact '{name}'"
                )
            merged[name] = value
    # Validate (model_copy would not): a provider returning an unknown value fails loudly.
    return CaseFacts.model_validate({**facts_of(case).model_dump(), **merged})


facts_with_runs = facts_for  # kept for existing callers


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
    spec = find_spec(command)
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
    # 5-6 closed, step
    gate = blocked_reason(spec, CaseState(case.state), CaseStep(case.step))
    if gate is not None:
        raise gate
    if spec.requires_policy is not None:  # stage 7
        gate = policy_gate(spec, policy_service.current_state(session, case))
        if gate is not None:
            raise gate
    if spec.requires_approval:  # stage 8
        gate = approval_gate(spec, approval_state(session, case), approval_binding(case))
        if gate is not None:
            raise gate
    # The client key must equal the server-resolved template (case, actor, payload).
    expected_key = resolve_key(
        spec,
        {
            "case_id": case.id,
            "case_version": case.case_version,
            "user_id": actor.user_id,
            **(KEY_CONTEXTS[spec.name](session, case, body) if spec.name in KEY_CONTEXTS else {}),
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
    actor = Actor(actor_id, actor_name, actor_role, frozenset({actor_role}))
    ectx = EffectContext(command=spec.name, key=key, first_report=first_report)
    effect = EFFECTS.get(spec.name)
    if effect is not None:  # side effects run inside this transaction, before the reducer
        ectx.extra.update(effect(session, case, actor, model, now, ectx))
    extra = ectx.extra
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
    red = spec.reducer(facts_for(session, case), model, ctx)
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
    after = AFTER_EFFECTS.get(spec.name)
    if after is not None:  # follow-on writes and events after the command's own event
        after(session, case, actor, model, now, ectx, out)
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


# --- Built-in effects, registered through the same tables feature modules use. ---


def _link_report_effect(
    session: Session, case: Case, actor: Actor, model: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    _record_linked_report(session, case, model, ctx.first_report, now)
    return {}


def _policy_effect(
    session: Session, case: Case, actor: Actor, model: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    return {"policy": policy_service.compute(session, case).model_dump(mode="json")}


def _policy_after(
    session: Session,
    case: Case,
    actor: Actor,
    model: Any,
    now: datetime,
    ctx: EffectContext,
    out: Outcome,
) -> None:
    result = PolicyResult.model_validate(ctx.extra["policy"])
    policy_service.store(session, case, result, int(out.event_ids[0][4:]), now)


def _evidence_effect(
    session: Session, case: Case, actor: Actor, model: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    from vera_api.evidence import run_effect

    return run_effect(
        session,
        case,
        ctx.command,
        model,
        now=now,
        actor_id=actor.user_id,
        actor_role=actor.active_role,
    )


def _evidence_after(
    session: Session,
    case: Case,
    actor: Actor,
    model: Any,
    now: datetime,
    ctx: EffectContext,
    out: Outcome,
) -> None:
    from vera_api.evidence import after_effect

    after_effect(
        session,
        case,
        ctx.command,
        ctx.extra,
        now=now,
        actor_id=actor.user_id,
        actor_role=actor.active_role,
    )


def _investigation_effect(
    session: Session, case: Case, actor: Actor, model: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    from vera_api import investigation

    return investigation.run_effect(session, case, ctx.command, model)


def _investigation_facts(session: Session, case: Case) -> dict[str, Any]:
    from vera_api import investigation

    return {"investigation_run_status": investigation.run_status(session, case.id)}


def _policy_keys(session: Session, case: Case, body: dict[str, Any]) -> Mapping[str, object]:
    return policy_service.key_context(session, case)


def _investigation_keys(session: Session, case: Case, body: dict[str, Any]) -> Mapping[str, object]:
    from vera_api import investigation

    return investigation.key_context(session, case, str(body.get("step_key", "")))


_INVESTIGATION = {"start_investigation", "retry_specialist_step", "complete_investigation"}
_register_handlers(
    __name__,
    {"link_report", "evaluate_policy", *SERVICE_REGISTRY, *_INVESTIGATION},
    {
        "link_report": _link_report_effect,
        "evaluate_policy": _policy_effect,
        **{name: _evidence_effect for name in SERVICE_REGISTRY},
        **{name: _investigation_effect for name in _INVESTIGATION},
    },
    {"evaluate_policy": _policy_after, **{name: _evidence_after for name in SERVICE_REGISTRY}},
)
KEY_CONTEXTS["evaluate_policy"] = _policy_keys
KEY_CONTEXTS["retry_specialist_step"] = _investigation_keys
register_fact_provider(_investigation_facts)

plugins.load_features()  # last: feature modules import this module's registration functions
