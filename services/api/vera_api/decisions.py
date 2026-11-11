"""Decision packet, decision, reviewer approval (bound to snapshot/policy/workflow) and Ask Vera."""

from collections.abc import Iterator
from datetime import datetime
from types import ModuleType
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from vera_domain import decisions as d
from vera_domain.clock import Clock
from vera_domain.commands import ApprovalState
from vera_domain.enums import EventType
from vera_domain.errors import CommandError
from vera_domain.specialists import ExecutionMode, StepStatus

from vera_api import auth, evidence, gateway, plugins
from vera_api import policy as policy_service
from vera_api.auth import Actor
from vera_api.config import Settings
from vera_api.gateway import EffectContext
from vera_api.model_client import PROBE_TOOL, default_mode
from vera_api.models import Case, IdempotencyKey, User
from vera_api.models_decisions import (
    Approval,
    AskPair,
    Decision,
    DecisionPacket,
    DecisionPacketContent,
)
from vera_api.models_runs import WorkflowRun, WorkflowStep
from vera_api.runner import SpecialistRunner, create_run
from vera_api.worker import Touch, enqueue, register


# vera_api.investigation and vera_api.evidence both import the gateway, which loads this feature:
# import investigation on use and define the route dependencies here to avoid a circular import.
def _inv() -> ModuleType:
    from vera_api import investigation

    return investigation


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def _actor(request: Request, session: Annotated[Session, Depends(_session)]) -> Actor:
    settings: Settings = request.app.state.settings
    return auth.load_actor(
        session, settings.secret(), request.cookies.get(auth.COOKIE), settings.synthetic
    )


DbSession = Annotated[Session, Depends(_session)]
ReaderDep = Annotated[Actor, Depends(_actor)]

DEFAULT_REVIEWER = "usr-dana-okafor"
JOB_KIND = "decision_packet_preparer"

# ---- reads (the credit stage uses current_decision / latest_approval) ---------------------------


def latest_packet(session: Session, case_id: str) -> DecisionPacket | None:
    stmt = select(DecisionPacket).where(DecisionPacket.case_id == case_id)
    return session.scalars(stmt.order_by(DecisionPacket.version.desc())).first()


def packet_content(session: Session, case_id: str, version: int) -> DecisionPacketContent | None:
    return session.scalars(
        select(DecisionPacketContent).where(
            DecisionPacketContent.case_id == case_id,
            DecisionPacketContent.packet_version == version,
        )
    ).first()


def current_decision(session: Session, case_id: str) -> Decision | None:
    """The decision recorded on the CURRENT packet version (None once a new packet replaces it)."""
    packet = latest_packet(session, case_id)
    if packet is None:
        return None
    stmt = select(Decision).where(
        Decision.case_id == case_id, Decision.packet_version == packet.version
    )
    return session.scalars(stmt.order_by(Decision.id.desc())).first()


def latest_approval(session: Session, case_id: str) -> Approval | None:
    """The approval of the CURRENT packet version (an older packet's approval is superseded)."""
    packet = latest_packet(session, case_id)
    if packet is None:
        return None
    stmt = select(Approval).where(
        Approval.case_id == case_id, Approval.packet_version == packet.version
    )
    return session.scalars(stmt).first()


def _facts(session: Session, case: Case) -> dict[str, Any]:
    packet = latest_packet(session, case.id)
    decision = current_decision(session, case.id)
    approval = latest_approval(session, case.id)
    return {
        "packet_status": "none"
        if packet is None
        else ("ready" if packet_content(session, case.id, packet.version) else "draft"),
        "decision": decision.decision if decision else "none",
        "approval_status": approval.status if approval else "none",
    }


def _approval_provider(session: Session, case: Case) -> ApprovalState | None:
    row = latest_approval(session, case.id)
    if row is None:
        return None
    return ApprovalState(
        snapshot_hash=row.snapshot_hash,
        policy_version=row.policy_version,
        workflow_version=row.workflow_version,
        transaction_id=row.transaction_id,
        approval_id=row.id,
        status=row.status,
    )


