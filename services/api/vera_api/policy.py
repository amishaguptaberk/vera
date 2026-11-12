"""Policy Controller service: load input, evaluate, persist, gate, re-evaluate, read routes.

The pure rules live in vera_domain.policy; this module is the only place that touches the
database for policy. Nothing from model text reaches the evaluator.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.clock import default_demo_clock
from vera_domain.commands import PolicyState
from vera_domain.enums import EventType, Role
from vera_domain.errors import CommandError
from vera_domain.evidence import EvidenceSummary
from vera_domain.models import PolicyView
from vera_domain.policy import (
    POLICY_ID,
    POLICY_V1,
    PolicyInput,
    PolicyResult,
    PolicyVersion,
    Rule,
    evaluate,
    policy_input_from,
)

from vera_api import evidence as evidence_service
from vera_api.auth import Actor
from vera_api.intake import _emit
from vera_api.models import Cardholder as CardholderRow
from vera_api.models import CardTransaction, Case
from vera_api.models_policy import PolicyEvaluation, PolicyVersionRow

__all__ = ["POLICY_ID", "router"]

POLICY_CONTROLLER = Actor(
    user_id="policy_controller",
    name="Policy Controller",
    active_role=Role.POLICY_CONTROLLER,
    roles=frozenset({Role.POLICY_CONTROLLER}),
)


def seed_policy_v1(session: Session) -> None:
    """Insert policy v1 from the rules data (idempotent; versions are immutable)."""
    if session.get(PolicyVersionRow, (POLICY_ID, POLICY_V1.version)) is None:
        session.add(
            PolicyVersionRow(
                policy_id=POLICY_ID,
                version=POLICY_V1.version,
                rules=[r.model_dump(mode="json") for r in POLICY_V1.rules],
            )
        )
        session.flush()


def _version(session: Session, version: int) -> PolicyVersion:
    row = session.get(PolicyVersionRow, (POLICY_ID, version))
    if row is None:
        raise CommandError("policy_version_not_found", 404, f"No policy version {version}.")
    return PolicyVersion(version=row.version, rules=[Rule.model_validate(r) for r in row.rules])


def _evidence_summary(session: Session, case_id: str) -> EvidenceSummary:
    return evidence_service.get_evidence_summary(session, case_id)


def _identity_verified(session: Session, case_id: str) -> bool:
    """A completed one-time-code or push verification authenticates the cardholder."""
    from vera_api import identity

    return identity.identity_verified(session, case_id)


def load_policy_input(session: Session, case_id: str) -> PolicyInput:
    """THE seam for evidence. Case/transaction facts come from the case and transaction rows;
    records, conflicts, missing kinds and the snapshot hash come from the evidence summary."""
    case = session.get(Case, case_id)
    if case is None:
        raise CommandError("case_not_found", 404, "No such case.")
    txn = session.get(CardTransaction, case.transaction_id)
    assert txn is not None
    holder = session.get(CardholderRow, txn.cardholder_id)
    twins = session.scalars(
        select(CardTransaction.id).where(
            CardTransaction.cardholder_id == txn.cardholder_id,
            CardTransaction.merchant_id == txn.merchant_id,
            CardTransaction.amount_cents == txn.amount_cents,
            CardTransaction.id != txn.id,
        )
    ).first()
    facts = {
        "transaction_id": txn.id,
        "amount_cents": txn.amount_cents,
        "currency": txn.currency,
        "cardholder_authenticated": (holder is not None and holder.contact_verified_at is not None)
        or _identity_verified(session, case_id),
        "duplicates_ruled_out": twins is None,
    }
    return policy_input_from(
        facts, _evidence_summary(session, case_id), fallback_snapshot=case.evidence_snapshot
    )


def compute(session: Session, case: Case) -> PolicyResult:
    return evaluate(_version(session, case.policy_version), load_policy_input(session, case.id))


def _latest(session: Session, case_id: str, snapshot: str | None = None) -> PolicyEvaluation | None:
    stmt = select(PolicyEvaluation).where(PolicyEvaluation.case_id == case_id)
    if snapshot is not None:
        stmt = stmt.where(PolicyEvaluation.snapshot_hash == snapshot)
    return session.scalars(stmt.order_by(PolicyEvaluation.id.desc())).first()


def has_evaluation(session: Session, case_id: str) -> bool:
    return _latest(session, case_id) is not None


def store(
    session: Session, case: Case, result: PolicyResult, event_id: int | None, now: datetime
) -> PolicyEvaluation:
    row = PolicyEvaluation(
        case_id=case.id,
        policy_version=result.policy_version,
        snapshot_hash=result.snapshot_hash,
        status=result.status,
        code=result.code,
        result=result.model_dump(mode="json"),
        evidence_ids=list(result.evidence_used),
        event_id=event_id,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return row


def evaluate_and_store(
    session: Session, case_id: str, actor: Actor, now: datetime | None = None
) -> PolicyResult:
    """Evaluate on the current snapshot. A snapshot+version already evaluated to the same
    verdict writes nothing. Inputs that are not evidence (a verified cardholder) can change the
    verdict on an unchanged snapshot; that writes a new evaluation instead of keeping the old."""
    case = session.get(Case, case_id)
    if case is None:
        raise CommandError("case_not_found", 404, "No such case.")
    result = compute(session, case)
    prior = _latest(session, case_id, result.snapshot_hash)
    if (
        prior is not None
        and prior.policy_version == result.policy_version
        and _same_verdict(PolicyResult.model_validate(prior.result), result)
    ):
        return PolicyResult.model_validate(prior.result)
    at = now or default_demo_clock().now()
    event_id = _emit(
        session,
        EventType.POLICY_EVALUATED,
        case,
        actor.user_id,
        actor.active_role,
        at,
        list(result.evidence_used),
        f"Policy v{result.policy_version}: {result.label}",
        {
            "status": result.status,
            "code": result.code,
            "snapshot": result.snapshot_hash,
            "policy_version": result.policy_version,
            "rules_failed": result.rules_failed,
        },
    )
    store(session, case, result, event_id, at)
    return result


def _same_verdict(a: PolicyResult, b: PolicyResult) -> bool:
    return (a.status, a.code, sorted(a.rules_passed), sorted(a.rules_failed)) == (
        b.status,
        b.code,
        sorted(b.rules_passed),
        sorted(b.rules_failed),
    )


def reevaluate_on_evidence_change(
    session: Session, case_id: str, now: datetime | None = None
) -> PolicyResult:
    """Called by the evidence pipeline after a material change (the policy_reevaluator step)."""
    return evaluate_and_store(session, case_id, POLICY_CONTROLLER, now)


def key_context(session: Session, case: Case) -> dict[str, object]:
    """Fields the evaluate_policy key template needs beyond case, actor and payload."""
    return {
        "snapshot_hash": load_policy_input(session, case.id).snapshot_hash,
        "policy_version": case.policy_version,
    }


def current_state(session: Session, case: Case) -> PolicyState | None:
    """Latest stored evaluation for the case's current snapshot (stage 7 reads this)."""
    snapshot = load_policy_input(session, case.id).snapshot_hash
    row = _latest(session, case.id, snapshot)
    if row is None or row.policy_version != case.policy_version:
        return None
    return PolicyState(status=row.status, label=str(row.result["label"]))


