import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.commands import REGISTRY, available_actions, recovery_actions, resolve_key
from vera_domain.enums import CaseState, CaseStep, Role
from vera_domain.exposure import CreditStatus, ExposureRow, case_impact, compute_exposure
from vera_domain.facts import Hold, derive_step
from vera_domain.labels import BLOCKER_BY_STEP, WAIT_KIND_BY_STEP, describe
from vera_domain.models import (
    ActionView,
    CardholderView,
    CaseView,
    ChargeImpact,
    ContactOnFile,
    Due,
    FilterCounts,
    Person,
    Pins,
    QueueRow,
    Summary,
    SummaryMetric,
    TransactionView,
)
from vera_domain.progress import ProgressStep, progress_steps

from vera_api import auth, investigation
from vera_api import policy as policy_service
from vera_api.gateway import KEY_CONTEXTS, approval_binding, approval_state, facts_for
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


def _with_feature_key(session: Session, case: Case, action: ActionView) -> ActionView:
    """Fill the key fields a feature supplies (its gateway key context: verification id, attempt,
    packet version, approval id...), so the offered key is exactly what the gateway expects."""
    ctx = KEY_CONTEXTS.get(action.command)
    if ctx is None or "{" not in action.idempotency_key:
        return action
    body = dict(action.payload_defaults)
    # The offered key already carries case, version, user and policy fields; fill the rest.
    partial = replace(REGISTRY[action.command], key_template=action.idempotency_key)
    key = resolve_key(partial, {**ctx(session, case, body), **body})
    return action.model_copy(update={"idempotency_key": key})


def _person(session: Session, user_id: str) -> Person:
    user = session.get(User, user_id)
    assert user is not None
    return Person(id=user.id, name=user.name)


def _mask_phone(phone: str) -> str:
    return phone[:5] + "•••-" + phone[-4:]


def list_cases(session: Session, now: datetime, tz: str) -> list[QueueRow]:
    return [row for row, _ in _queue(session, now, tz)]


def _queue(session: Session, now: datetime, tz: str) -> list[tuple[QueueRow, str]]:
    """Queue rows with the id of the person the case is with (hold's next owner, else owner)."""
    stmt = (
        select(Case, CardTransaction, Merchant, User)
        .join(CardTransaction, CardTransaction.id == Case.transaction_id)
        .join(Merchant, Merchant.id == CardTransaction.merchant_id)
        .join(User, User.id == Case.owner_id)
        .order_by(Case.due_at.asc().nulls_last(), Case.id)
    )
    rows: list[tuple[QueueRow, str]] = []
    for case, txn, merchant, owner in session.execute(stmt):
        state, step = CaseState(case.state), CaseStep(case.step)
        hold = Hold.model_validate(case.hold) if case.hold else None
        if case.live:
            waiting = _waiting_on(session, case, txn)
            next_action: str | None = describe(state, step)[2]
            waiting_on = waiting.name if waiting else None
            blocker = BLOCKER_BY_STEP.get(step)
        else:
            next_action = case.display_next_action
            waiting_on = case.display_waiting_on
            blocker = case.display_blocker
        due = _due(case.due_at, now, tz)
        row = QueueRow(
            case_id=case.id,
            merchant=merchant.name,
            amount_cents=txn.amount_cents,
            currency=txn.currency,
            state=state,
            step=step,
            state_label=case.display_label or describe(state, step)[0],
            owner=Person(id=owner.id, name=owner.name),
            due=due,
            credit_cents=case.credit_cents,
            live=case.live,
            next_action=next_action,
            waiting_on=waiting_on,
            blocker=blocker,
            wait_kind=WAIT_KIND_BY_STEP.get(step),
            due_today=_due_today(case.due_at, now, tz, closed=state == CaseState.CLOSED),
        )
        rows.append((row, hold.next_owner_id if hold else owner.id))
    return rows


def _due_today(due_at: datetime | None, now: datetime, tz: str, *, closed: bool) -> bool:
    if due_at is None or closed or due_at < now:
        return False
    zone = ZoneInfo(tz)
    return due_at.astimezone(zone).date() == now.astimezone(zone).date()


def filter_counts(session: Session, now: datetime, tz: str, user_id: str) -> FilterCounts:
    """Queue filter chip counts (prototype `FL`), server-side with the demo clock."""
    rows = _queue(session, now, tz)

    def count(pred: Callable[[QueueRow, str], bool]) -> int:
        return sum(1 for row, with_id in rows if pred(row, with_id))

    return FilterCounts(
        all=len(rows),
        due_today=count(lambda r, _: r.due_today),
        overdue=count(lambda r, _: r.state != CaseState.CLOSED and bool(r.due and r.due.overdue)),
        mine=count(
            lambda r, who: who == user_id and r.wait_kind is None and r.state != CaseState.CLOSED
        ),
        cardholder=count(lambda r, _: r.wait_kind == "cardholder"),
        reviewer=count(lambda r, _: r.wait_kind == "reviewer"),
    )


def _waiting_on(session: Session, case: Case, txn: CardTransaction) -> Person | None:
    """Who a live case waits on: the hold's next owner, else the party its step waits on."""
    if case.hold:
        return _person(session, Hold.model_validate(case.hold).next_owner_id)
    kind = WAIT_KIND_BY_STEP.get(CaseStep(case.step))
    if kind == "cardholder":
        holder = session.get(Cardholder, txn.cardholder_id)
        return Person(id=holder.profile_id, name=holder.name) if holder else None
    if kind == "reviewer":
        reviewer = session.get(User, case.waiting_on_id) if case.waiting_on_id else None
        reviewer = reviewer or auth.user_for_role(session, Role.REVIEWER)
        return Person(id=reviewer.id, name=reviewer.name) if reviewer else None
    return None


def _steps(session: Session, case: Case) -> list[ProgressStep]:
    held_step = derive_step(facts_for(session, case).model_copy(update={"hold": None}))[1]
    failed = bool(investigation.failed_steps(session, case.id))  # same source as recovery_actions
    return progress_steps(CaseStep(case.step), held_step=held_step, run_failed=failed)


def _exposure_row(case: Case, txn: CardTransaction) -> ExposureRow:
    return ExposureRow(
        amount_cents=txn.amount_cents,
        currency=txn.currency,
        closed=case.state == CaseState.CLOSED.value,
        due_at=case.due_at,
        credit_cents=case.credit_cents,
        credit_status=CreditStatus(case.credit_status) if case.credit_status else None,
    )


def summarize(session: Session, now: datetime, tz: str) -> Summary:
    stmt = select(Case, CardTransaction).join(
        CardTransaction, CardTransaction.id == Case.transaction_id
    )
    rows = [_exposure_row(case, txn) for case, txn in session.execute(stmt)]
    metrics = compute_exposure(rows, now, tz)
    return Summary(**{k: SummaryMetric(**vars(m)) for k, m in metrics.items()})


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
            approval=approval_state(session, case),
            approval_binding=approval_binding(case),
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
        waiting_on=_waiting_on(session, case, txn),
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
        charge_impact=ChargeImpact(**vars(case_impact(_exposure_row(case, txn)))),
        available_actions=[_with_feature_key(session, case, a) for a in enabled],
        blocked_actions=blocked,
        recovery_actions=(
            recovery_actions(
                actor[1],
                state,
                step,
                case_id=case.id,
                case_version=case.case_version,
                failed_steps=investigation.failed_steps(session, case.id),
            )
            if actor
            else []
        ),
        hold=Hold.model_validate(case.hold) if case.hold else None,
        policy=policy_service.latest_view(session, case.id),
        steps=_steps(session, case),
    )