def _mark_stale(session: Session, case: Case, snapshot: str) -> list[str]:
    """evidence.STALE_APPROVAL_HOOKS: a material change invalidates the bound approval."""
    row = latest_approval(session, case.id)
    if (
        row is None
        or row.status not in ("requested", "approved")
        or row.consumed_at is not None
        or row.snapshot_hash == case.evidence_snapshot
    ):
        return []
    row.status = "stale"
    session.flush()
    return [row.id]


def mark_approval_consumed(
    session: Session, approval_id: str, execution_id: str, now: datetime | None = None
) -> None:
    """Called by the credit stage in its own transaction once a credit execution exists for the
    approval. Only an `approved` approval can be consumed; a consumed approval never goes stale.
    Idempotent for the same execution."""
    row = session.get(Approval, approval_id, with_for_update=True)
    if row is None or row.status != "approved":
        raise CommandError("approval_required", 422, "No approved approval to consume.")
    if row.consumed_at is not None:
        if row.consumed_execution_id != str(execution_id):
            raise CommandError("approval_consumed", 409, "The approval was already used.")
        return
    row.consumed_at = now or datetime.now().astimezone()
    row.consumed_execution_id = str(execution_id)
    session.flush()


# ---- effects ------------------------------------------------------------------------------------


def _need(row: Any, what: str) -> Any:
    if row is None:
        raise CommandError("precondition_failed", 422, f"No {what} for this case.")
    return row


def _summary(session: Session, case: Case) -> dict[str, Any]:
    """The code-computed part of the packet (conflicts, gaps, stored policy result)."""
    ev = evidence.get_evidence_summary(session, case.id)
    view = policy_service.latest_view(session, case.id)
    return {
        "open_conflicts": [c.model_dump(mode="json") for c in ev.open_conflicts],
        "missing": list(ev.missing),
        "policy": view.model_dump(mode="json") if view else None,
    }


