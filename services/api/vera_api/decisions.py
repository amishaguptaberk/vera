"""Decision packet, decision, reviewer approval (bound to snapshot/policy/workflow) and Ask Vera."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain import decisions as d
from vera_domain.clock import Clock
from vera_domain.commands import ApprovalState
from vera_domain.errors import CommandError

from vera_api import evidence, gateway, plugins
from vera_api import policy as policy_service
from vera_api.auth import Actor
from vera_api.evidence import DbSession, ReaderDep
from vera_api.gateway import EffectContext
from vera_api.models import Case, User
from vera_api.models_decisions import Approval, AskPair, Decision, DecisionPacket

DEFAULT_REVIEWER = "usr-dana-okafor"

# ---- reads (the credit stage uses current_decision / latest_approval) ---------------------------


def latest_packet(session: Session, case_id: str) -> DecisionPacket | None:
    stmt = select(DecisionPacket).where(DecisionPacket.case_id == case_id)
    return session.scalars(stmt.order_by(DecisionPacket.version.desc())).first()


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
        "packet_status": "ready" if packet else "none",
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
        or row.snapshot_hash == case.evidence_snapshot
    ):
        return []
    row.status = "stale"
    session.flush()
    return [row.id]


# ---- effects ------------------------------------------------------------------------------------


def _need(row: Any, what: str) -> Any:
    if row is None:
        raise CommandError("precondition_failed", 422, f"No {what} for this case.")
    return row


def _summary(session: Session, case: Case) -> dict[str, Any]:
    """Packet body from stored rows only; every statement cites record, version and field."""
    ev = evidence.get_evidence_summary(session, case.id)
    statements = [
        {
            "text": f"{r.record_id} v{r.current_version} records {name}",
            "record_id": r.record_id,
            "version": r.current_version,
            "field": name,
        }
        for r in ev.records
        for name in sorted(r.fields)
    ]
    view = policy_service.latest_view(session, case.id)
    return {
        "statements": statements,
        "open_conflicts": [c.model_dump(mode="json") for c in ev.open_conflicts],
        "missing": list(ev.missing),
        "policy": view.model_dump(mode="json") if view else None,
        "recommendation": "Vera recommends; the analyst decides and the reviewer approves.",
    }


def _create_packet(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    prior = latest_packet(session, case.id)
    snapshot = case.evidence_snapshot
    evaluation = policy_service._latest(session, case.id)
    row = DecisionPacket(
        case_id=case.id,
        version=(prior.version if prior else 0) + 1,
        snapshot_hash=snapshot,
        workflow_version=case.workflow_version,
        policy_version=case.policy_version,
        policy_evaluation_id=evaluation.id if evaluation else None,
        summary=_summary(session, case),
        created_by=actor.user_id,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return {
        "packet_version": row.version,
        "snapshot_hash": row.snapshot_hash,
        "policy_version": row.policy_version,
        "workflow_version": row.workflow_version,
    }


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
    return {
        "packet_version": packet.version if packet else 0,
        "approval_id": approval.id if approval else "none",
    }


gateway.register_commands(
    __name__,
    human={c.name: c for c in d.COMMANDS},
    effects={
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
gateway.register_fact_provider(_facts)
gateway.set_approval_provider(_approval_provider)
if _mark_stale not in evidence.STALE_APPROVAL_HOOKS:
    evidence.STALE_APPROVAL_HOOKS.append(_mark_stale)
plugins.register_reset_tables(["ask_pairs", "approvals", "decisions", "decision_packets"])

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


class PacketStatement(d.Citation):
    text: str


class DecisionPacketView(BaseModel):
    case_id: str
    version: int
    latest_version: int
    current: bool  # false when the case's evidence snapshot moved on
    snapshot_hash: str
    workflow_version: int
    policy_version: int
    policy_evaluation_id: int | None
    statements: list[PacketStatement]
    open_conflicts: list[dict[str, Any]]
    missing: list[str]
    policy: dict[str, Any] | None
    recommendation: str
    decision: str | None
    approval: ApprovalView | None
    created_by: str
    created_at: datetime


class AskIn(BaseModel):
    text: str


class AskOut(BaseModel):
    answer: str
    citations: list[d.Citation]
    refused: bool


router = APIRouter(prefix="/api")


@router.get("/cases/{case_id}/decision-packet")
def get_decision_packet(
    case_id: str, session: DbSession, actor: ReaderDep, version: int | None = None
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
    return DecisionPacketView(
        case_id=case_id,
        version=row.version,
        latest_version=latest.version,
        current=row.version == latest.version and row.snapshot_hash == case.evidence_snapshot,
        snapshot_hash=row.snapshot_hash,
        workflow_version=row.workflow_version,
        policy_version=row.policy_version,
        policy_evaluation_id=row.policy_evaluation_id,
        statements=[PacketStatement(**x) for x in s["statements"]],
        open_conflicts=s["open_conflicts"],
        missing=s["missing"],
        policy=s["policy"],
        recommendation=s["recommendation"],
        decision=decision.decision if decision else None,
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


def _citations(session: Session, case_id: str, record_ids: list[str]) -> list[d.Citation]:
    """Only records in this case's register (staff-readable), at their current version."""
    records = {r.record_id: r for r in evidence.get_evidence_summary(session, case_id).records}
    wanted = [i for i in record_ids if i in records] or sorted(records)[:1]
    return [
        d.Citation(
            record_id=i, version=records[i].current_version, field=sorted(records[i].fields)[0]
        )
        for i in wanted
        if records[i].fields
    ]


