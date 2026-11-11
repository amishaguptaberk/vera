"""Final communication and closure: effects, fact provider, checklist, routes.

Facts owned: `final_message_status` (latest final_messages row), `closed` and `monitoring`
(case_closures row). Commands: draft_final_message, update_final_message, send_final_message,
close_case. `send_final_message` is distinct from the follow-up `send_communication`; it sends
through the adapter framework with the adapter named `messaging`, looked up at call time (no
adapter registered -> 502 `adapter_not_registered`, nothing written).

Closure checklist seam (GET /api/cases/{id}/closure-checklist):

    register_checklist_source(name, fn: (session, case_id) -> ChecklistItem | list[ChecklistItem])

Built-in sources (registered here, read real recorded state):
    evidence_conflicts  - no open evidence conflicts (evidence._open_conflicts)
    policy_current      - a policy evaluation is stored for the current snapshot/policy version
    investigation_run   - latest investigation run succeeded
    exposure_columns    - cases.credit_cents / credit_status consistent (credit recorded if any)
    final_message       - the final cardholder update was sent (final_messages)

REQUIRED sources, registered below from the decision and money features. While one is not
registered its item is `unknown` and close_case (and draft_final_message, for the
DRAFT_PREREQUISITES) is BLOCKED with `422 closure_incomplete` naming the item - it never passes
by default:
    "decision"  - wraps `current_decision(session, case_id)` (met when a decision is
                  recorded; record id = decision id)
    "approval"  - wraps `latest_approval(session, case_id)` (met when approved and bound,
                  or the decision needs no approval)
    "credit"    - wraps `credit_summary(session, case_id)` (met when credit issued, or the
                  decision is not credit)
    "dispute"   - wraps `dispute_summary(session, case_id)` (met when submitted / accepted /
                  denied, or not applicable)
    "controls"  - wraps `controls_summary(session, case_id)` (met when applied, skipped or
                  declined, or not applicable)
"""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.closure import (
    ChecklistItem,
    CloseCasePayload,
    ClosureChecklist,
    RecordDisputeOutcomePayload,
    SendFinalMessagePayload,
    UpdateFinalMessagePayload,
    content_violations,
    reduce_close,
    reduce_dispute_outcome,
    reduce_draft,
    reduce_send,
    reduce_update,
    render_final_message,
    with_owner,
)
from vera_domain.commands import CommandSpec, NoPayload, StepSet
from vera_domain.enums import CaseState, CaseStep, Role, StateKind, register_event_types
from vera_domain.errors import CommandError
from vera_domain.labels import register_event_summaries, register_labels

from vera_api import adapters, auth, gateway, plugins, worker
from vera_api import evidence as evidence_service
from vera_api import policy as policy_service
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.config import Settings
from vera_api.gateway import EffectContext
from vera_api.models import Cardholder, CardTransaction, Case
from vera_api.models_closure import CaseClosure, FinalMessage

MESSAGING_ADAPTER = "messaging"

ChecklistSource = Callable[[Session, str], ChecklistItem | list[ChecklistItem]]
CHECKLIST_SOURCES: dict[str, ChecklistSource] = {}
REQUIRED_SOURCES: dict[str, str] = {
    "decision": "Decision recorded",
    "approval": "Approval valid for the decision",
    "credit": "Credit issued, or the decision is not credit",
    "dispute": "Dispute submitted, or not applicable",
    "controls": "Card controls applied, skipped or declined",
}
# Items that must be met before the final update is drafted.
DRAFT_PREREQUISITES = ("decision", "credit", "dispute", "controls")


def register_checklist_source(name: str, fn: ChecklistSource) -> None:
    if name in CHECKLIST_SOURCES:
        raise ValueError(f"checklist source '{name}' is already registered")
    CHECKLIST_SOURCES[name] = fn