def _create_packet(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    prior = latest_packet(session, case.id)
    snapshot = case.evidence_snapshot
    evaluation = policy_service._latest(session, case.id)
    try:
        mode = default_mode()
    except (RuntimeError, ValueError) as exc:
        raise CommandError("execution_mode_unset", 503, str(exc)) from None
    run_id = create_run(session, case_id=case.id, mode=mode, now=now, commit=False)
    row = DecisionPacket(
        case_id=case.id,
        version=(prior.version if prior else 0) + 1,
        snapshot_hash=snapshot,
        workflow_version=case.workflow_version,
        policy_version=case.policy_version,
        policy_evaluation_id=evaluation.id if evaluation else None,
        summary=_summary(session, case),
        run_id=run_id,
        created_by=actor.user_id,
        created_at=now,
    )
    session.add(row)
    session.flush()
    job_id = enqueue(session, JOB_KIND, _job(row, mode.value), now=now)
    return {
        "packet_version": row.version,
        "snapshot_hash": row.snapshot_hash,
        "policy_version": row.policy_version,
        "workflow_version": row.workflow_version,
        "run_id": run_id,
        "job_id": job_id,
        "mode": mode.value,
    }


def _job(packet: DecisionPacket, mode: str) -> dict[str, Any]:
    return {
        "case_id": packet.case_id,
        "packet_version": packet.version,
        "run_id": packet.run_id,
        "mode": mode,
    }


def _retries(session: Session, case_id: str, version: int) -> int:
    return int(
        session.scalars(
            select(func.count())
            .select_from(IdempotencyKey)
            .where(IdempotencyKey.key.like(f"packet-retry:{case_id}:{version}:%"))
        ).one()
    )


def _retry_packet(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    """Explicit recovery: rerun the failed preparer step live or from the recording."""
    packet = latest_packet(session, case.id)
    step = session.get(WorkflowStep, (packet.run_id, d.PREPARER)) if packet else None
    if (
        packet is None
        or packet_content(session, case.id, packet.version) is not None
        or step is None
        or step.status != StepStatus.FAILED.value
    ):
        reason = "The decision packet has no failed preparation step to retry."
        raise CommandError("invalid_step", 409, reason, blocked_reason=reason)
    job_id = enqueue(session, JOB_KIND, _job(packet, p.mode), now=now)
    return {
        "packet_version": packet.version,
        "run_id": packet.run_id,
        "mode": p.mode,
        "job_id": job_id,
        "prior_failure": step.failure_reason,
    }


def _complete_packet(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    """Stores the runner's VALIDATED step output (never text passed by the caller)."""
    packet = session.scalars(
        select(DecisionPacket).where(
            DecisionPacket.case_id == case.id, DecisionPacket.version == p.packet_version
        )
    ).first()
    if packet is None or packet.run_id != p.run_id:
        raise CommandError("packet_not_found", 404, "No such decision packet run.")
    step = session.get(WorkflowStep, (p.run_id, d.PREPARER))
    if step is None or step.output is None:
        raise CommandError("precondition_failed", 422, "The preparer has no validated output.")
    out = d.PacketOutput.model_validate(step.output)
    if packet_content(session, case.id, packet.version) is None:
        session.add(
            DecisionPacketContent(
                case_id=case.id,
                packet_version=packet.version,
                run_id=p.run_id,
                execution_mode=step.execution_mode,
                model_id=step.model_id,
                statements=[x.model_dump(mode="json") for x in out.statements],
                recommendation=out.recommendation,
                reasons=[x.model_dump(mode="json") for x in out.reasons],
                created_at=now,
            )
        )
        session.flush()
    return {
        "packet_version": packet.version,
        "run_id": p.run_id,
        "recommendation": out.recommendation,
        "execution_mode": step.execution_mode,
    }


# ---- worker: the Decision Packet Preparer on the shared SpecialistRunner -----------------------


def packet_input(session: Session, case_id: str) -> tuple[d.PacketInput, frozenset[str]]:
    register_ = _inv()._register(session, case_id)
    ev = evidence.get_evidence_summary(session, case_id)
    view = policy_service.latest_view(session, case_id)
    inputs = d.PacketInput(
        case_id=case_id,
        records={
            rid: d.RecordInfo(kind=kind, fields=sorted(fields))
            for rid, (kind, fields) in sorted(register_.items())
        },
        open_conflict_fields=sorted({str(c.field) for c in ev.open_conflicts}),
        open_finding_ids=sorted({str(i) for c in ev.open_conflicts for i in [c.finding_id]}),
        missing=list(ev.missing),
        policy_status=view.status if view else None,
        policy_code=view.code if view else None,
        policy_rules_failed=list(view.rules_failed) if view else [],
    )
    return inputs, frozenset(register_)


@register(JOB_KIND)
def run_packet_job(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    case_id, version = str(payload["case_id"]), int(payload["packet_version"])
    run_id, mode = str(payload["run_id"]), ExecutionMode(str(payload["mode"]))
    session.rollback()
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        if packet_content(s, case_id, version) is not None:
            return  # a re-delivered job repeats nothing
        inputs, record_ids = packet_input(s, case_id)
        s.rollback()

        def apply(output: Any) -> None:
            _inv()._execute_retrying(
                factory,
                case_id,
                "complete_decision_packet",
                f"packet-done:{case_id}:{version}",
                {"packet_version": version, "run_id": run_id},
                _inv().SYSTEM,
            )

        runner = SpecialistRunner(_inv().client_for, _inv()._reader(s, case_id), _inv()._clock())
        outcome = runner.run_step(
            s, run_id, d.PREPARER, d.build_packet_spec(record_ids), inputs, mode, apply, touch
        )
    if outcome.status != StepStatus.SUCCEEDED.value:
        # Explicit failure: the packet stays `draft` (step `packet`) until an analyst retries.
        reason = outcome.failure_reason or "failed"
        _inv()._emit_once(
            factory,
            case_id,
            EventType.SPECIALIST_FAILED,
            run_id,
            d.PREPARER,
            f"{d.PREPARER} failed: {reason}. Retry live or replay.",
            {"reason": reason, "attempt": outcome.attempts, "mode": mode.value},
        )
        return
    _inv()._finish(factory, run_id, "succeeded")


def dump_request(session: Session, case_id: str, root: Any) -> Any:
    """Request file for capturing a real recording on a networked machine."""
    import json
    from pathlib import Path

    inputs, record_ids = packet_input(session, case_id)
    spec = d.build_packet_spec(record_ids)
    path = Path(root) / d.PREPARER / d.PROMPT_VERSION / f"{case_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "messages": spec.build_messages(inputs),
        "response_schema": spec.output_schema.model_json_schema(),
        "tools": [PROBE_TOOL],
    }
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return path


def _record_decision(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    packet = _need(latest_packet(session, case.id), "decision packet")
    state = policy_service.current_state(session, case)
    if state is None or state.status not in d.DECISION_POLICY[p.decision]:
        label = state.label if state else "Policy has not been evaluated on the current evidence."
        raise CommandError("policy_blocked", 422, label, blocked_reason=label)
    session.add(
        Decision(
            case_id=case.id,
            packet_version=packet.version,
            decision=p.decision,
            rationale=p.rationale,
            decided_by=actor.user_id,
            decided_at=now,
        )
    )
    session.flush()
    return {"packet_version": packet.version, "decision": p.decision}


def _binding(row: Approval) -> dict[str, Any]:
    return {
        "approval_id": row.id,
        "case_id": row.case_id,
        "transaction_id": row.transaction_id,
        "packet_version": row.packet_version,
        "snapshot_hash": row.snapshot_hash,
        "policy_version": row.policy_version,
        "workflow_version": row.workflow_version,
        "status": row.status,
        "reviewer_id": row.reviewer_id,
    }


def _request_approval(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    packet = _need(latest_packet(session, case.id), "decision packet")
    decision = current_decision(session, case.id)
    if decision is None or decision.decision != "credit":
        reason = "Record a credit decision before requesting reviewer approval."
        raise CommandError("decision_required", 422, reason, blocked_reason=reason)
    if packet.snapshot_hash != case.evidence_snapshot:
        reason = "The packet is out of date. Prepare a new version."
        raise CommandError("packet_stale", 422, reason, blocked_reason=reason)
    row = Approval(
        id=f"APR-{case.id}-{packet.version}",
        case_id=case.id,
        transaction_id=case.transaction_id,
        packet_version=packet.version,
        snapshot_hash=packet.snapshot_hash,
        policy_version=packet.policy_version,
        workflow_version=packet.workflow_version,
        status="requested",
        reviewer_id=DEFAULT_REVIEWER,
        requested_by=actor.user_id,
        requested_at=now,
    )
    session.add(row)
    session.flush()
    return _binding(row)


def _approve(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row: Approval = _need(latest_approval(session, case.id), "approval request")
    if (
        row.status == "stale"
        or row.snapshot_hash != case.evidence_snapshot
        or row.policy_version != case.policy_version
        or row.workflow_version != case.workflow_version
    ):
        reason = "The evidence changed after this packet was prepared. The approval is out of date."
        raise CommandError("approval_stale", 422, reason, blocked_reason=reason)
    if row.status != "requested":
        raise CommandError("precondition_failed", 422, f"The approval is already {row.status}.")
    row.status, row.decided_by, row.decided_at = "approved", actor.user_id, now
    session.flush()
    return _binding(row)


def _return(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row: Approval = _need(latest_approval(session, case.id), "approval request")
    owner = session.get(User, p.owner)
    if owner is None:
        raise CommandError("schema_invalid", 422, f"owner: unknown user '{p.owner}'.")
    row.status, row.decided_by, row.decided_at = "returned", actor.user_id, now
    row.return_reason, row.return_next_step, row.return_owner_id = p.reason, p.next_step, owner.id
    session.flush()
    return {
        **_binding(row),
        "reason": p.reason,
        "next_step": p.next_step,
        "owner_id": owner.id,
    }


def _remind(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    return _binding(_need(latest_approval(session, case.id), "approval request"))


def _reassign(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row: Approval = _need(latest_approval(session, case.id), "approval request")
    user = session.get(User, p.to)
    if user is None:
        raise CommandError("schema_invalid", 422, f"to: unknown user '{p.to}'.")
    row.reviewer_id = user.id
    session.flush()
    return _binding(row)


def _keys(session: Session, case: Case, body: dict[str, Any]) -> dict[str, object]:
    packet = latest_packet(session, case.id)
    approval = latest_approval(session, case.id)
    version = packet.version if packet else 0
    return {
        "packet_version": version,
        "approval_id": approval.id if approval else "none",
        "attempt_no": _retries(session, case.id, version) + 1,
    }


gateway.register_commands(
    __name__,
    human={c.name: c for c in d.COMMANDS},
    service={d.COMPLETE_PACKET.name: d.COMPLETE_PACKET},
    effects={
        "retry_decision_packet": _retry_packet,
        "complete_decision_packet": _complete_packet,
        "create_decision_packet": _create_packet,
        "record_decision": _record_decision,
        "request_reviewer_approval": _request_approval,
        "approve_decision": _approve,
        "return_decision": _return,
        "remind_reviewer": _remind,
        "reassign_reviewer": _reassign,
    },
    key_context=_keys,
)


# ---- what the case view offers: the same preconditions the effects check -------------------------


def _failed_preparer(session: Session, case: Case) -> WorkflowStep | None:
    packet = latest_packet(session, case.id)
    if packet is None or packet_content(session, case.id, packet.version) is not None:
        return None
    step = session.get(WorkflowStep, (packet.run_id, d.PREPARER))
    return step if step is not None and step.status == StepStatus.FAILED.value else None


def _no_failed_preparer(session: Session, case: Case) -> CommandError | None:
    if _failed_preparer(session, case) is None:
        reason = "The decision packet has no failed preparation step to retry."
        return gateway.blocked("invalid_step", reason)
    return None


def _retry_defaults(session: Session, case: Case) -> dict[str, Any]:
    step = _failed_preparer(session, case)
    run = session.get(WorkflowRun, step.run_id) if step is not None else None
    return {"mode": run.mode} if run is not None else {}


def _approval_not_ready(session: Session, case: Case) -> CommandError | None:
    packet = latest_packet(session, case.id)
    decision = current_decision(session, case.id)
    if packet is None or decision is None or decision.decision != "credit":
        reason = "Record a credit decision before requesting reviewer approval."
        return gateway.blocked("decision_required", reason)
    if packet.snapshot_hash != case.evidence_snapshot:
        return gateway.blocked("packet_stale", "The packet is out of date. Prepare a new version.")
    return None


def _not_approvable(session: Session, case: Case) -> CommandError | None:
    row = latest_approval(session, case.id)
    if row is None:
        return gateway.blocked("precondition_failed", "No approval request for this case.")
    if (
        row.status == "stale"
        or row.snapshot_hash != case.evidence_snapshot
        or row.policy_version != case.policy_version
        or row.workflow_version != case.workflow_version
    ):
        reason = "The evidence changed after this packet was prepared. The approval is out of date."
        return gateway.blocked("approval_stale", reason)
    if row.status != "requested":
        return gateway.blocked("precondition_failed", f"The approval is already {row.status}.")
    return None


gateway.register_actions(
    __name__,
    defaults={"retry_decision_packet": _retry_defaults},
    guards={
        "retry_decision_packet": _no_failed_preparer,
        "request_reviewer_approval": _approval_not_ready,
        "approve_decision": _not_approvable,
    },
    hidden_when_refused=["retry_decision_packet"],
)
gateway.register_fact_provider(_facts)
gateway.set_approval_provider(_approval_provider)
if _mark_stale not in evidence.STALE_APPROVAL_HOOKS:
    evidence.STALE_APPROVAL_HOOKS.append(_mark_stale)
plugins.register_reset_tables(
    ["ask_pairs", "approvals", "decisions", "decision_packet_contents", "decision_packets"]
)

# ---- routes -------------------------------------------------------------------------------------


class ApprovalView(BaseModel):
    approval_id: str
    case_id: str
    transaction_id: str
    packet_version: int
    snapshot_hash: str
    policy_version: int
    workflow_version: int
    status: str
    reviewer_id: str
    return_reason: str | None = None
    return_next_step: str | None = None
    return_owner_id: str | None = None


class CitedRecord(BaseModel):
    record_id: str
    kind: str
    version: int
    fields: dict[str, Any]  # only the fields the packet cites


class PacketAction(BaseModel):
    command: str
    label: str
    idempotency_key: str


class PacketStatement(BaseModel):
    text: str
    citations: list[d.Citation]


class PreparerView(BaseModel):
    run_id: str
    status: str  # running | failed | succeeded
    execution_mode: str | None
    model_id: str | None
    failure_reason: str | None


class DecisionPacketView(BaseModel):
    case_id: str
    version: int
    latest_version: int
    current: bool  # false when the case's evidence snapshot moved on
    snapshot_hash: str
    workflow_version: int
    policy_version: int
    policy_evaluation_id: int | None
    packet_status: str  # draft (being prepared or failed) | ready
    preparer: PreparerView
    statements: list[PacketStatement]
    recommendation: str | None  # Vera's recommendation; the analyst decides
    recommendation_reasons: list[PacketStatement]
    open_conflicts: list[dict[str, Any]]
    missing: list[str]
    policy: dict[str, Any] | None
    decision: str | None
    approval: ApprovalView | None
    cited_records: list[CitedRecord]  # the evidence this packet cites, nothing else
    actions: list[PacketAction]  # packet commands the server offers the caller's role now
    created_by: str
    created_at: datetime


class AskIn(BaseModel):
    text: str
    role: str | None = None  # informational: the session's active role is authoritative
    last_intent: str | None = None


class AskAction(BaseModel):
    """A button to render. Never auto-run; a command is one the server offers this role now."""

    kind: str  # navigate | command
    label: str
    target: str | None = None
    command: str | None = None


class AskOut(BaseModel):
    intent: str
    title: str
    paragraphs: list[str]
    cites: list[d.Citation]
    actions: list[AskAction]
    signature: str


router = APIRouter(prefix="/api")


@router.get("/cases/{case_id}/decision-packet")
def get_decision_packet(
    case_id: str,
    request: Request,
    session: DbSession,
    actor: ReaderDep,
    version: int | None = None,
) -> DecisionPacketView:
    evidence._require_reader(actor)
    case = evidence._case(session, case_id)
    latest = latest_packet(session, case_id)
    row = latest
    if version is not None:
        row = session.scalars(
            select(DecisionPacket).where(
                DecisionPacket.case_id == case_id, DecisionPacket.version == version
            )
        ).first()
    if row is None or latest is None:
        raise CommandError("packet_not_found", 404, "No decision packet for this case.")
    decision = session.scalars(
        select(Decision)
        .where(Decision.case_id == case_id, Decision.packet_version == row.version)
        .order_by(Decision.id.desc())
    ).first()
    approval = session.scalars(
        select(Approval).where(Approval.case_id == case_id, Approval.packet_version == row.version)
    ).first()
    s = row.summary
    content = packet_content(session, case_id, row.version)
    step = session.get(WorkflowStep, (row.run_id, d.PREPARER))

    def cited(items: list[Any]) -> list[PacketStatement]:
        return [
            PacketStatement(
                text=x["statement"],
                citations=[
                    d.Citation(record_id=c["record_id"], version=c["version"], field=c["field"])
                    for c in x["citations"]
                ],
            )
            for x in items
        ]

    return DecisionPacketView(
        case_id=case_id,
        version=row.version,
        latest_version=latest.version,
        current=row.version == latest.version and row.snapshot_hash == case.evidence_snapshot,
        snapshot_hash=row.snapshot_hash,
        workflow_version=row.workflow_version,
        policy_version=row.policy_version,
        policy_evaluation_id=row.policy_evaluation_id,
        packet_status="ready" if content else "draft",
        preparer=PreparerView(
            run_id=row.run_id,
            status="succeeded" if content else (step.status if step else "running"),
            execution_mode=step.execution_mode if step else None,
            model_id=step.model_id if step else None,
            failure_reason=step.failure_reason if step and not content else None,
        ),
        statements=cited(content.statements) if content else [],
        recommendation=content.recommendation if content else None,
        recommendation_reasons=cited(content.reasons) if content else [],
        open_conflicts=s["open_conflicts"],
        missing=s["missing"],
        policy=s["policy"],
        decision=decision.decision if decision else None,
        cited_records=_cited_records(session, case_id, content),
        actions=[
            PacketAction(command=a.command, label=a.label, idempotency_key=a.idempotency_key)
            for name, a in _offered(request, session, case_id, actor).items()
            if name in PACKET_COMMANDS
        ],
        approval=ApprovalView(
            **_binding(approval),
            return_reason=approval.return_reason,
            return_next_step=approval.return_next_step,
            return_owner_id=approval.return_owner_id,
        )
        if approval
        else None,
        created_by=row.created_by,
        created_at=row.created_at,
    )


PACKET_COMMANDS = frozenset(c.name for c in d.COMMANDS)


def _cited_records(
    session: Session, case_id: str, content: DecisionPacketContent | None
) -> list[CitedRecord]:
    if content is None:
        return []
    wanted: dict[str, set[str]] = {}
    for part in (*content.statements, *content.reasons):
        for c in part["citations"]:
            wanted.setdefault(c["record_id"], set()).add(c["field"])
    return [
        CitedRecord(
            record_id=r.record_id,
            kind=r.kind,
            version=r.current_version,
            fields={k: v for k, v in r.fields.items() if k in wanted[r.record_id]},
        )
        for r in evidence.get_evidence_summary(session, case_id).records
        if r.record_id in wanted
    ]


def _cite(session: Session, case_id: str, record_id: str, field: str) -> list[d.Citation]:
    """One statement's source: a field of a record in THIS case's register, current version."""
    for r in evidence.get_evidence_summary(session, case_id).records:
        if r.record_id == record_id and field in r.fields:
            return [d.Citation(record_id=record_id, version=r.current_version, field=field)]
    return []


def _offered(request: Request, session: Session, case_id: str, actor: Actor) -> dict[str, Any]:
    """Commands the server currently offers this role (never more)."""
    from vera_api import queries

    view = queries.get_case_view(
        session,
        case_id,
        request.app.state.clock.now(),
        request.app.state.settings.demo_tz,
        (actor.user_id, actor.active_role),
    )
    return {a.command: a for a in view.available_actions if a.enabled}


def _closure_items(session: Session, case: Case) -> list[str]:
    facts = gateway.facts_for(session, case)
    items: list[str] = []
    conflicts = len(evidence.get_evidence_summary(session, case.id).open_conflicts)
    if conflicts:
        items.append(f"Open evidence conflicts: {conflicts}.")
    if facts.decision == "none":
        items.append("The decision is not recorded.")
    if facts.approval_status in ("requested", "returned", "stale"):
        items.append(f"Reviewer approval is {facts.approval_status}.")
    if facts.final_message_status != "sent":
        items.append("The final cardholder update is not sent.")
    return items


def _answer(
    session: Session, case: Case, intent: str, offered: dict[str, Any]
) -> tuple[str, list[str], list[d.Citation], list[AskAction]]:
    view = policy_service.latest_view(session, case.id)
    approval = latest_approval(session, case.id)
    open_decision = AskAction(kind="navigate", label="Open decision", target="decision")
    commands = [
        AskAction(kind="command", label=offered[name].label, command=name)
        for name in ("approve_decision", "return_decision")
        if name in offered
    ]
    profile = {
        r.record_id: r.fields for r in evidence.get_evidence_summary(session, case.id).records
    }.get("PRF-4418", {})
    name, phone = profile.get("name"), profile.get("phone")
    policy_cites = [
        c
        for rid in (view.evidence_used if view else [])[:3]
        for c in _first_field(session, case.id, str(rid))
    ]
    if intent == "approve":
        return "Approval", [d.REFUSAL], [], [open_decision, *commands]
    if intent in ("issue_credit", "credit_eligible"):
        if case.credit_status == "issued":
            return "Credit", [d.CREDIT_ISSUED], [], []
        if view is not None and view.status == "eligible":
            return "Credit", [d.CREDIT_NEEDS_APPROVAL], policy_cites, [open_decision]
        label = view.label if view else "Policy has not been evaluated on the current evidence."
        return "Credit", [f"Credit is not available: {label}"], policy_cites, []
    if intent == "contact" and name and phone:
        return (
            "Contact",
            [f"The approved contact is {name} · {phone}.", d.CONTACT_RULE],
            _cite(session, case.id, "PRF-4418", "phone"),
            [],
        )
    if intent == "phone" and name and phone:
        return (
            "Phone on file",
            [f"The phone on file is {phone} for {name}."],
            _cite(session, case.id, "PRF-4418", "phone"),
            [],
        )
    if intent in ("can_close", "close_now"):
        items = _closure_items(session, case)
        if not items:
            return "Closure", ["Yes. Every closure item is complete."], [], []
        checklist = AskAction(kind="navigate", label="Open closure checklist", target="closure")
        return "Closure", ["Not yet.", *items], [], [checklist]
    if intent == "stale":
        stale = approval is not None and approval.status == "stale"
        text = (
            "The approval is out of date: the evidence changed after the packet was prepared."
            if stale
            else "No approval is out of date."
        )
        return "Approval status", [text], [], [open_decision] if stale else []
    if intent in ("credit_blocked", "policy"):
        if view is None:
            text = "Policy has not been evaluated on the current evidence."
        elif view.status == "eligible" and (approval is None or approval.status != "approved"):
            text = d.CREDIT_NEEDS_APPROVAL
        else:
            text = view.label
        return "Policy", [text], policy_cites, []
    return "Vera", [d.UNKNOWN], [], []


def _first_field(session: Session, case_id: str, record_id: str) -> list[d.Citation]:
    for r in evidence.get_evidence_summary(session, case_id).records:
        if r.record_id == record_id and r.fields:
            return [
                d.Citation(
                    record_id=record_id, version=r.current_version, field=sorted(r.fields)[0]
                )
            ]
    return []


@router.post("/cases/{case_id}/ask")
def ask(
    case_id: str, body: AskIn, request: Request, session: DbSession, actor: ReaderDep
) -> AskOut:
    """Read-only: fixed answers from stored rows. No model call, no command, no audit event."""
    import hashlib
    import json

    evidence._require_reader(actor)
    case = evidence._case(session, case_id)
    if not body.text.strip():
        raise CommandError("schema_invalid", 422, "text: required.")
    intent = d.ask_intent(body.text, body.last_intent)
    title, paragraphs, cites, actions = _answer(
        session, case, intent, _offered(request, session, case_id, actor)
    )
    signature = hashlib.sha256(
        json.dumps([intent, paragraphs, [c.model_dump() for c in cites]]).encode()
    ).hexdigest()[:16]
    out = AskOut(
        intent=intent,
        title=title,
        paragraphs=paragraphs,
        cites=cites,
        actions=actions,
        signature=signature,
    )
    clock: Clock = request.app.state.clock
    pair = session.scalars(
        select(AskPair).where(
            AskPair.case_id == case_id,
            AskPair.user_id == actor.user_id,
            AskPair.intent == intent,
            AskPair.signature == signature,
        )
    ).first()
    if pair is None:
        pair = AskPair(case_id=case_id, user_id=actor.user_id, intent=intent, signature=signature)
        session.add(pair)
    pair.question, pair.answer, pair.asked_at = body.text.strip(), out.model_dump(), clock.now()
    session.commit()
    return out


class AskPairView(BaseModel):
    question: str
    answer: AskOut
    asked_at: datetime


@router.get("/cases/{case_id}/ask")
def list_ask_pairs(case_id: str, session: DbSession, actor: ReaderDep) -> list[AskPairView]:
    evidence._require_reader(actor)
    rows = session.scalars(
        select(AskPair)
        .where(AskPair.case_id == case_id, AskPair.user_id == actor.user_id)
        .order_by(AskPair.asked_at, AskPair.id)
    )
    return [
        AskPairView(question=r.question, answer=AskOut(**r.answer), asked_at=r.asked_at)
        for r in rows
    ]


plugins.register_router(router)
