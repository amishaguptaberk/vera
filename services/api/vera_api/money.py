"""Credit, dispute and card controls (VER-010): simulated adapters, effects, facts, routes, jobs.

Approval is enforced only by gateway stage 8 (`requires_approval`); nothing here re-checks it.
An adapter is reached only through `adapters.execute` with a business key, and an `uncertain`
result is never treated as success: the credit row stays `uncertain` until `adapters.lookup`.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain import money as domain
from vera_domain.adapters import AdapterResult
from vera_domain.clock import default_demo_clock
from vera_domain.enums import Role
from vera_domain.errors import CommandError

from vera_api import adapters, auth, gateway, plugins, worker
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.config import Settings
from vera_api.gateway import EffectContext, Outcome
from vera_api.intake import _emit
from vera_api.models import CardTransaction, Case
from vera_api.models_adapters import AdapterExecution
from vera_api.models_money import CardControl, ControlPlan, DisputePacket, ProvisionalCredit


class _Simulated:
    """Synthetic integration: deterministic reference derived from the request. No real system."""

    def __init__(self, prefix: str, id_field: str) -> None:
        self.prefix, self.id_field = prefix, id_field

    def call(self, operation: str, request: dict[str, Any]) -> AdapterResult:
        suffix = str(request[self.id_field]).rsplit("-", 1)[-1]
        return AdapterResult(
            status="succeeded",
            result={"reference": f"{self.prefix}-{suffix}", "simulated": True, **request},
        )


adapters.register_adapter("credit", _Simulated("CREDIT", "case_id"))
adapters.register_adapter("dispute", _Simulated("DSPSUB", "case_id"))
adapters.register_adapter("card_controls", _Simulated("CTL", "case_id"))


def _one(session: Session, model: Any, case_id: str) -> Any:
    return session.scalars(select(model).where(model.case_id == case_id)).first()


def _wrong(message: str) -> CommandError:
    return CommandError("invalid_step", 409, message, blocked_reason=message)


# --- credit ---


def credit_key(case: Case) -> str:
    return f"credit:{case.transaction_id}"


def _settle_credit(
    case: Case, row: ProvisionalCredit, out: AdapterResult, now: datetime
) -> dict[str, Any]:
    """Store what the execution record says. Only `succeeded` writes money facts on the case."""
    row.updated_at = now
    if out.status == "succeeded":
        row.status, row.reference, row.issued_at = "issued", str(out.result["reference"]), now
        case.credit_cents, case.credit_status = row.amount_cents, "issued"
    else:
        row.status = "uncertain" if out.status == "uncertain" else "failed"
    return {
        "credit_status": row.status,
        "credit_id": row.reference,
        "amount_cents": row.amount_cents,
        "currency": row.currency,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "execution_status": out.status,
        "idempotency_key": row.execution_key,
        "simulated": True,
    }


def _issue_effect(
    session: Session, case: Case, actor: Actor, payload: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    txn = session.get(CardTransaction, case.transaction_id)
    if txn is None:
        raise CommandError("transaction_not_found", 404, "The case has no transaction.")
    row = _one(session, ProvisionalCredit, case.id)
    if row is None:
        row = ProvisionalCredit(
            case_id=case.id,
            transaction_id=txn.id,
            amount_cents=txn.amount_cents,
            currency=txn.currency,
            status="requested",
            execution_key=credit_key(case),
            requested_by=actor.user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()  # unique (case, transaction, key): a second credit cannot be stored
    elif row.status in ("issued", "uncertain"):
        raise _wrong("A credit was already requested for this charge.")
    out = adapters.execute(
        session,
        case_id=case.id,
        adapter="credit",
        operation="issue",
        key=row.execution_key,
        request={
            "case_id": case.id,
            "transaction_id": txn.id,
            "amount_cents": txn.amount_cents,
            "currency": txn.currency,
        },
        now=now,
    )
    if out.status != "failed":  # an execution exists: the approval it ran under is used up
        _consume_approval(session, case, str(out.execution_id), now)
    return _settle_credit(case, row, out, now)


def _consume_approval(session: Session, case: Case, execution_id: str, now: datetime) -> None:
    """Marks the case's approved approval (VER-009) consumed by this credit execution, so a later
    evidence change cannot stale an approval whose money already moved. The gateway's approval
    gate has already checked it; no stored approval row (no decisions feature) means nothing to
    consume."""
    from vera_api import decisions

    row = decisions.latest_approval(session, case.id)
    if row is not None and row.status == "approved":
        decisions.mark_approval_consumed(session, row.id, execution_id, now)


def _lookup_effect(
    session: Session, case: Case, actor: Actor, payload: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    missing = CommandError("execution_not_found", 404, "No execution with that key on this case.")
    execution = session.scalars(
        select(AdapterExecution).where(
            AdapterExecution.idempotency_key == payload.idempotency_key,
            AdapterExecution.case_id == case.id,
        )
    ).first()
    if execution is not None and execution.adapter == "dispute":
        return _lookup_dispute(session, case, payload.idempotency_key, now, missing)
    if execution is not None and execution.adapter == "card_controls":
        return _lookup_controls(session, case, actor, payload.idempotency_key, now, missing)
    row = _one(session, ProvisionalCredit, case.id)
    if row is None or row.execution_key != payload.idempotency_key:
        raise missing
    out = adapters.lookup(session, row.execution_key, now)
    if out is None:
        raise CommandError("execution_not_found", 404, "No execution with that key on this case.")
    return {"found": True, **_settle_credit(case, row, out, now)}


def _lookup_dispute(
    session: Session, case: Case, key: str, now: datetime, missing: CommandError
) -> dict[str, Any]:
    row = _one(session, DisputePacket, case.id)
    if row is None or key != f"dsp-sub:DSP-{row.id}":
        raise missing
    out = adapters.lookup(session, key, now)
    if out is None:
        raise missing
    row.updated_at = now
    if out.status == "succeeded" and row.status != "submitted":
        row.status, row.submitted_at = "submitted", now
        row.submission_reference = str(out.result["reference"])
    return {
        "found": True,
        "dispute_status": row.status,
        "dispute_id": f"DSP-{row.id}",
        "submission_id": row.submission_reference,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "execution_status": out.status,
        "idempotency_key": key,
        "simulated": True,
    }


def _lookup_controls(
    session: Session, case: Case, actor: Actor, key: str, now: datetime, missing: CommandError
) -> dict[str, Any]:
    row = _one(session, ControlPlan, case.id)
    if row is None or key != f"ctl-apply:{row.id}":
        raise missing
    out = adapters.lookup(session, key, now)
    if out is None:
        raise missing
    applied: list[str] = []
    if out.status == "succeeded" and row.status == "approved":
        _record_applied(session, case, row, actor, str(out.result["reference"]), now)
        applied = list(row.controls)
    return {
        "found": True,
        "controls_status": row.status,
        "plan_id": row.id,
        "applied": applied,
        "execution_status": out.status,
        "idempotency_key": key,
        "simulated": True,
    }


def _credit_after(event: str, summary: str):  # type: ignore[no-untyped-def]
    def after(
        session: Session,
        case: Case,
        actor: Actor,
        payload: Any,
        now: datetime,
        ctx: EffectContext,
        outcome: Outcome,
    ) -> None:
        if ctx.extra.get("credit_status") == "issued":
            from vera_api import prevention  # the planner recommends controls; humans decide

            worker.enqueue(session, prevention.JOB_KIND, {"case_id": case.id}, now=now)
            ref = ctx.extra["credit_id"]
            _emit(
                session,
                event,
                case,
                actor.user_id,
                actor.active_role,
                now,
                [case.id],
                summary.format(ref=ref),
                {"credit_id": ref, "amount_cents": ctx.extra["amount_cents"], "simulated": True},
            )

    return after


# --- dispute ---


def _dispute_step(expected: tuple[str, ...], new: str):  # type: ignore[no-untyped-def]
    def effect(
        session: Session, case: Case, actor: Actor, payload: Any, now: datetime, ctx: EffectContext
    ) -> dict[str, Any]:
        row = _one(session, DisputePacket, case.id)
        current = row.status if row else "none"
        if current not in expected:
            raise _wrong(f"The dispute packet is {current}; this step is not available.")
        if row is None:
            row = DisputePacket(
                case_id=case.id,
                status=new,
                created_by=actor.user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
        row.status, row.updated_at = new, now
        return {"dispute_status": new, "dispute_id": f"DSP-{row.id}"}

    return effect


def _prepare_after(
    session: Session,
    case: Case,
    actor: Actor,
    payload: Any,
    now: datetime,
    ctx: EffectContext,
    outcome: Outcome,
) -> None:
    from vera_api import dispute_prep  # the preparer drafts the reason and narrative; never gates

    dispute_prep.enqueue_preparer(session, case.id, now)


def _submit_effect(
    session: Session, case: Case, actor: Actor, payload: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _one(session, DisputePacket, case.id)
    current = row.status if row else "none"
    if row is None or current not in ("reviewed", "failed"):
        raise _wrong(f"The dispute packet is {current}; it cannot be submitted yet.")
    out = adapters.execute(
        session,
        case_id=case.id,
        adapter="dispute",
        operation="submit",
        key=f"dsp-sub:DSP-{row.id}",
        request={"case_id": case.id, "dispute_id": f"DSP-{row.id}"},
        now=now,
    )
    row.updated_at = now
    if out.status == "succeeded":
        row.status, row.submitted_at = "submitted", now
        row.submission_reference = str(out.result["reference"])
    else:  # failed or uncertain: never recorded as submitted
        row.status = "failed"
    return {
        "dispute_status": row.status,
        "dispute_id": f"DSP-{row.id}",
        "submission_id": row.submission_reference,
        "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        "execution_status": out.status,
        "simulated": True,
    }


def _submit_after(
    session: Session,
    case: Case,
    actor: Actor,
    payload: Any,
    now: datetime,
    ctx: EffectContext,
    outcome: Outcome,
) -> None:
    if ctx.extra["dispute_status"] == "submitted":
        _emit(
            session,
            "dispute.submitted",
            case,
            actor.user_id,
            actor.active_role,
            now,
            [case.id],
            "Dispute submission recorded · simulated · safe to retry",
            {"submission_id": ctx.extra["submission_id"], "simulated": True},
        )


# --- card controls ---


def _plan_effect(expected: tuple[str, ...], new: str):  # type: ignore[no-untyped-def]
    def effect(
        session: Session, case: Case, actor: Actor, payload: Any, now: datetime, ctx: EffectContext
    ) -> dict[str, Any]:
        row = _one(session, ControlPlan, case.id)
        current = row.status if row else "none"
        if current not in expected:
            raise _wrong(f"The control plan is {current}; this step is not available.")
        if row is None:
            row = ControlPlan(
                case_id=case.id, status=new, controls=[], created_at=now, updated_at=now
            )
            session.add(row)
        controls = getattr(payload, "controls", None)
        if controls is not None:
            row.controls = sorted(set(controls))
        reason = getattr(payload, "reason", None)
        if reason is not None:
            row.reason = reason
        if new == "proposed":
            row.proposed_by = actor.user_id
        if new in ("approved", "declined", "skipped"):
            row.decided_by = actor.user_id
        row.status, row.updated_at = new, now
        session.flush()
        return {"controls_status": new, "plan_id": row.id, "controls": list(row.controls)}

    return effect


def _record_applied(
    session: Session, case: Case, row: ControlPlan, actor: Actor, reference: str, now: datetime
) -> None:
    for control in row.controls:
        session.add(
            CardControl(
                case_id=case.id,
                plan_id=row.id,
                control=control,
                reference=reference,
                applied_by=actor.user_id,
                applied_at=now,
            )
        )
    row.status, row.updated_at = "applied", now
    session.flush()


def _apply_effect(
    session: Session, case: Case, actor: Actor, payload: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _one(session, ControlPlan, case.id)
    current = row.status if row else "none"
    if row is None or current != "approved":
        raise _wrong(f"The control plan is {current}; controls can be applied only once approved.")
    out = adapters.execute(
        session,
        case_id=case.id,
        adapter="card_controls",
        operation="apply",
        key=f"ctl-apply:{row.id}",
        request={"case_id": case.id, "plan_id": row.id, "controls": list(row.controls)},
        now=now,
    )
    applied: list[str] = []
    if out.status == "succeeded":
        _record_applied(session, case, row, actor, str(out.result["reference"]), now)
        applied = list(row.controls)
    return {
        "controls_status": row.status,
        "plan_id": row.id,
        "applied": applied,
        "applied_at": now.isoformat() if applied else None,
        "execution_status": out.status,
        "simulated": True,
    }


def _apply_after(
    session: Session,
    case: Case,
    actor: Actor,
    payload: Any,
    now: datetime,
    ctx: EffectContext,
    outcome: Outcome,
) -> None:
    if ctx.extra["controls_status"] == "applied":
        _emit(
            session,
            "controls.applied",
            case,
            actor.user_id,
            actor.active_role,
            now,
            [case.id],
            "Card controls applied · simulated · safe to retry",
            {"plan_id": ctx.extra["plan_id"], "applied": ctx.extra["applied"], "simulated": True},
        )


# --- facts and summaries (stored rows only) ---


class CreditSummary(BaseModel):
    status: str
    credit_id: str | None = None
    amount_cents: int | None = None
    currency: str | None = None
    issued_at: datetime | None = None
    simulated: bool = True


class NarrativeStatement(BaseModel):
    text: str
    record_id: str
    version: int
    field: str


class DisputeSummary(BaseModel):
    status: str
    dispute_id: str | None = None
    submission_id: str | None = None
    submitted_at: datetime | None = None
    simulated: bool = True
    # Dispute Packet Preparer output; never gates the track. None until a packet exists.
    reason_code: str | None = None
    narrative: list[NarrativeStatement] = []
    narrative_status: Literal["pending", "ready", "failed"] | None = None


class ControlsSummary(BaseModel):
    status: str
    plan_id: int | None = None
    controls: list[str] = []
    applied: list[str] = []
    reason: str | None = None
    simulated: bool = True


def credit_summary(session: Session, case_id: str) -> CreditSummary:
    row = _one(session, ProvisionalCredit, case_id)
    if row is None:
        return CreditSummary(status="none")
    return CreditSummary(
        status=row.status,
        credit_id=row.reference,
        amount_cents=row.amount_cents,
        currency=row.currency,
        issued_at=row.issued_at,
    )


def dispute_summary(session: Session, case_id: str) -> DisputeSummary:
    row = _one(session, DisputePacket, case_id)
    if row is None:
        return DisputeSummary(status="none")
    from vera_api import dispute_prep

    return DisputeSummary(
        status=row.status,
        dispute_id=f"DSP-{row.id}",
        submission_id=row.submission_reference,
        submitted_at=row.submitted_at,
        reason_code=row.reason_code,
        narrative=[NarrativeStatement.model_validate(s) for s in row.narrative or []],
        narrative_status=dispute_prep.narrative_status(session, row),
    )


def controls_summary(session: Session, case_id: str) -> ControlsSummary:
    row = _one(session, ControlPlan, case_id)
    if row is None:
        return ControlsSummary(status="none")
    applied = session.scalars(
        select(CardControl.control).where(CardControl.plan_id == row.id).order_by(CardControl.id)
    ).all()
    return ControlsSummary(
        status=row.status,
        plan_id=row.id,
        controls=list(row.controls),
        applied=list(applied),
        reason=row.reason,
    )


def _facts(session: Session, case: Case) -> dict[str, Any]:
    return {
        "credit_status": credit_summary(session, case.id).status,
        "dispute_status": dispute_summary(session, case.id).status,
        "controls_status": controls_summary(session, case.id).status,
    }


gateway.register_commands(
    __name__,
    human=domain.HUMAN,
    service=domain.SERVICE,
    effects={
        "issue_provisional_credit": _issue_effect,
        "lookup_execution_result": _lookup_effect,
        "reconcile_execution_result": _lookup_effect,
        "prepare_dispute_packet": _dispute_step(("none",), "prepared"),
        "open_dispute_packet": _dispute_step(("prepared",), "opened"),
        "review_dispute_packet": _dispute_step(("opened",), "reviewed"),
        "submit_dispute": _submit_effect,
        "recommend_card_controls": _plan_effect(("none",), "recommended"),
        "propose_card_controls": _plan_effect(("none", "recommended"), "proposed"),
        "skip_card_controls": _plan_effect(("none", "recommended"), "skipped"),
        "approve_card_controls": _plan_effect(("proposed",), "approved"),
        "decline_card_controls": _plan_effect(("proposed",), "declined"),
        "apply_card_controls": _apply_effect,
    },
    after_effects={
        "issue_provisional_credit": _credit_after(
            "credit.issued", "Temporary credit issued · {ref} · simulated · safe to retry"
        ),
        "lookup_execution_result": _credit_after(
            "credit.confirmed", "{ref} issued once · nothing re-sent"
        ),
        "reconcile_execution_result": _credit_after(
            "credit.confirmed", "{ref} issued once · nothing re-sent"
        ),
        "prepare_dispute_packet": _prepare_after,
        "submit_dispute": _submit_after,
        "apply_card_controls": _apply_after,
    },
)
gateway.register_fact_provider(_facts)
plugins.register_reset_tables(
    ["card_controls", "control_plans", "dispute_packets", "provisional_credits"]
)

# --- reconciler job: resolves an uncertain credit by lookup, never by re-issuing ---

RECONCILER_JOB = "uncertain_result_reconciler"
RECONCILER = Actor(RECONCILER_JOB, "Result reconciler", Role.SYSTEM, frozenset({Role.SYSTEM}))


@worker.register(RECONCILER_JOB)
def reconcile_uncertain(session: Session, payload: dict[str, Any], touch: worker.Touch) -> None:
    case = session.get(Case, str(payload["case_id"]))
    row = _one(session, ProvisionalCredit, case.id) if case is not None else None
    if case is None or row is None or row.status != "uncertain":
        session.rollback()
        return  # already resolved: nothing to do
    gateway.execute_command(
        session,
        now=default_demo_clock().now(),
        case_id=case.id,
        command="reconcile_execution_result",
        key=f"reconcile:{case.id}:{case.case_version}",
        expected_version=case.case_version,
        payload={"idempotency_key": row.execution_key},
        actor=RECONCILER,
        request_id=f"job:{RECONCILER_JOB}",
    )


# --- routes ---


class ExecutionView(BaseModel):
    id: int
    adapter: str
    operation: str
    idempotency_key: str
    status: str
    attempts: int
    error: str | None
    simulated: bool = True
    created_at: datetime
    updated_at: datetime


class ExecutionList(BaseModel):
    case_id: str
    executions: list[ExecutionView]


class MoneyView(BaseModel):
    case_id: str
    credit: CreditSummary
    dispute: DisputeSummary
    controls: ControlsSummary


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


def _staff(session: Session, actor: Actor, case_id: str) -> None:
    if actor.active_role not in STAFF_ROLES or actor.active_role not in actor.roles:
        raise CommandError("role_forbidden", 403, "This role cannot read execution records.")
    if session.get(Case, case_id) is None:
        raise CommandError("case_not_found", 404, "No such case.")


router = APIRouter(prefix="/api")


@router.get("/cases/{case_id}/executions")
def get_executions(case_id: str, session: DbSession, actor: ReaderDep) -> ExecutionList:
    _staff(session, actor, case_id)
    rows = session.scalars(
        select(AdapterExecution)
        .where(AdapterExecution.case_id == case_id)
        .order_by(AdapterExecution.id.desc())
    ).all()
    return ExecutionList(
        case_id=case_id,
        executions=[ExecutionView.model_validate(r, from_attributes=True) for r in rows],
    )


@router.get("/cases/{case_id}/remediation")
def get_remediation(case_id: str, session: DbSession, actor: ReaderDep) -> MoneyView:
    _staff(session, actor, case_id)
    return MoneyView(
        case_id=case_id,
        credit=credit_summary(session, case_id),
        dispute=dispute_summary(session, case_id),
        controls=controls_summary(session, case_id),
    )


plugins.register_router(router)
