import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.commands import REGISTRY, available_actions
from vera_domain.enums import CaseState, CaseStep, Role
from vera_domain.facts import Hold
from vera_domain.labels import describe
from vera_domain.models import (
    CardholderView,
    CaseView,
    ChargeImpact,
    ContactOnFile,
    Due,
    Person,
    Pins,
    QueueRow,
    Summary,
    SummaryMetric,
    TransactionView,
)

from vera_api import policy as policy_service
from vera_api.models import Cardholder, CardTransaction, Case, Merchant, Report, User


class CaseNotFoundError(LookupError):
    pass


class CaseNotOpenableError(LookupError):
    pass


def _due(due_at: datetime | None, now: datetime, tz: str) -> Due | None:
    if due_at is None:
        return None
    local = due_at.astimezone(ZoneInfo(tz))
    label = f"{local:%b} {local.day}, {local.hour % 12 or 12}:{local:%M} {local:%p}"
    return Due(at=due_at, label=label, overdue=due_at < now)


def _person(session: Session, user_id: str) -> Person:
    user = session.get(User, user_id)
    assert user is not None
    return Person(id=user.id, name=user.name)


def _mask_phone(phone: str) -> str:
    return phone[:5] + "•••-" + phone[-4:]


def list_cases(session: Session, now: datetime, tz: str) -> list[QueueRow]:
    stmt = (
        select(Case, CardTransaction, Merchant, User)
        .join(CardTransaction, CardTransaction.id == Case.transaction_id)
        .join(Merchant, Merchant.id == CardTransaction.merchant_id)
        .join(User, User.id == Case.owner_id)
        .order_by(Case.due_at.asc().nulls_last(), Case.id)
    )
    rows: list[QueueRow] = []
    for case, txn, merchant, owner in session.execute(stmt):
        state, step = CaseState(case.state), CaseStep(case.step)
        rows.append(
            QueueRow(
                case_id=case.id,
                merchant=merchant.name,
                amount_cents=txn.amount_cents,
                currency=txn.currency,
                state=state,
                step=step,
                state_label=case.display_label or describe(state, step)[0],
                owner=Person(id=owner.id, name=owner.name),
                due=_due(case.due_at, now, tz),
                credit_cents=case.credit_cents,
                live=case.live,
            )
        )
    return rows


def summarize(session: Session, now: datetime, tz: str) -> Summary:
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).date()
    stmt = select(Case, CardTransaction).join(
        CardTransaction, CardTransaction.id == Case.transaction_id
    )
    exposure = [0, 0]
    due_today = [0, 0]
    overdue = [0, 0]
    credit = [0, 0]
    for case, txn in session.execute(stmt):
        if case.state == CaseState.CLOSED.value:
            continue
        open_cents = txn.amount_cents - case.credit_cents
        exposure[0] += open_cents
        exposure[1] += 1
        if case.credit_cents > 0:
            credit[0] += case.credit_cents
            credit[1] += 1
        if case.due_at is not None:
            if case.due_at < now:
                overdue[0] += open_cents
                overdue[1] += 1
            elif case.due_at.astimezone(zone).date() == today:
                due_today[0] += open_cents
                due_today[1] += 1

    def metric(pair: list[int]) -> SummaryMetric:
        return SummaryMetric(amount_cents=pair[0], cases=pair[1])

    return Summary(
        open_exposure=metric(exposure),
        due_today=metric(due_today),
        overdue=metric(overdue),
        temporary_credit=metric(credit),
    )


_SEQUENTIAL_REPORT_ID = re.compile(r"REP-([0-9]{1,9})", re.ASCII)


def _next_report_id(session: Session) -> str:
    """Next sequential REP-NNNN above the highest stored report id (read in this session)."""
    top = 0
    for (rid,) in session.execute(select(Report.id).where(Report.id.like("REP-%"))):
        # ASCII digits only and bounded: stored ids may be foreign data; never raise here.
        match = _SEQUENTIAL_REPORT_ID.fullmatch(rid)
        if match:
            top = max(top, int(match.group(1)))
    return f"REP-{top + 1:04d}"


def get_case_view(
    session: Session,
    case_id: str,
    now: datetime,
    tz: str,
    actor: tuple[str, Role] | None = None,
) -> CaseView:
    case = session.get(Case, case_id)
    if case is None:
        raise CaseNotFoundError(case_id)
    if not case.live:
        raise CaseNotOpenableError(case_id)
    txn = session.get(CardTransaction, case.transaction_id)
    assert txn is not None
    merchant = session.get(Merchant, txn.merchant_id)
    holder = session.get(Cardholder, txn.cardholder_id)
    assert merchant is not None and holder is not None
    state, step = CaseState(case.state), CaseStep(case.step)
    label, kind, next_action = describe(state, step)
    exposure = txn.amount_cents - case.credit_cents
    gated = any(s.requires_policy is not None for s in REGISTRY.values())
    enabled, blocked = (
        available_actions(
            actor[1],
            state,
            step,
            case_id=case.id,
            case_version=case.case_version,
            user_id=actor[0],
            next_report_id=_next_report_id(session),
            policy_state=policy_service.current_state(session, case) if gated else None,
            key_context=policy_service.key_context(session, case),
        )
        if actor
        else ([], [])
    )
    return CaseView(
        case_id=case.id,
        case_version=case.case_version,
        state=state,
        step=step,
        state_label=label,
        state_kind=kind,
        next_action=next_action,
        owner=_person(session, case.owner_id),
        waiting_on=None,
        due=_due(case.due_at, now, tz),
        pins=Pins(
            workflow_version=case.workflow_version,
            policy_version=case.policy_version,
            evidence_snapshot=case.evidence_snapshot,
        ),
        transaction=TransactionView(
            id=txn.id,
            merchant=merchant.name,
            amount_cents=txn.amount_cents,
            currency=txn.currency,
            card_last4=txn.card_last4,
            posted_at=txn.posted_at,
        ),
        cardholder=CardholderView(
            id=holder.profile_id,
            name=holder.name,
            contact_on_file=ContactOnFile(
                phone_masked=_mask_phone(holder.phone),
                email=holder.email,
                verified_at=holder.contact_verified_at,
            ),
        ),
        charge_impact=ChargeImpact(
            posted_cents=txn.amount_cents,
            credit_cents=case.credit_cents,
            exposure_cents=exposure,
            note="No temporary credit issued."
            if case.credit_cents == 0
            else "Temporary credit issued.",
        ),
        available_actions=enabled,
        blocked_actions=blocked,
        recovery_actions=[],
        hold=Hold.model_validate(case.hold) if case.hold else None,
        policy=policy_service.latest_view(session, case.id),
    )