def _answer(session: Session, case: Case, intent: str) -> AskOut:
    if intent == "approve":
        return AskOut(answer=d.REFUSAL, citations=[], refused=True)
    view = policy_service.latest_view(session, case.id)
    approval = latest_approval(session, case.id)
    cites = _citations(session, case.id, list(view.evidence_used) if view else [])
    if intent == "issue_credit":
        if approval is not None and approval.status == "approved":
            text = "The decision is approved. Credit is issued with the analyst action, not chat."
        else:
            text = "The packet is eligible for credit, but reviewer approval is still required."
            if view is None or view.status != "eligible":
                text = "Credit is not available: " + (
                    view.label if view else "policy not evaluated."
                )
        return AskOut(answer=text, citations=cites, refused=True)
    if intent == "stale":
        stale = approval is not None and approval.status == "stale"
        text = (
            "The approval is out of date: the evidence changed after the packet was prepared."
            if stale
            else "No approval is out of date."
        )
        return AskOut(answer=text, citations=cites, refused=False)
    if intent in ("credit_blocked", "policy"):
        if view is None:
            text = "Policy has not been evaluated on the current evidence."
        elif view.status == "eligible" and (approval is None or approval.status != "approved"):
            text = "The packet is eligible for credit, but reviewer approval is still required."
        else:
            text = view.label
        return AskOut(answer=text, citations=cites, refused=False)
    return AskOut(answer=d.UNKNOWN, citations=[], refused=False)


@router.post("/cases/{case_id}/ask")
def ask(
    case_id: str, body: AskIn, request: Request, session: DbSession, actor: ReaderDep
) -> AskOut:
    """Read-only: fixed answers from stored rows. No model call, no command, no audit event."""
    evidence._require_reader(actor)
    case = evidence._case(session, case_id)
    if not body.text.strip():
        raise CommandError("schema_invalid", 422, "text: required.")
    intent = d.ask_intent(body.text)
    out = _answer(session, case, intent)
    clock: Clock = request.app.state.clock
    pair = session.scalars(
        select(AskPair).where(
            AskPair.case_id == case_id, AskPair.user_id == actor.user_id, AskPair.intent == intent
        )
    ).first()
    if pair is None:
        pair = AskPair(case_id=case_id, user_id=actor.user_id, intent=intent)
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