def latest_view(session: Session, case_id: str) -> PolicyView | None:
    row = _latest(session, case_id)
    if row is None:
        return None
    r = row.result
    return PolicyView(
        status=row.status,  # type: ignore[arg-type,unused-ignore]
        code=row.code,
        label=r["label"],
        rules_passed=r["rules_passed"],
        rules_failed=r["rules_failed"],
        evidence_used=list(row.evidence_ids),
        snapshot=row.snapshot_hash,
        policy_version=row.policy_version,
        evaluated_at=row.created_at,
    )


def _get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


router = APIRouter(prefix="/api/policies")
Db = Annotated[Session, Depends(_get_session)]


def _out(session: Session, policy_id: str, version: int) -> dict[str, Any]:
    versions = list(
        session.scalars(
            select(PolicyVersionRow.version)
            .where(PolicyVersionRow.policy_id == policy_id)
            .order_by(PolicyVersionRow.version)
        )
    )
    row = session.get(PolicyVersionRow, (policy_id, version))
    if row is None:
        raise CommandError("policy_not_found", 404, "No such policy version.")
    return {
        "policy_id": policy_id,
        "version": row.version,
        "versions": versions,
        "rules": row.rules,
        "created_at": row.created_at,
    }


@router.get("/{policy_id}")
def get_policy(policy_id: str, session: Db) -> dict[str, Any]:
    top = session.scalars(
        select(PolicyVersionRow.version)
        .where(PolicyVersionRow.policy_id == policy_id)
        .order_by(PolicyVersionRow.version.desc())
    ).first()
    if top is None:
        raise CommandError("policy_not_found", 404, "No such policy.")
    return _out(session, policy_id, top)


@router.get("/{policy_id}/versions/{version}")
def get_policy_version(policy_id: str, version: int, session: Db) -> dict[str, Any]:
    return _out(session, policy_id, version)
