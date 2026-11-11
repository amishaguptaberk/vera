"""Idempotent report intake: one case and one report per card transaction (US-A04)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vera_domain.enums import CaseState, CaseStep, EventType, Role

from vera_api.models import (
    AuditEvent,
    CardTransaction,
    Case,
    CaseAssignment,
    Claim,
    Report,
    StateTransition,
)

DEFAULT_OWNER_ID = "usr-sam-rivera"
WORKFLOW_VERSION = 3
POLICY_VERSION = 1
# sha256 of the canonical JSON "[]" (no evidence records yet).
EMPTY_SNAPSHOT = "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


class UnknownTransactionError(LookupError):
    pass


class CaseNotOpenableError(LookupError):
    """The transaction's case is display-only or has no report to link to."""


@dataclass(frozen=True)
class IntakeResult:
    case_id: str
    report_id: str
    created: bool


def case_id_for(transaction_id: str) -> str:
    return "CHG-" + transaction_id.removeprefix("TXN-")


def _emit(
    session: Session,
    type_: EventType,
    case: Case,
    cardholder_id: str,
    at: datetime,
    record_ids: list[str],
    summary: str,
) -> int:
    event = AuditEvent(
        type=type_.value,
        case_id=case.id,
        case_version=case.case_version,
        at=at,
        actor_id=cardholder_id,
        actor_role=Role.CARDHOLDER.value,
        record_ids=record_ids,
        summary=summary,
    )
    session.add(event)
    session.flush()
    return event.id


def _existing(session: Session, transaction_id: str) -> Case | None:
    return session.scalars(select(Case).where(Case.transaction_id == transaction_id)).first()


def submit_report(
    session: Session,
    *,
    report_id: str,
    transaction_id: str,
    statement: str,
    now: datetime,
    due_at: datetime | None = None,
) -> IntakeResult:
    """Create the case and report once; later reports link to the existing case."""
    txn = session.get(CardTransaction, transaction_id)
    if txn is None:
        raise UnknownTransactionError(transaction_id)

    case = _existing(session, transaction_id)
    if case is None:
        try:
            with session.begin_nested():
                return _create(session, txn, report_id, statement, now, due_at)
        except IntegrityError:
            case = _existing(session, transaction_id)
            if case is None:
                raise
    return _link_duplicate(session, case, txn, report_id, now)


def _create(
    session: Session,
    txn: CardTransaction,
    report_id: str,
    statement: str,
    now: datetime,
    due_at: datetime | None,
) -> IntakeResult:
    case = Case(
        id=case_id_for(txn.id),
        transaction_id=txn.id,
        state=CaseState.REPORTED.value,
        step=CaseStep.INTAKE.value,
        case_version=1,
        owner_id=DEFAULT_OWNER_ID,
        due_at=due_at,
        workflow_version=WORKFLOW_VERSION,
        policy_version=POLICY_VERSION,
        evidence_snapshot=EMPTY_SNAPSHOT,
        live=True,
    )
    session.add(case)
    session.flush()
    session.add(
        Report(
            id=report_id,
            case_id=case.id,
            cardholder_id=txn.cardholder_id,
            statement=statement,
            received_at=now,
        )
    )
    session.flush()
    session.add(
        Claim(
            id="CLM-" + report_id.removeprefix("REP-"),
            report_id=report_id,
            case_id=case.id,
            statement=statement,
        )
    )
    session.add(CaseAssignment(case_id=case.id, user_id=DEFAULT_OWNER_ID, assigned_at=now))
    _emit(
        session,
        EventType.REPORT_RECEIVED,
        case,
        txn.cardholder_id,
        now,
        [report_id],
        "Cardholder report received",
    )
    created = _emit(
        session,
        EventType.CASE_CREATED,
        case,
        txn.cardholder_id,
        now,
        [case.id],
        "Case created from report",
    )
    session.add(
        StateTransition(
            case_id=case.id,
            prior_state=None,
            prior_step=None,
            next_state=case.state,
            next_step=case.step,
            actor_id=txn.cardholder_id,
            actor_role=Role.CARDHOLDER.value,
            reason="Report received",
            case_version=case.case_version,
            workflow_version=case.workflow_version,
            policy_version=case.policy_version,
            evidence_snapshot=case.evidence_snapshot,
            event_id=created,
            at=now,
        )
    )
    session.flush()
    return IntakeResult(case_id=case.id, report_id=report_id, created=True)


def _link_duplicate(
    session: Session, case: Case, txn: CardTransaction, report_id: str, now: datetime
) -> IntakeResult:
    original = session.scalars(
        select(Report).where(Report.case_id == case.id).order_by(Report.received_at, Report.id)
    ).first()
    if original is None or not case.live:
        raise CaseNotOpenableError(case.id)
    if report_id != original.id:  # same report id is a plain replay: nothing to record
        _emit(
            session,
            EventType.REPORT_DUPLICATE_LINKED,
            case,
            txn.cardholder_id,
            now,
            [report_id, original.id],
            "Repeat report linked to existing case",
        )
    return IntakeResult(case_id=case.id, report_id=original.id, created=False)
