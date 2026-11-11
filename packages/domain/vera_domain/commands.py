"""Command registry: one CommandSpec per case write, plus the pure gate and action logic."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from vera_domain.enums import EVENT_TYPES, CaseState, CaseStep, EventType, Role
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


class RetryStepPayload(Payload):
    step_key: str = Field(min_length=1, max_length=64)
    mode: Literal["live", "replay"]


class CompleteInvestigationPayload(Payload):
    run_id: str = Field(min_length=1, max_length=64)


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
    type: str  # an EventType member or a string registered in enums.EVENT_TYPES
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
    extra: dict[str, Any] = field(default_factory=dict)  # service effect output, policy input


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
    events: tuple[str, ...]
    label: str
    style: Literal["primary", "secondary", "dark", "ghost"]
    # Stage 7: policy statuses under which the command may run (None = ungated).
    requires_policy: frozenset[str] | None = None
    # Stage 8: the command needs an APPROVED approval bound to the case's current pins.
    requires_approval: bool = False
    # Name of the adapter (vera_api.adapters.ADAPTERS) the command's effect dispatches to.
    adapter: str | None = None
    # One command for a human role AND a service principal. Reserved for DUAL_COMMANDS.
    dual: bool = False


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


def reduce_evaluate_policy(f: CaseFacts, p: NoPayload, ctx: ReduceContext) -> Reduction:
    result: dict[str, Any] = ctx.extra["policy"]
    return Reduction(
        facts=f,
        reason="Policy evaluated",
        events=[
            EventDraft(
                EventType.POLICY_EVALUATED,
                f"Policy v{result['policy_version']}: {result['label']}",
                list(result["evidence_used"]),
                {
                    "status": result["status"],
                    "code": result["code"],
                    "snapshot": result["snapshot_hash"],
                    "policy_version": result["policy_version"],
                    "rules_failed": result["rules_failed"],
                },
            )
        ],
        result={
            k: result[k] for k in ("status", "code", "label", "snapshot_hash", "policy_version")
        },
    )


def reduce_start_investigation(f: CaseFacts, p: NoPayload, ctx: ReduceContext) -> Reduction:
    run: dict[str, Any] = ctx.extra["run"]
    return Reduction(
        facts=f.model_copy(update={"investigation_run_status": "running"}),
        reason="Investigation started",
        events=[
            EventDraft(
                EventType.INVESTIGATION_STARTED,
                f"{ctx.actor_name} started the investigation ({run['mode']})",
                [ctx.case_id],
                dict(run),
            )
        ],
        result=dict(run),
    )


def reduce_retry_step(f: CaseFacts, p: RetryStepPayload, ctx: ReduceContext) -> Reduction:
    run: dict[str, Any] = ctx.extra["run"]
    return Reduction(
        facts=f.model_copy(update={"investigation_run_status": "running"}),
        reason=f"Specialist step {p.step_key} retried ({p.mode})",
        events=[
            EventDraft(
                EventType.SPECIALIST_RETRIED,
                f"{ctx.actor_name} retried {p.step_key} in {p.mode} mode",
                [ctx.case_id],
                dict(run),
            )
        ],
        result=dict(run),
    )


def reduce_complete_investigation(
    f: CaseFacts, p: CompleteInvestigationPayload, ctx: ReduceContext
) -> Reduction:
    status: str = ctx.extra["run_status"]
    return Reduction(
        facts=f.model_copy(update={"investigation_run_status": status}),
        reason="Investigation run completed",
        events=[
            EventDraft(
                EventType.INVESTIGATION_COMPLETED,
                "Investigation complete: specialists posted their findings",
                [ctx.case_id],
                {"run_id": p.run_id, "status": status},
            )
        ],
        result={"run_id": p.run_id, "status": status},
    )


_NOT_HELD = StepSet(exclude_states=frozenset({CaseState.HELD}))
_ANY = StepSet()
_A = frozenset({Role.ANALYST})
_WORKING = StepSet(include=frozenset({(CaseState.INVESTIGATING, CaseStep.WORKING)}))

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
        CommandSpec(
            "evaluate_policy",
            frozenset({Role.POLICY_CONTROLLER, Role.ANALYST}),
            NoPayload,
            _ANY,
            "policy:{case_id}:{snapshot_hash}:{policy_version}",
            reduce_evaluate_policy,
            (EventType.POLICY_EVALUATED,),
            "Evaluate policy",
            "ghost",
            dual=True,
        ),
        CommandSpec(
            "start_investigation",
            _A,
            NoPayload,
            StepSet(include=frozenset({(CaseState.INVESTIGATING, CaseStep.INTAKE)})),
            "inv:{case_id}",
            reduce_start_investigation,
            (EventType.INVESTIGATION_STARTED,),
            "Start investigation",
            "primary",
        ),
        CommandSpec(
            "retry_specialist_step",
            _A,
            RetryStepPayload,
            _WORKING,
            "retry:{run_id}:{step_key}:{attempt_no}",
            reduce_retry_step,
            (EventType.SPECIALIST_RETRIED,),
            "Retry specialist",
            "secondary",
        ),
    )
}

# Worker-only: recompute state/step after a run finishes. Never offered to a human role.
INVESTIGATION_SERVICE_REGISTRY: dict[str, CommandSpec] = {
    "complete_investigation": CommandSpec(
        "complete_investigation",
        frozenset({Role.SYSTEM}),
        CompleteInvestigationPayload,
        _WORKING,
        "invdone:{run_id}",
        reduce_complete_investigation,
        (EventType.INVESTIGATION_COMPLETED,),
        "Complete investigation",
        "ghost",
    )
}

# Every service-principal command (never offered to a human, never in available_actions).
SERVICE_COMMANDS: dict[str, CommandSpec] = {}
_OWNERS: dict[str, str] = {}
HUMAN_ROLES = frozenset(
    {Role.ANALYST, Role.OPS_ADMIN, Role.REVIEWER, Role.CARD_ADMIN, Role.CARDHOLDER}
)
# The only commands a human role and a service principal share (the analyst and the Policy
# Controller both evaluate policy). Do not add to this without a security review.
DUAL_COMMANDS = frozenset({"evaluate_policy"})


def check_spec_roles(module_name: str, spec: CommandSpec, *, service: bool) -> None:
    """A service command lists NO human role; a human command lists ONLY human roles."""
    if spec.dual:
        if service or spec.name not in DUAL_COMMANDS:
            raise ValueError(f"{module_name}: '{spec.name}' may not be dual (DUAL_COMMANDS)")
        return
    if not spec.roles:
        raise ValueError(f"{module_name}: command '{spec.name}' lists no role")
    wrong = sorted(
        r.value for r in (spec.roles & HUMAN_ROLES if service else spec.roles - HUMAN_ROLES)
    )
    if wrong:
        kind, other = ("service", "human") if service else ("human", "service")
        raise ValueError(
            f"{module_name}: {kind} command '{spec.name}' lists {other} role(s) {wrong}"
        )


for _spec in REGISTRY.values():  # the built-in human commands obey the same rule
    check_spec_roles(__name__, _spec, service=False)


def register_commands(
    module_name: str,
    *,
    human: Mapping[str, CommandSpec] | None = None,
    service: Mapping[str, CommandSpec] | None = None,
) -> None:
    """Add a module's commands. `human` commands go through the same gates and appear in
    available_actions; `service` commands are for service principals only. A name registered
    twice (by any module, in either table) raises at import."""
    for table, specs in ((REGISTRY, human or {}), (SERVICE_COMMANDS, service or {})):
        for name, spec in specs.items():
            if name != spec.name:
                raise ValueError(f"{module_name}: key '{name}' != spec name '{spec.name}'")
            if name in REGISTRY or name in SERVICE_COMMANDS:
                owner = _OWNERS.get(name, "vera_domain.commands")
                raise ValueError(f"{module_name}: command '{name}' already registered by {owner}")
            unknown = [e for e in spec.events if str(e) not in EVENT_TYPES]
            if unknown:
                raise ValueError(f"{module_name}: {name} declares unregistered events {unknown}")
            check_spec_roles(module_name, spec, service=table is SERVICE_COMMANDS)
    # Nothing is registered unless every spec in the call is valid.
    for table, specs in ((REGISTRY, human or {}), (SERVICE_COMMANDS, service or {})):
        for name, spec in specs.items():
            if name in REGISTRY or name in SERVICE_COMMANDS:  # same name in human and service
                raise ValueError(f"{module_name}: command '{name}' registered twice")
            table[name] = spec
            _OWNERS[name] = module_name


def find_spec(command: str) -> CommandSpec | None:
    return REGISTRY.get(command) or SERVICE_COMMANDS.get(command)


register_commands("vera_domain.commands", service=INVESTIGATION_SERVICE_REGISTRY)

RECOVERY_ONLY = frozenset({"retry_specialist_step"})
RETRY_NOTE = (
    "mode 'live' calls the model again; mode 'replay' uses the recorded reference output and "
    "the step is labeled Replayed result"
)


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


@dataclass(frozen=True)
class PolicyState:
    """Latest stored evaluation for the case's current snapshot (None = never evaluated)."""

    status: str
    label: str