def _case(session: Session, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise CommandError("case_not_found", 404, "Case not found.")
    return case


# ---- built-in sources ---------------------------------------------------------------------------


def _evidence_source(session: Session, case_id: str) -> ChecklistItem:
    conflicts = evidence_service._open_conflicts(session, case_id)
    ids = sorted({r for c in conflicts for r in c.record_ids})
    return ChecklistItem(
        name="evidence_conflicts",
        label="No open evidence conflicts",
        status="unmet" if conflicts else "met",
        record_ids=ids,
        detail=f"{len(conflicts)} open conflict(s)",
    )


def _policy_source(session: Session, case_id: str) -> ChecklistItem:
    case = _case(session, case_id)
    state = policy_service.current_state(session, case)
    return ChecklistItem(
        name="policy_current",
        label="Policy evaluated on the current evidence",
        status="met" if state is not None else "unmet",
        record_ids=[case.evidence_snapshot],
        detail=state.label if state is not None else "No evaluation for the current snapshot",
    )


def _investigation_source(session: Session, case_id: str) -> ChecklistItem:
    status = gateway.facts_for(session, _case(session, case_id)).investigation_run_status
    return ChecklistItem(
        name="investigation_run",
        label="Investigation complete",
        status="met" if status == "succeeded" else "unmet",
        detail=f"Investigation run {status}",
    )


def _exposure_source(session: Session, case_id: str) -> ChecklistItem:
    case = _case(session, case_id)
    ok = case.credit_cents == 0 or case.credit_status in ("issued", "finalized")
    return ChecklistItem(
        name="exposure_columns",
        label="Credit recorded on the case",
        status="met" if ok else "unmet",
        detail=f"credit_cents={case.credit_cents} credit_status={case.credit_status or 'none'}",
    )


def _final_message_source(session: Session, case_id: str) -> ChecklistItem:
    row = latest_message(session, case_id)
    sent = row is not None and row.status == "sent"
    return ChecklistItem(
        name="final_message",
        label="Final cardholder update sent",
        status="met" if sent else "unmet",
        record_ids=[row.id] if row else [],
        detail=row.status if row else "No final update drafted",
    )


register_checklist_source("evidence_conflicts", _evidence_source)
register_checklist_source("policy_current", _policy_source)
register_checklist_source("investigation_run", _investigation_source)
register_checklist_source("exposure_columns", _exposure_source)
register_checklist_source("final_message", _final_message_source)


# ---- required sources backed by the decision and remediation features ----------------------------
# Both modules load before this one (plugins.FEATURES order). The tracks follow derive_step:
# clear/violation/unresolved has no remediation; dispute runs the dispute and controls tracks;
# credit needs an approval and a credit first.
_TRACK_DECISIONS = ("credit", "dispute")
_DISPUTE_DONE = ("submitted", "accepted", "denied")
_CONTROLS_DONE = ("applied", "skipped", "declined")


def _decision_kind(session: Session, case_id: str) -> str | None:
    from vera_api import decisions

    row = decisions.current_decision(session, case_id)
    return row.decision if row is not None else None


def _decision_source(session: Session, case_id: str) -> ChecklistItem:
    from vera_api import decisions

    row = decisions.current_decision(session, case_id)
    return ChecklistItem(
        name="decision",
        label=REQUIRED_SOURCES["decision"],
        status="met" if row is not None else "unmet",
        record_ids=[str(row.id)] if row is not None else [],
        detail=f"Decision: {row.decision}" if row is not None else "No decision recorded",
    )


def _approval_source(session: Session, case_id: str) -> ChecklistItem:
    from vera_api import decisions

    kind = _decision_kind(session, case_id)
    row = decisions.latest_approval(session, case_id)
    if kind is None:
        status, detail = "unmet", "No decision recorded"
    elif kind != "credit":
        status, detail = "met", f"Not required for a {kind} decision"
    else:
        status = "met" if row is not None and row.status == "approved" else "unmet"
        detail = f"Approval {row.status}" if row is not None else "No approval requested"
    return ChecklistItem(
        name="approval",
        label=REQUIRED_SOURCES["approval"],
        status=status,
        record_ids=[row.id] if row is not None else [],
        detail=detail,
    )


def _track_item(
    name: str, kind: str | None, applies: bool, current: str, done: tuple[str, ...], ref: Any
) -> ChecklistItem:
    if kind is None:
        status, detail = "unmet", "No decision recorded"
    elif not applies:
        status, detail = "met", f"Not applicable to a {kind} decision"
    else:
        status, detail = ("met" if current in done else "unmet"), f"{name.capitalize()} {current}"
    return ChecklistItem(
        name=name,
        label=REQUIRED_SOURCES[name],
        status=status,
        record_ids=[str(ref)] if ref else [],
        detail=detail,
    )


def _credit_source(session: Session, case_id: str) -> ChecklistItem:
    from vera_api import money

    kind = _decision_kind(session, case_id)
    s = money.credit_summary(session, case_id)
    return _track_item("credit", kind, kind == "credit", s.status, ("issued",), s.credit_id)


def _dispute_source(session: Session, case_id: str) -> ChecklistItem:
    from vera_api import money

    kind = _decision_kind(session, case_id)
    s = money.dispute_summary(session, case_id)
    return _track_item(
        "dispute", kind, kind in _TRACK_DECISIONS, s.status, _DISPUTE_DONE, s.dispute_id
    )


def _controls_source(session: Session, case_id: str) -> ChecklistItem:
    from vera_api import money

    kind = _decision_kind(session, case_id)
    s = money.controls_summary(session, case_id)
    return _track_item(
        "controls", kind, kind in _TRACK_DECISIONS, s.status, _CONTROLS_DONE, s.plan_id
    )


register_checklist_source("decision", _decision_source)
register_checklist_source("approval", _approval_source)
register_checklist_source("credit", _credit_source)
register_checklist_source("dispute", _dispute_source)
register_checklist_source("controls", _controls_source)


def checklist(session: Session, case_id: str) -> ClosureChecklist:
    _case(session, case_id)
    items: list[ChecklistItem] = []
    for name, label in REQUIRED_SOURCES.items():
        if name not in CHECKLIST_SOURCES:
            items.append(
                ChecklistItem(
                    name=name, label=label, status="unknown", detail="Source not registered"
                )
            )
    for fn in CHECKLIST_SOURCES.values():
        got = fn(session, case_id)
        items.extend(got if isinstance(got, list) else [got])
    items = [with_owner(i) for i in items]
    return ClosureChecklist(
        case_id=case_id, ready=all(i.status == "met" for i in items), items=items
    )


def _require(items: list[ChecklistItem], what: str) -> None:
    open_items = [i for i in items if i.status != "met"]
    if open_items:
        names = "; ".join(
            f"{i.label} ({i.status}) - {i.owner}: {i.next_action}" for i in open_items
        )
        raise CommandError("closure_incomplete", 422, f"{what}: {names}.")


# ---- rows and facts -----------------------------------------------------------------------------


def latest_message(session: Session, case_id: str) -> FinalMessage | None:
    return session.scalars(
        select(FinalMessage)
        .where(FinalMessage.case_id == case_id)
        .order_by(FinalMessage.created_at.desc(), FinalMessage.id.desc())
    ).first()


def closure_record(session: Session, case_id: str) -> CaseClosure | None:
    return session.scalars(select(CaseClosure).where(CaseClosure.case_id == case_id)).first()


def _facts(session: Session, case: Case) -> dict[str, Any]:
    msg = latest_message(session, case.id)
    out: dict[str, Any] = {"final_message_status": msg.status if msg else "none"}
    row = closure_record(session, case.id)
    if row is not None:
        # `closed` is a case-row fact: close_case / record_dispute_outcome set it via the reducer.
        out["monitoring"] = row.monitoring
    return out


def _cardholder_name(session: Session, case: Case) -> str:
    txn = session.get(CardTransaction, case.transaction_id)
    holder = session.get(Cardholder, txn.cardholder_id) if txn else None
    return holder.name if holder else "cardholder"


def _check_content(session: Session, case: Case, body: str) -> None:
    bad = content_violations(body, gateway.facts_for(session, case))
    if bad:
        claim = bad[0]
        raise CommandError(
            "content_policy_violation",
            422,
            f"The message states an action that is not recorded ({claim['claim']}): "
            f"{claim['sentence']}",
            blocked_reason=claim["claim"],
        )


# ---- effects ------------------------------------------------------------------------------------


def _draft_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    _require(
        [i for i in checklist(session, case.id).items if i.name in DRAFT_PREREQUISITES],
        "The final update needs recorded outcomes",
    )
    facts = gateway.facts_for(session, case)
    body = render_final_message(
        facts, cardholder_name=_cardholder_name(session, case), case_id=case.id
    )
    _check_content(session, case, body)
    row = FinalMessage(
        id=f"MSG-{uuid.uuid4().hex[:10]}",
        case_id=case.id,
        body=body,
        status="drafted",
        created_by=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return {"message_id": row.id}


def _drafted(session: Session, case: Case) -> FinalMessage:
    row = latest_message(session, case.id)
    if row is None or row.status != "drafted":
        raise CommandError("final_message_not_drafted", 409, "No drafted final update to use.")
    return row


def _update_effect(
    session: Session,
    case: Case,
    actor: Actor,
    p: UpdateFinalMessagePayload,
    now: datetime,
    ctx: EffectContext,
) -> dict[str, Any]:
    row = _drafted(session, case)
    _check_content(session, case, p.body)
    row.body = p.body
    row.updated_at = now
    session.flush()
    return {"message_id": row.id}


MESSAGING_UNAVAILABLE = "Messaging is not available"


def _send_effect(
    session: Session,
    case: Case,
    actor: Actor,
    p: SendFinalMessagePayload,
    now: datetime,
    ctx: EffectContext,
) -> dict[str, Any]:
    row = _drafted(session, case)
    if p.body is not None and p.body != row.body:
        raise CommandError(
            "final_message_edited",
            422,
            "The body differs from the stored draft. Edits go through update_final_message.",
        )
    if MESSAGING_ADAPTER not in adapters.ADAPTERS:
        raise CommandError(
            "blocked", 409, MESSAGING_UNAVAILABLE, blocked_reason=MESSAGING_UNAVAILABLE
        )
    _check_content(session, case, row.body)  # facts may have changed since the draft
    result = adapters.execute(
        session,
        case_id=case.id,
        adapter=MESSAGING_ADAPTER,
        operation="send_final_message",
        key=f"final-msg:{row.id}",
        request={"message_id": row.id, "channel": "email", "body": row.body},
        now=now,
    )
    if result.status == "failed":
        raise CommandError("adapter_failed", 502, "The message was not sent. Safe to retry.")
    if result.status == "uncertain":
        raise CommandError("adapter_uncertain", 504, "Checking whether the message was sent.")
    row.status = "sent"
    row.sent_at = now
    row.execution_id = result.execution_id
    row.updated_at = now
    session.flush()
    return {"message_id": row.id, "execution_id": result.execution_id}


def _close_effect(
    session: Session,
    case: Case,
    actor: Actor,
    p: CloseCasePayload,
    now: datetime,
    ctx: EffectContext,
) -> dict[str, Any]:
    items = checklist(session, case.id).items
    _require(items, "The case cannot close")
    monitoring = gateway.facts_for(session, case).dispute_status == "submitted"
    row = CaseClosure(
        id=f"CLS-{uuid.uuid4().hex[:10]}",
        case_id=case.id,
        reason=p.reason,
        outcome=p.outcome,
        monitoring=monitoring,
        evidence_snapshot=case.evidence_snapshot,
        checklist=[i.model_dump() for i in items],
        closed_by=actor.user_id,
        closed_at=now,
    )
    session.add(row)
    session.flush()
    return {"closure_id": row.id, "monitoring": monitoring}


def _dispute_outcome_effect(
    session: Session,
    case: Case,
    actor: Actor,
    p: RecordDisputeOutcomePayload,
    now: datetime,
    ctx: EffectContext,
) -> dict[str, Any]:
    row = closure_record(session, case.id)
    if row is None or not row.monitoring:
        raise CommandError("invalid_step", 409, "The case is not monitoring a dispute.")
    return {"closure_id": row.id}


# ---- registration -------------------------------------------------------------------------------

register_event_types(
    "final_message.drafted",
    "final_message.updated",
    "final_message.sent",
    "case.closed",
    "dispute.outcome_recorded",
)
register_event_summaries(
    {
        "final_message.drafted": "Final update drafted from recorded state",
        "final_message.updated": "Final update edited",
        "final_message.sent": "Final update sent to the cardholder",
        "case.closed": "Case closed",
        "dispute.outcome_recorded": "Dispute outcome received",
    }
)
register_labels(
    {
        (CaseState.REMEDIATION_PENDING, CaseStep.FINALPREP): (
            "Final update not sent",
            StateKind.IDLE,
            "Draft the final update",
        ),
        (CaseState.REMEDIATION_PENDING, CaseStep.FINAL): (
            "Final update not sent",
            StateKind.REVIEW,
            "Review and send the final update",
        ),
        (CaseState.REMEDIATION_PENDING, CaseStep.CLOSE): (
            "Ready to close",
            StateKind.IDLE,
            "Close the case",
        ),
        (CaseState.MONITORING, CaseStep.MONITORING): (
            "Monitoring",
            StateKind.WAITING,
            "Waiting for the dispute outcome.",
        ),
        (CaseState.CLOSED, CaseStep.CLOSED): ("Closed", StateKind.COMPLETE, "No action needed"),
    }
)

_RP = CaseState.REMEDIATION_PENDING
_ANALYST = frozenset({Role.ANALYST})

DRAFT = CommandSpec(
    "draft_final_message",
    _ANALYST,
    NoPayload,
    StepSet(include=frozenset({(_RP, CaseStep.FINALPREP)})),
    "final:{case_id}",
    reduce_draft,
    ("final_message.drafted",),
    "Draft final update",
    "primary",
)
UPDATE = CommandSpec(
    "update_final_message",
    _ANALYST,
    UpdateFinalMessagePayload,
    StepSet(include=frozenset({(_RP, CaseStep.FINAL)})),
    "final-edit:{case_id}:{case_version}",
    reduce_update,
    ("final_message.updated",),
    "Edit final update",
    "secondary",
)
SEND = CommandSpec(
    "send_final_message",
    _ANALYST,
    SendFinalMessagePayload,
    StepSet(include=frozenset({(_RP, CaseStep.FINAL)})),
    "final-send:{case_id}",
    reduce_send,
    ("final_message.sent",),
    "Send final update",
    "primary",
    adapter=MESSAGING_ADAPTER,
)
CLOSE = CommandSpec(
    "close_case",
    _ANALYST,
    CloseCasePayload,
    StepSet(include=frozenset({(_RP, CaseStep.CLOSE)})),
    "close:{case_id}",
    reduce_close,
    ("case.closed",),
    "Close case",
    "primary",
)

# Service principal only (the card network adapter via the ingest job); the one command the
# closed gate lets through while the case is MONITORING.
DISPUTE_OUTCOME = CommandSpec(
    "record_dispute_outcome",
    frozenset({Role.SYSTEM}),
    RecordDisputeOutcomePayload,
    StepSet(include=frozenset({(CaseState.MONITORING, CaseStep.MONITORING)})),
    "dispute-outcome:{case_id}",
    reduce_dispute_outcome,
    ("dispute.outcome_recorded", "case.closed"),
    "Record dispute outcome",
    "ghost",
    allowed_in_monitoring=True,
)

gateway.register_commands(
    __name__,
    human={s.name: s for s in (DRAFT, UPDATE, SEND, CLOSE)},
    service={DISPUTE_OUTCOME.name: DISPUTE_OUTCOME},
    effects={
        DRAFT.name: _draft_effect,
        UPDATE.name: _update_effect,
        SEND.name: _send_effect,
        CLOSE.name: _close_effect,
        DISPUTE_OUTCOME.name: _dispute_outcome_effect,
    },
)


# ---- what the case view offers: the same preconditions the effects check -------------------------


def _open_items(items: list[ChecklistItem], what: str) -> CommandError | None:
    try:
        _require(items, what)
    except CommandError as err:
        return gateway.blocked(err.code, err.message)
    return None


def _draft_not_ready(session: Session, case: Case) -> CommandError | None:
    items = [i for i in checklist(session, case.id).items if i.name in DRAFT_PREREQUISITES]
    return _open_items(items, "The final update needs recorded outcomes")


def _no_drafted_message(session: Session, case: Case) -> CommandError | None:
    try:
        _drafted(session, case)
    except CommandError as err:
        return gateway.blocked(err.code, err.message)
    return None


def _not_closable(session: Session, case: Case) -> CommandError | None:
    return _open_items(checklist(session, case.id).items, "The case cannot close")


gateway.register_actions(
    __name__,
    guards={
        DRAFT.name: _draft_not_ready,
        UPDATE.name: _no_drafted_message,
        SEND.name: _no_drafted_message,
        CLOSE.name: _not_closable,
    },
)
gateway.register_fact_provider(_facts)
plugins.register_reset_tables(["case_closures", "final_messages"])


# ---- routes -------------------------------------------------------------------------------------


class FinalMessageView(BaseModel):
    message_id: str
    status: str
    body: str
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    execution_id: int | None


class ClosureRecordView(BaseModel):
    closure_id: str
    reason: str
    outcome: str
    state: str
    closed_by: str
    closed_at: datetime
    evidence_snapshot: str
    checklist: list[ChecklistItem]


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def _actor(request: Request, session: Annotated[Session, Depends(_session)]) -> Actor:
    settings: Settings = request.app.state.settings
    actor = auth.load_actor(
        session, settings.secret(), request.cookies.get(auth.COOKIE), settings.synthetic
    )
    if actor.active_role not in STAFF_ROLES or actor.active_role not in actor.roles:
        raise CommandError("role_forbidden", 403, "This role cannot read the closure record.")
    return actor


DbSession = Annotated[Session, Depends(_session)]
StaffDep = Annotated[Actor, Depends(_actor)]
router = APIRouter(prefix="/api")


@router.get("/cases/{case_id}/closure-checklist")
def get_checklist(case_id: str, session: DbSession, actor: StaffDep) -> ClosureChecklist:
    return checklist(session, case_id)


@router.get("/cases/{case_id}/final-message")
def get_final_message(case_id: str, session: DbSession, actor: StaffDep) -> FinalMessageView | None:
    _case(session, case_id)
    row = latest_message(session, case_id)
    if row is None:
        return None
    return FinalMessageView(
        message_id=row.id,
        status=row.status,
        body=row.body,
        created_at=row.created_at,
        updated_at=row.updated_at,
        sent_at=row.sent_at,
        execution_id=row.execution_id,
    )


@router.get("/cases/{case_id}/closure")
def get_closure(case_id: str, session: DbSession, actor: StaffDep) -> ClosureRecordView | None:
    _case(session, case_id)
    row = closure_record(session, case_id)
    if row is None:
        return None
    return ClosureRecordView(
        closure_id=row.id,
        reason=row.reason,
        outcome=row.outcome,
        state="monitoring" if row.monitoring else "closed",
        closed_by=row.closed_by,
        closed_at=row.closed_at,
        evidence_snapshot=row.evidence_snapshot,
        checklist=[ChecklistItem.model_validate(i) for i in row.checklist],
    )


plugins.register_router(router)


# ---- dispute outcome ingestion (worker job + synthetic trigger) ---------------------------------

DISPUTE_OUTCOME_JOB = "dispute_outcome_ingest"
NETWORK = Actor("svc-dispute-network", "Card network", Role.SYSTEM, frozenset({Role.SYSTEM}))


@worker.register(DISPUTE_OUTCOME_JOB)
def ingest_dispute_outcome(session: Session, payload: dict[str, Any], touch: Any) -> None:
    """Apply a reported dispute outcome through the gateway as the network service principal.
    The idempotency key is per case, so a re-delivered job replays instead of writing twice."""
    case_id = str(payload["case_id"])
    body = {"outcome": payload["outcome"], "reference": payload["reference"]}
    for _ in range(8):
        version = session.scalars(select(Case.case_version).where(Case.id == case_id)).one()
        session.rollback()
        try:
            gateway.execute_command(
                session,
                now=datetime.now(UTC),
                case_id=case_id,
                command=DISPUTE_OUTCOME.name,
                key=f"dispute-outcome:{case_id}",
                expected_version=version,
                payload=body,
                actor=NETWORK,
                request_id=f"worker:dispute-outcome:{case_id}",
            )
            return
        except CommandError as exc:
            if exc.code != "stale_case_version":
                raise
    raise RuntimeError("record_dispute_outcome kept racing on the case version")


class DisputeOutcomeRequest(BaseModel):
    case_id: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    # The simulated network's reference; defaults to one derived from the case.
    reference: str | None = Field(default=None, min_length=1, max_length=100)


demo_router = APIRouter(prefix="/api/demo")


@demo_router.post("/dispute-outcome")
def post_dispute_outcome(body: DisputeOutcomeRequest, session: DbSession) -> dict[str, Any]:
    """Synthetic only: queue the network's dispute outcome; a worker applies it."""
    _case(session, body.case_id)
    payload = {**body.model_dump(), "reference": body.reference or f"NET-{body.case_id}"}
    job_id = worker.enqueue(session, DISPUTE_OUTCOME_JOB, payload)
    session.commit()
    return {"job_id": job_id, "kind": DISPUTE_OUTCOME_JOB}


plugins.register_router(demo_router, synthetic_only=True)
