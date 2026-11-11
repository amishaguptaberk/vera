"""Command registry: one CommandSpec per case write, plus the pure gate and action logic."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from vera_domain.enums import CaseState, CaseStep, EventType, Role
from vera_domain.errors import CommandError
from vera_domain.facts import CaseFacts, Hold
from vera_domain.labels import describe
from vera_domain.models import ActionView, BlockedAction

CLOSED_STATES = frozenset({CaseState.CLOSED, CaseState.MONITORING})
CLOSED_REASON = "The case is closed. No further actions can run."
SAFE_NOTE = "Safe to retry · the same key replays the original result"


# One definition for every edge that accepts a report id: ASCII only, bounded, no control chars.
ReportId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Z][A-Z0-9]*-[A-Za-z0-9][A-Za-z0-9_-]{0,31}$",
        max_length=64,
    ),
]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoPayload(Payload):
    pass


class HoldPayload(Payload):
    reason: str = Field(min_length=5)
    next_owner: str = Field(min_length=1)
    due: datetime | None = None


class ReassignPayload(Payload):
    to: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class LinkReportPayload(Payload):
    report_id: ReportId
    statement: str = Field(min_length=1)


@dataclass(frozen=True)
class StepSet:
    """Steps a command accepts: explicit (state, step) pairs, or any except excluded states."""

    include: frozenset[tuple[CaseState, CaseStep]] | None = None
    exclude_states: frozenset[CaseState] = frozenset()

    def allows(self, state: CaseState, step: CaseStep) -> bool:
        if state in self.exclude_states:
            return False
        return self.include is None or (state, step) in self.include


@dataclass(frozen=True)
class EventDraft:
    type: EventType
    summary: str
    record_ids: list[str]
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReduceContext:
    case_id: str
    actor_id: str
    actor_name: str
    actor_role: Role
    now: datetime
    resolve_user: Callable[[str], tuple[str, str] | None]  # ref -> (id, name)
    first_report_id: str | None


@dataclass(frozen=True)
class Reduction:
    facts: CaseFacts
    reason: str
    events: list[EventDraft]
    result: dict[str, Any]


Reducer = Callable[[CaseFacts, Any, ReduceContext], Reduction]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    roles: frozenset[Role]
    payload_model: type[Payload]
    allowed_steps: StepSet
    key_template: str
    reducer: Reducer
    events: tuple[EventType, ...]
    label: str
    style: Literal["primary", "secondary", "dark", "ghost"]


def _user(ctx: ReduceContext, ref: str, field_name: str) -> tuple[str, str]:
    found = ctx.resolve_user(ref)
    if found is None:
        raise CommandError("schema_invalid", 422, f"{field_name}: unknown user '{ref}'.")
    return found


def reduce_open(f: CaseFacts, p: NoPayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f.model_copy(update={"opened_at": ctx.now}),
        reason="Case opened",
        events=[
            EventDraft(EventType.CASE_OPENED, f"{ctx.actor_name} opened the case", [ctx.case_id])
        ],
        result={"opened": True},
    )


def reduce_hold(f: CaseFacts, p: HoldPayload, ctx: ReduceContext) -> Reduction:
    owner_id, owner_name = _user(ctx, p.next_owner, "next_owner")
    hold = Hold(
        reason=p.reason,
        next_owner_id=owner_id,
        due_at=p.due,
        held_by=ctx.actor_id,
        held_at=ctx.now,
    )
    new = f.model_copy(update={"hold": hold, "owner_id": owner_id, "due_at": p.due or f.due_at})
    return Reduction(
        facts=new,
        reason=p.reason,
        events=[
            EventDraft(
                EventType.CASE_HELD,
                f"Case put on hold, next owner {owner_name}: {p.reason}",
                [ctx.case_id],
                {"reason": p.reason, "next_owner": owner_id, "due": p.due and p.due.isoformat()},
            )
        ],
        result={"held": True, "next_owner": owner_id},
    )


def reduce_resume(f: CaseFacts, p: NoPayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f.model_copy(update={"hold": None}),
        reason="Hold cleared",
        events=[EventDraft(EventType.CASE_RESUMED, "Case resumed", [ctx.case_id])],
        result={"resumed": True},
    )


def reduce_reassign(f: CaseFacts, p: ReassignPayload, ctx: ReduceContext) -> Reduction:
    owner_id, owner_name = _user(ctx, p.to, "to")
    hold = Hold(reason=p.reason, next_owner_id=owner_id, held_by=ctx.actor_id, held_at=ctx.now)
    return Reduction(
        facts=f.model_copy(update={"hold": hold, "owner_id": owner_id}),
        reason=p.reason,
        events=[
            EventDraft(
                EventType.CASE_REASSIGNED,
                f"Case reassigned to {owner_name}: {p.reason}",
                [ctx.case_id],
                {"to": owner_id, "reason": p.reason},
            )
        ],
        result={"reassigned_to": owner_id},
    )


def reduce_link(f: CaseFacts, p: LinkReportPayload, ctx: ReduceContext) -> Reduction:
    original = ctx.first_report_id or ctx.case_id
    return Reduction(
        facts=f,
        reason="Repeat report linked to existing case",
        events=[
            EventDraft(
                EventType.REPORT_LINKED,
                f"Second report {p.report_id} linked · no new case",
                [p.report_id, original],
            )
        ],
        result={"linked_to": original},
    )


_NOT_HELD = StepSet(exclude_states=frozenset({CaseState.HELD}))
_ANY = StepSet()
_A = frozenset({Role.ANALYST})

REGISTRY: dict[str, CommandSpec] = {
    s.name: s
    for s in (
        CommandSpec(
            "open_case",
            _A,
            NoPayload,
            StepSet(include=frozenset({(CaseState.REPORTED, CaseStep.INTAKE)})),
            "open:{case_id}:{user_id}",
            reduce_open,
            (EventType.CASE_OPENED,),
            "Open case",
            "primary",
        ),
        CommandSpec(
            "hold_case",
            _A,
            HoldPayload,
            _NOT_HELD,
            "hold:{case_id}:{case_version}",
            reduce_hold,
            (EventType.CASE_HELD,),
            "Hold for more information",
            "secondary",
        ),
        CommandSpec(
            "resume_case",
            _A,
            NoPayload,
            StepSet(include=frozenset({(CaseState.HELD, CaseStep.ONHOLD)})),
            "resume:{case_id}:{case_version}",
            reduce_resume,
            (EventType.CASE_RESUMED,),
            "Resume",
            "primary",
        ),
        CommandSpec(
            "reassign_case",
            _A,
            ReassignPayload,
            _ANY,
            "reassign:{case_id}:{case_version}",
            reduce_reassign,
            (EventType.CASE_REASSIGNED,),
            "Reassign",
            "ghost",
        ),
        CommandSpec(
            "link_report",
            frozenset({Role.ANALYST, Role.CARDHOLDER}),
            LinkReportPayload,
            _ANY,
            "report:{report_id}",
            reduce_link,
            (EventType.REPORT_LINKED,),
            "Link duplicate report",
            "ghost",
        ),
    )
}


def check_role(spec: CommandSpec, active_role: Role) -> None:
    """Stage 1. The caller has already confirmed the session holds active_role."""
    if active_role not in spec.roles:
        raise CommandError(
            "role_forbidden", 403, f"The {active_role.value} role cannot run {spec.name}."
        )


def blocked_reason(spec: CommandSpec, state: CaseState, step: CaseStep) -> CommandError | None:
    """Stages 5-8 without side effects. Stage 7 (policy) and 8 (permission) are no-op hooks."""
    if state in CLOSED_STATES:
        return CommandError("case_closed", 409, CLOSED_REASON, blocked_reason=CLOSED_REASON)
    if not spec.allowed_steps.allows(state, step):
        label = describe(state, step)[0]
        reason = f"{spec.label} is not available while the case is '{label}'."
        return CommandError("invalid_step", 409, reason, blocked_reason=reason)
    return None


def resolve_key(spec: CommandSpec, ctx: Mapping[str, object]) -> str:
    """Fill the key template. Unknown fields (payload) stay literal."""

    class _Keep(dict[str, object]):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return spec.key_template.format_map(_Keep(ctx))


def available_actions(
    role: Role,
    state: CaseState,
    step: CaseStep,
    *,
    case_id: str,
    case_version: int,
    user_id: str,
    next_report_id: str,
) -> tuple[list[ActionView], list[BlockedAction]]:
    enabled: list[ActionView] = []
    blocked: list[BlockedAction] = []
    base = {"case_id": case_id, "case_version": case_version, "user_id": user_id}
    for spec in REGISTRY.values():
        if role not in spec.roles:
            continue
        err = blocked_reason(spec, state, step)
        if err is not None:
            reason = err.blocked_reason or err.message
            blocked.append(
                BlockedAction(
                    command=spec.name, label=spec.label, reason=reason, blocked_reason=reason
                )
            )
            continue
        defaults: dict[str, Any] = (
            {"report_id": next_report_id} if spec.name == "link_report" else {}
        )
        enabled.append(
            ActionView(
                command=spec.name,
                label=spec.label,
                role=role,
                style=spec.style,
                enabled=True,
                expected_state=state,
                expected_step=step,
                safe_note=SAFE_NOTE,
                idempotency_key=resolve_key(spec, {**base, **defaults}),
                payload_defaults=defaults,
                key_template=spec.key_template,
            )
        )
    return enabled, blocked