NOT_EVALUATED = "Policy has not been evaluated on the current evidence."


def policy_gate(spec: CommandSpec, current: PolicyState | None) -> CommandError | None:
    """Stage 7, pure: shared by the gateway and available_actions."""
    if spec.requires_policy is None:
        return None
    if current is None:
        return CommandError("policy_blocked", 422, NOT_EVALUATED, blocked_reason=NOT_EVALUATED)
    if current.status not in spec.requires_policy:
        return CommandError("policy_blocked", 422, current.label, blocked_reason=current.label)
    return None


@dataclass(frozen=True)
class ApprovalBinding:
    """What an approval must be bound to: the case's CURRENT pins and transaction."""

    snapshot_hash: str
    policy_version: int
    workflow_version: int
    transaction_id: str


@dataclass(frozen=True)
class ApprovalState(ApprovalBinding):
    """The case's latest approval as stored (stage 8 reads this through APPROVAL_PROVIDER)."""

    approval_id: str = ""
    status: str = "requested"  # requested | approved | returned | stale


NO_APPROVAL = "No approval recorded"
APPROVAL_STALE = (
    "Approval out of date: the evidence, policy, workflow or transaction changed after approval."
)


def approval_gate(
    spec: CommandSpec, current: ApprovalState | None, binding: ApprovalBinding | None
) -> CommandError | None:
    """Stage 8, pure: shared by the gateway and available_actions. Blocks unless an APPROVED
    approval is bound to the current snapshot, policy version, workflow version, transaction."""
    if not spec.requires_approval:
        return None
    if current is None or binding is None:
        return CommandError("approval_required", 422, NO_APPROVAL, blocked_reason=NO_APPROVAL)
    if current.status == "stale":
        return CommandError("approval_stale", 409, APPROVAL_STALE, blocked_reason=APPROVAL_STALE)
    if current.status != "approved":
        reason = f"Approval {current.approval_id} is {current.status}, not approved."
        return CommandError("approval_required", 422, reason, blocked_reason=reason)
    bound = ApprovalBinding(
        current.snapshot_hash,
        current.policy_version,
        current.workflow_version,
        current.transaction_id,
    )
    if bound != binding:
        return CommandError("approval_stale", 409, APPROVAL_STALE, blocked_reason=APPROVAL_STALE)
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
    policy_state: PolicyState | None = None,
    key_context: Mapping[str, object] | None = None,
    approval: ApprovalState | None = None,
    approval_binding: ApprovalBinding | None = None,
) -> tuple[list[ActionView], list[BlockedAction]]:
    enabled: list[ActionView] = []
    blocked: list[BlockedAction] = []
    base = {
        "case_id": case_id,
        "case_version": case_version,
        "user_id": user_id,
        **(key_context or {}),
    }
    for spec in REGISTRY.values():
        if role not in spec.roles or spec.name in RECOVERY_ONLY:
            continue
        err = (
            blocked_reason(spec, state, step)
            or policy_gate(spec, policy_state)
            or approval_gate(spec, approval, approval_binding)
        )
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


@dataclass(frozen=True)
class FailedStep:
    run_id: str
    step_key: str
    attempt_no: int  # the next retry attempt for this step
    mode: str  # the run's pinned mode, offered as the default


def recovery_actions(
    role: Role,
    state: CaseState,
    step: CaseStep,
    *,
    case_id: str,
    case_version: int,
    failed_steps: Sequence[FailedStep],
) -> list[ActionView]:
    """Plan §18: a failed specialist step offers retry_specialist_step and hold_case."""
    if not failed_steps or role is not Role.ANALYST:
        return []
    out: list[ActionView] = []
    retry = REGISTRY["retry_specialist_step"]
    if blocked_reason(retry, state, step) is None:
        for fs in failed_steps:
            defaults = {"step_key": fs.step_key, "mode": fs.mode}
            out.append(
                ActionView(
                    command=retry.name,
                    label=f"{retry.label}: {fs.step_key}",
                    role=role,
                    style=retry.style,
                    enabled=True,
                    expected_state=state,
                    expected_step=step,
                    safe_note=SAFE_NOTE,
                    confirm=RETRY_NOTE,
                    idempotency_key=resolve_key(
                        retry,
                        {"run_id": fs.run_id, "attempt_no": fs.attempt_no, **defaults},
                    ),
                    payload_defaults=defaults,
                    key_template=retry.key_template,
                )
            )
    hold = REGISTRY["hold_case"]
    if blocked_reason(hold, state, step) is None:
        out.append(
            ActionView(
                command=hold.name,
                label=hold.label,
                role=role,
                style=hold.style,
                enabled=True,
                expected_state=state,
                expected_step=step,
                safe_note=SAFE_NOTE,
                idempotency_key=resolve_key(
                    hold, {"case_id": case_id, "case_version": case_version}
                ),
                payload_defaults={},
                key_template=hold.key_template,
            )
        )
    return out
