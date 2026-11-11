"""Cardholder follow-up (VER-005): effects, fact provider, messaging adapter, routes, watcher."""

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from vera_domain import comms as dom
from vera_domain.adapters import AdapterResult
from vera_domain.clock import Clock
from vera_domain.enums import CaseState, CaseStep, Role, StateKind
from vera_domain.errors import CommandError
from vera_domain.evidence import content_hash
from vera_domain.labels import register_event_summaries, register_labels
from vera_domain.specialists import ExecutionMode, StepStatus

from vera_api import adapters, auth, evidence, gateway, plugins
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.config import Settings
from vera_api.gateway import EffectContext
from vera_api.model_client import PROBE_TOOL, default_mode
from vera_api.models import AuditEvent, CardTransaction, Case, User
from vera_api.models_comms import Communication, CommunicationDraft, CommunicationResponse
from vera_api.models_evidence import (
    Attachment,
    EvidenceRecord,
    EvidenceVersion,
    Finding,
    FindingLink,
)
from vera_api.models_runs import WorkflowRun
from vera_api.runner import SpecialistRunner, create_run
from vera_api.worker import FAILURE_HOOKS, Touch, enqueue, register, run_once


def _inv() -> ModuleType:
    """vera_api.investigation, imported on use: it imports vera_api.evidence, which loads the
    gateway and with it this feature, so a top-level import is circular."""
    from vera_api import investigation

    return investigation


REPLY_WINDOW = timedelta(days=3)
FIRST_MESSAGE = 2201
WATCHER = Actor("svc-deadline-watcher", "Deadline watcher", Role.SYSTEM, frozenset({Role.SYSTEM}))

register_event_summaries(
    {
        "communication.drafted": "Follow-up drafted for analyst approval",
        "communication.updated": "Follow-up draft edited",
        "communication.sent": "Request sent to the cardholder",
        "communication.reminded": "Reminder sent to the cardholder",
        "communication.overdue": "Reply deadline missed",
        "communication.responded": "Cardholder replied to the request",
        "communication.reviewed": "Cardholder response reviewed",
    }
)

_W = CaseState.WAITING_ON_CARDHOLDER
register_labels(
    {
        (_W, CaseStep.WAITING): ("Waiting on cardholder", StateKind.WAITING, "Send reminder"),
        (_W, CaseStep.NORESP1): ("Response overdue", StateKind.BLOCKED, "Send a reminder"),
        (_W, CaseStep.NORESP2): ("Response overdue", StateKind.BLOCKED, "Escalate the case"),
        (CaseState.RESPONSE_RECEIVED, CaseStep.RESPONSE): (
            "Needs review",
            StateKind.REVIEW,
            "Review the cardholder response",
        ),
    }
)


# ---- simulated messaging adapter -----------------------------------------------------------------


class SimulatedMessaging:
    """Synthetic delivery: never contacts anyone; the execution record is the delivery receipt."""

    def call(self, operation: str, request: dict[str, Any]) -> AdapterResult:
        # The one `messaging` adapter: follow-ups send communication_id, closure's final
        # update (send_final_message) sends message_id.
        ref = request.get("communication_id") or request["message_id"]
        return AdapterResult(
            status="succeeded",
            result={
                "delivery_id": f"DLV-{ref}-{operation}",
                "status": "delivered",
                "channel": request["channel"],
                "synthetic": True,
            },
        )


adapters.register_adapter("messaging", SimulatedMessaging())


# ---- reads --------------------------------------------------------------------------------------


def latest_communication(session: Session, case_id: str) -> Communication | None:
    return session.scalars(
        select(Communication)
        .where(Communication.case_id == case_id)
        .order_by(Communication.created_at.desc(), Communication.id.desc())
    ).first()


def latest_response_review(session: Session, case_id: str) -> str:
    """'none' | 'complete' | 'incomplete' | 'conflicting' for the case's current request."""
    row = latest_communication(session, case_id)
    return row.response_review if row else "none"


def _facts(session: Session, case: Case) -> dict[str, Any]:
    row = latest_communication(session, case.id)
    if row is None:
        return {}
    return {
        "followup_status": row.status,
        "followups_sent": row.reminders,
        "response_review": row.response_review,
    }


def _require(session: Session, case: Case) -> Communication:
    row = latest_communication(session, case.id)
    if row is None:
        raise CommandError("communication_not_found", 404, "No cardholder request on this case.")
    return row


# ---- effects ------------------------------------------------------------------------------------

FU_PREFIX = "run_fu_"
RR_PREFIX = "run_rr_"
FU_JOB = "follow_up_drafter"
RR_JOB = "response_reviewer"
WATCH_JOB = "deadline_watcher"


def _unresolved(session: Session, case_id: str) -> tuple[list[dom.OpenFindingRef], list[str]]:
    """Open findings (with their cited record/version/field) and missing records."""
    findings = session.scalars(
        select(Finding).where(Finding.case_id == case_id, Finding.status == "open")
    ).all()
    out = []
    for f in sorted(findings, key=lambda x: x.id):
        stmt = select(FindingLink).where(FindingLink.finding_id == f.id)
        links = session.scalars(stmt.order_by(FindingLink.id)).all()  # stable request text
        out.append(
            dom.OpenFindingRef(
                finding_id=f.id,
                kind=f.kind,
                links=[
                    dom.ItemRef(record_id=lk.record_id, version=lk.version, field=lk.field)
                    for lk in links
                ],
            )
        )
    missing = session.scalars(
        select(EvidenceRecord.id).where(
            EvidenceRecord.case_id == case_id, EvidenceRecord.status == "missing"
        )
    ).all()
    return out, sorted(missing)


def _guard_no_followup(session: Session, case: Case) -> None:
    if latest_communication(session, case.id) is not None:
        raise CommandError("followup_exists", 409, "This case already has a cardholder request.")


def _draft(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    """Starts the Cardholder Follow-up specialist; it drafts, the analyst approves and sends."""
    _guard_no_followup(session, case)
    try:
        mode = default_mode()
    except (RuntimeError, ValueError) as exc:
        raise CommandError("execution_mode_unset", 503, str(exc)) from None
    run_id = create_run(
        session,
        case_id=case.id,
        mode=mode,
        now=now,
        run_id=f"{FU_PREFIX}{uuid.uuid4().hex[:10]}",
        commit=False,
    )
    job_id = enqueue(session, FU_JOB, {"run_id": run_id, "case_id": case.id}, now=now)
    return {"run_id": run_id, "job_id": job_id, "mode": mode.value}  # reducer: run running


def _recommend(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _require(session, case)
    run = session.get(WorkflowRun, p.run_id)
    if run is None or run.case_id != case.id:
        raise CommandError("run_not_found", 404, f"No run '{p.run_id}' on this case.")
    run.status, run.updated_at = "succeeded", now
    row.review_recommendation = {
        "response_id": p.response_id,
        "classification": p.classification,
        "citations": [c.model_dump(mode="json") for c in p.citations],
        "run_id": p.run_id,
    }
    session.flush()
    return {
        "request_id": row.id,
        "recommendation": p.classification,
        "_facts": {"investigation_run_status": "succeeded"},
    }


def _retry(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    run = _inv().latest_run(session, case.id)
    if run is None or not run.id.startswith(FU_PREFIX) or run.status != "failed":
        raise CommandError("invalid_step", 409, "No failed follow-up draft to retry.")
    run.status, run.updated_at = "running", now
    job_id = enqueue(
        session, FU_JOB, {"run_id": run.id, "case_id": case.id, "mode": p.mode}, now=now
    )
    return {"run_id": run.id, "job_id": job_id, "mode": p.mode}


def _store_draft(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    _guard_no_followup(session, case)
    run = session.get(WorkflowRun, p.run_id)
    if run is None or run.case_id != case.id:
        raise CommandError("run_not_found", 404, f"No run '{p.run_id}' on this case.")
    run.status, run.updated_at = "succeeded", now
    n = session.scalar(select(func.count()).select_from(Communication)) or 0
    questions = [q.text for q in p.questions]
    body = "Hello,\n\n" + "\n".join(f"- {q}" for q in questions) + "\n\nThank you."
    row = Communication(
        id=f"MSG-{FIRST_MESSAGE + n}",
        case_id=case.id,
        status="drafted",
        subject=p.subject,
        body=body,
        questions=questions,
        attachments=[],
        reminders=0,
        response_review="none",
        created_by=actor.user_id,
        created_at=now,
    )
    session.add(row)
    session.flush()
    session.add(
        CommunicationDraft(
            communication_id=row.id,
            version=1,
            subject=p.subject,
            body=body,
            created_by=actor.user_id,
            created_at=now,
        )
    )
    session.flush()
    return {
        "request_id": row.id,
        "questions": questions,
        "version": 1,
        "_facts": {"investigation_run_status": "succeeded", "followup_status": "drafted"},
    }


def _update(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _require(session, case)
    if row.status != "drafted":
        raise CommandError("communication_sent", 409, "The request was already sent.")
    v = session.scalar(
        select(func.max(CommunicationDraft.version)).where(
            CommunicationDraft.communication_id == row.id
        )
    )
    session.add(
        CommunicationDraft(
            communication_id=row.id,
            version=(v or 0) + 1,
            subject=p.subject,
            body=p.body,
            created_by=actor.user_id,
            created_at=now,
        )
    )
    row.subject, row.body = p.subject, p.body
    session.flush()
    return {"request_id": row.id, "version": (v or 0) + 1}


def _deliver(session: Session, case: Case, row: Communication, op: str, now: datetime) -> Any:
    res = adapters.execute(
        session,
        case_id=case.id,
        adapter="messaging",
        operation=op,
        key=f"{op}:{row.id}:{row.reminders}",
        request={
            "case_id": case.id,
            "communication_id": row.id,
            "channel": row.channel,
            "subject": row.subject,
            "attachments": row.attachments,
        },
        now=now,
    )
    if res.status != "succeeded":
        raise CommandError(
            "delivery_not_confirmed", 502, f"Messaging returned '{res.status}'; nothing was sent."
        )
    return res


def _send(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _require(session, case)
    row.channel, row.subject, row.attachments = p.channel, p.subject, list(p.attachments)
    res = _deliver(session, case, row, "send", now)
    row.status, row.sent_by, row.sent_at = "sent", actor.user_id, now
    row.due_at = now + REPLY_WINDOW
    row.delivery = res.result
    session.flush()
    return {
        "request_id": row.id,
        "case_id": case.id,
        "channel": row.channel,
        "subject": row.subject,
        "attachments": row.attachments,
        "delivery": res.result,
        "execution_id": res.execution_id,
        "due_at": row.due_at.isoformat(),
    }


def _remind(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _require(session, case)
    if row.reminders >= 1 and row.status == "reminded":
        raise CommandError("reminder_pending", 409, "A reminder is already waiting for a reply.")
    res = _deliver(session, case, row, "remind", now)
    row.reminders += 1
    row.status, row.due_at = "reminded", now + REPLY_WINDOW
    session.flush()
    return {"request_id": row.id, "followups_sent": row.reminders, "delivery": res.result}


def _deadline(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _require(session, case)
    if row.due_at is None or row.due_at > now:
        raise CommandError("deadline_not_passed", 409, "The reply deadline has not passed.")
    row.status, row.overdue_at = "overdue", now
    session.flush()
    return {"request_id": row.id, "owner_id": case.owner_id, "overdue_at": now.isoformat()}


def _respond(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = session.get(Communication, p.request_id)
    user = session.get(User, actor.user_id)
    if row is None or row.case_id != case.id or user is None:
        raise CommandError("request_not_found", 404, "No such request.")
    txn = session.get(CardTransaction, case.transaction_id)
    if user.cardholder_id is None or txn is None or user.cardholder_id != txn.cardholder_id:
        raise CommandError("request_not_found", 404, "No such request.")
    record_id: str | None = None
    if p.attachment is not None:
        if p.attachment.content_type not in dom.ALLOWED_TYPES:
            raise CommandError(
                "attachment_type_rejected", 422, "Only PDF, PNG or JPEG files can be attached."
            )
        record_id = f"RCP-{row.id.removeprefix('MSG-')}"
        fields = {"file_name": p.attachment.file_name, "source_request": row.id}
        session.add(
            EvidenceRecord(id=record_id, case_id=case.id, kind="receipt", status="pending_review")
        )
        session.flush()
        session.add(
            EvidenceVersion(
                record_id=record_id,
                version=1,
                material_version=1,
                fields=fields,
                content_hash=content_hash("receipt", fields),
                source="cardholder response",
                created_by=actor.user_id,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Attachment(
                record_id=record_id,
                version=1,
                uploader=actor.user_id,
                created_at=now,
                **p.attachment.model_dump(),
            )
        )
        session.flush()
        evidence.recompute_snapshot(session, case)
    rsp = CommunicationResponse(
        id=f"RSP-{row.id.removeprefix('MSG-')}",
        communication_id=row.id,
        text=p.text,
        evidence_record_id=record_id,
        submitted_by=actor.user_id,
        submitted_at=now,
    )
    session.add(rsp)
    row.status = "responded"
    session.flush()
    out: dict[str, Any] = {
        "request_id": row.id,
        "response_id": rsp.id,
        "evidence_record_id": record_id,
    }
    try:
        mode = default_mode()
    except (RuntimeError, ValueError):
        return out  # no execution mode: the analyst reviews without a recommendation
    run_id = create_run(
        session, case_id=case.id, mode=mode, now=now, run_id=f"{RR_PREFIX}{rsp.id}", commit=False
    )
    enqueue(session, RR_JOB, {"run_id": run_id, "case_id": case.id}, now=now)
    return {**out, "_facts": {"investigation_run_status": "running"}}


def _review(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _require(session, case)
    row.response_review = p.outcome
    finding_id: str | None = None
    if p.outcome == "conflicting":
        finding_id = f"FND-{row.id}-conflict"
        if session.get(Finding, finding_id) is None:
            session.add(
                Finding(
                    id=finding_id,
                    case_id=case.id,
                    kind="conflict",
                    statement=p.note or "The cardholder response contradicts REP-1042.",
                    status="open",
                    created_by=actor.user_id,
                    created_at=now,
                )
            )
    session.flush()
    return {
        "request_id": row.id,
        "response_review": p.outcome,
        "finding_id": finding_id,
    }


def _request_key(session: Session, case: Case, body: dict[str, Any]) -> dict[str, object]:
    row = latest_communication(session, case.id)
    run = _inv().latest_run(session, case.id)
    return {"request_id": row.id if row else "none", "run_id": run.id if run else "none"}


gateway.register_commands(
    __name__,
    human=dom.HUMAN,
    service=dom.SERVICE,
    effects={
        "draft_follow_up": _draft,
        "retry_follow_up_draft": _retry,
        "store_communication_draft": _store_draft,
        "store_review_recommendation": _recommend,
        "update_communication_draft": _update,
        "send_communication": _send,
        "send_reminder": _remind,
        "submit_cardholder_response": _respond,
        "review_cardholder_response": _review,
        "mark_deadline_missed": _deadline,
    },
    key_context=_request_key,
)
gateway.register_fact_provider(_facts)
plugins.register_reset_tables(["communication_responses", "communication_drafts", "communications"])


# ---- routes -------------------------------------------------------------------------------------


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def _actor(request: Request, session: Annotated[Session, Depends(_session)]) -> Actor:
    settings: Settings = request.app.state.settings
    return auth.load_actor(
        session, settings.secret(), request.cookies.get(auth.COOKIE), settings.synthetic
    )


DbSession = Annotated[Session, Depends(_session)]
ActorDep = Annotated[Actor, Depends(_actor)]


def _staff(actor: Actor) -> None:
    if actor.active_role not in STAFF_ROLES or actor.active_role not in actor.roles:
        raise CommandError("role_forbidden", 403, "This role cannot read communications.")


class CommunicationItem(BaseModel):
    id: str
    kind: str
    status: str
    title: str
    at: datetime
    channel: str | None
    due_at: datetime | None
    reminders: int
    response_review: str


class ResponseView(BaseModel):
    id: str
    text: str
    evidence_record_id: str | None
    submitted_at: datetime


class CommunicationDetail(CommunicationItem):
    subject: str
    body: str
    questions: list[str]
    attachments: list[str]
    delivery: dict[str, Any] | None
    draft_versions: int
    response: ResponseView | None


class CardholderRequest(BaseModel):
    """Cardholder-facing: only this request's question text and status."""

    request_id: str
    status: str
    subject: str
    questions: list[str]
    due_at: datetime | None
    responded: bool


class CardholderRequestList(BaseModel):
    requests: list[CardholderRequest]


class ResponseIn(BaseModel):
    text: str
    attachment: dom.ResponseAttachment | None = None


class ResponseOut(BaseModel):
    request_id: str
    status: str
    received: bool


def _item(row: Communication) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "title": row.subject,
        "at": row.sent_at or row.created_at,
        "channel": row.channel,
        "due_at": row.due_at,
        "reminders": row.reminders,
        "response_review": row.response_review,
    }


router = APIRouter(prefix="/api")
demo_router = APIRouter(prefix="/api/demo")


@router.get("/cases/{case_id}/communications")
def list_communications(
    case_id: str, session: DbSession, actor: ActorDep
) -> list[CommunicationItem]:
    _staff(actor)
    rows = session.scalars(
        select(Communication).where(Communication.case_id == case_id).order_by(Communication.id)
    )
    return [CommunicationItem(**_item(r)) for r in rows]


@router.get("/cases/{case_id}/communications/{item_id}")
def get_communication(
    case_id: str, item_id: str, session: DbSession, actor: ActorDep
) -> CommunicationDetail:
    _staff(actor)
    row = session.get(Communication, item_id)
    if row is None or row.case_id != case_id:
        raise CommandError("communication_not_found", 404, f"No communication '{item_id}'.")
    rsp = session.scalars(
        select(CommunicationResponse).where(CommunicationResponse.communication_id == row.id)
    ).first()
    versions = session.scalar(
        select(func.count()).where(CommunicationDraft.communication_id == row.id)
    )
    return CommunicationDetail(
        **_item(row),
        subject=row.subject,
        body=row.body,
        questions=row.questions,
        attachments=row.attachments,
        delivery=row.delivery,
        draft_versions=versions or 0,
        response=ResponseView(
            id=rsp.id,
            text=rsp.text,
            evidence_record_id=rsp.evidence_record_id,
            submitted_at=rsp.submitted_at,
        )
        if rsp
        else None,
    )


def _cardholder_rows(session: Session, actor: Actor) -> list[Communication]:
    if actor.active_role is not Role.CARDHOLDER or Role.CARDHOLDER not in actor.roles:
        raise CommandError("role_forbidden", 403, "Only the cardholder can read their requests.")
    user = session.get(User, actor.user_id)
    if user is None or user.cardholder_id is None:
        return []
    return list(
        session.scalars(
            select(Communication)
            .join(Case, Case.id == Communication.case_id)
            .join(CardTransaction, CardTransaction.id == Case.transaction_id)
            .where(
                CardTransaction.cardholder_id == user.cardholder_id,
                Communication.status != "drafted",
            )
            .order_by(Communication.id)
        )
    )


def _public(row: Communication) -> CardholderRequest:
    return CardholderRequest(
        request_id=row.id,
        status="answered" if row.status == "responded" else "awaiting_reply",
        subject=row.subject,
        questions=row.questions,
        due_at=row.due_at,
        responded=row.status == "responded",
    )


@router.get("/requests")
def my_requests(session: DbSession, actor: ActorDep, mine: bool = True) -> CardholderRequestList:
    return CardholderRequestList(requests=[_public(r) for r in _cardholder_rows(session, actor)])


@router.get("/requests/{request_id}")
def get_request(request_id: str, session: DbSession, actor: ActorDep) -> CardholderRequest:
    row = next((r for r in _cardholder_rows(session, actor) if r.id == request_id), None)
    if row is None:
        raise CommandError("request_not_found", 404, "No such request.")
    return _public(row)


@router.post("/requests/{request_id}/responses")
def post_response(
    request_id: str, body: ResponseIn, request: Request, session: DbSession, actor: ActorDep
) -> ResponseOut:
    row = next((r for r in _cardholder_rows(session, actor) if r.id == request_id), None)
    if row is None:
        raise CommandError("request_not_found", 404, "No such request.")
    case = session.get(Case, row.case_id)
    assert case is not None
    version, case_id = case.case_version, case.id
    session.rollback()
    clock: Clock = request.app.state.clock
    payload: dict[str, Any] = {"request_id": request_id, "text": body.text}
    if body.attachment is not None:
        payload["attachment"] = body.attachment.model_dump()
    gateway.execute_command(
        session,
        now=clock.now(),
        case_id=case_id,
        command="submit_cardholder_response",
        key=f"respond:{request_id}",
        expected_version=version,
        payload=payload,
        actor=actor,
        request_id=request.headers.get("x-request-id") or uuid.uuid4().hex,
    )
    return ResponseOut(request_id=request_id, status="answered", received=True)


# ---- worker jobs: specialists and the deadline watcher ------------------------------------------


def _factory(session: Session) -> sessionmaker[Session]:
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    return sessionmaker(engine, expire_on_commit=False)


def _evidence_reader(
    session: Session, case_id: str, allow: Callable[[str, str], bool]
) -> Callable[[str, str], tuple[Any, int]]:
    def read(record_id: str, field: str) -> tuple[Any, int]:
        if not allow(record_id, field):
            raise LookupError(f"{record_id}.{field} is not an unresolved item")
        try:
            return evidence.read_evidence_field(session, case_id, record_id, field)
        except CommandError as exc:
            raise LookupError(exc.message) from None

    return read


def _initial_report(session: Session, case_id: str) -> str | None:
    return session.scalars(
        select(EvidenceRecord.id).where(
            EvidenceRecord.case_id == case_id, EvidenceRecord.kind == "initial_report"
        )
    ).first()


def _run_specialist(
    session: Session,
    payload: dict[str, Any],
    touch: Touch,
    build: Callable[
        [Session, str, str], tuple[Any, BaseModel, Callable[[str, str], tuple[Any, int]]]
    ],
    store: Callable[[sessionmaker[Session], str, str, BaseModel], None],
    step_key: str,
) -> None:
    run_id, case_id = str(payload["run_id"]), str(payload["case_id"])
    run = session.get(WorkflowRun, run_id)
    if run is None or run.status != "running":
        session.rollback()
        return
    mode = ExecutionMode(str(payload.get("mode") or run.mode))
    spec, inputs, read = build(session, case_id, run_id)
    session.rollback()
    factory = _factory(session)

    def apply(output: BaseModel) -> None:
        store(factory, case_id, run_id, output)

    outcome = SpecialistRunner(_inv().client_for, read, _inv()._clock()).run_step(
        session, run_id, step_key, spec, inputs, mode, apply, touch
    )
    if outcome.status != StepStatus.SUCCEEDED.value:
        _inv()._fail_run(factory, run_id, case_id)  # explicit; recovery is retry_follow_up_draft


def _build_follow_up(
    session: Session, case_id: str, run_id: str
) -> tuple[Any, BaseModel, Callable[[str, str], tuple[Any, int]]]:
    findings, missing = _unresolved(session, case_id)
    items = {(lk.record_id, lk.field) for f in findings for lk in f.links}
    whole = set(missing)
    allowed = frozenset({r for r, _ in items} | whole)
    inputs = dom.FollowUpInput(
        case_id=case_id,
        open_findings=findings,
        missing_records=missing,
        initial_report_id=_initial_report(session, case_id),
    )
    read = _evidence_reader(session, case_id, lambda r, f: (r, f) in items or r in whole)
    return dom.follow_up_spec(allowed), inputs, read


def _store_follow_up(
    factory: sessionmaker[Session], case_id: str, run_id: str, out: BaseModel
) -> None:
    assert isinstance(out, dom.FollowUpOutput)
    by_ref: dict[tuple[str, str], str] = {}
    with factory() as s:
        for f in _unresolved(s, case_id)[0]:
            for lk in f.links:
                by_ref.setdefault((lk.record_id, lk.field), f.finding_id)
    questions = [
        {
            **q.model_dump(mode="json"),
            "finding_id": q.finding_id or by_ref.get((q.resolves.record_id, q.resolves.field)),
        }
        for q in out.questions
    ]
    _inv()._execute_retrying(
        factory,
        case_id,
        "store_communication_draft",
        f"store-draft:{case_id}:{run_id}",
        {"run_id": run_id, "subject": out.subject, "questions": questions},
        _inv().specialist_actor(dom.FOLLOW_UP),
    )


@register(FU_JOB)
def run_follow_up(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    _run_specialist(session, payload, touch, _build_follow_up, _store_follow_up, dom.FOLLOW_UP)


def _build_review(
    session: Session, case_id: str, run_id: str
) -> tuple[Any, BaseModel, Callable[[str, str], tuple[Any, int]]]:
    row = latest_communication(session, case_id)
    assert row is not None
    rsp = session.scalars(
        select(CommunicationResponse).where(CommunicationResponse.communication_id == row.id)
    ).one()
    rep = _initial_report(session, case_id) or "none"
    texts = {(rsp.id, "text"): rsp.text, (row.id, "questions"): "\n".join(row.questions)}
    evidence = _evidence_reader(session, case_id, lambda r, f: r == rep and f == "statement")

    def read(record_id: str, field: str) -> tuple[Any, int]:
        if (record_id, field) in texts:
            return texts[(record_id, field)], 1
        return evidence(record_id, field)

    inputs = dom.ResponseReviewInput(
        case_id=case_id, request_id=row.id, response_id=rsp.id, initial_report_id=rep
    )
    return dom.response_review_spec(frozenset({rsp.id, row.id, rep})), inputs, read


def _store_review(
    factory: sessionmaker[Session], case_id: str, run_id: str, out: BaseModel
) -> None:
    assert isinstance(out, dom.ResponseReviewOutput)
    response_id = run_id.removeprefix(RR_PREFIX)
    _inv()._execute_retrying(
        factory,
        case_id,
        "store_review_recommendation",
        f"recommend:{case_id}:{response_id}",
        {
            "response_id": response_id,
            "run_id": run_id,
            "classification": out.classification,
            "citations": [c.model_dump(mode="json") for c in out.citations],
        },
        _inv().specialist_actor(dom.RESPONSE_REVIEWER),
    )


@register(RR_JOB)
def run_response_review(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    _run_specialist(session, payload, touch, _build_review, _store_review, dom.RESPONSE_REVIEWER)


def _on_job_failed(session: Session, payload: dict[str, Any], error: str) -> None:
    """Out of attempts: the run's running step fails explicitly, as for the investigation."""
    _inv().on_job_failed(session, payload, error)


FAILURE_HOOKS[FU_JOB] = _on_job_failed
FAILURE_HOOKS[RR_JOB] = _on_job_failed


def dump_requests(session: Session, case_id: str, root: Path) -> list[Path]:
    """Request files for recording on a networked machine: evals/requests/{specialist}/v1/."""
    builds: list[tuple[str, Any]] = [(dom.FOLLOW_UP, _build_follow_up)]
    if latest_communication(session, case_id) is not None:
        builds.append((dom.RESPONSE_REVIEWER, _build_review))
    out = []
    for name, build in builds:
        spec, inputs, _read = build(session, case_id, "dump")
        path = root / name / dom.PROMPT_VERSION / f"{case_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "messages": spec.build_messages(inputs),
            "response_schema": spec.output_schema.model_json_schema(),
            "tools": [PROBE_TOOL],
        }
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        out.append(path)
    return out


@register(WATCH_JOB)
def deadline_watcher_job(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    run_deadline_watcher(session, datetime.fromisoformat(str(payload["now"])))


class WatcherIn(BaseModel):
    advance_hours: int = 0


class WatcherOut(BaseModel):
    job_id: int
    marked_overdue: list[str]  # case ids marked overdue by this watcher run


def run_deadline_watcher(session: Session, now: datetime) -> list[str]:
    """Marks every sent request past its deadline overdue via mark_deadline_missed (once)."""
    due = session.scalars(
        select(Communication).where(
            Communication.status.in_(("sent", "reminded")), Communication.due_at <= now
        )
    ).all()
    targets = [(r.case_id, r.id) for r in due]
    marked: list[str] = []
    for case_id, rid in targets:
        case = session.get(Case, case_id)
        assert case is not None
        version = case.case_version
        session.rollback()
        try:
            gateway.execute_command(
                session,
                now=now,
                case_id=case_id,
                command="mark_deadline_missed",
                key=f"deadline:{case_id}:{rid}",
                expected_version=version,
                payload={},
                actor=WATCHER,
                request_id=uuid.uuid4().hex,
            )
            marked.append(rid)
        except CommandError:
            session.rollback()
    return marked


@demo_router.post("/run-deadline-watcher")
def demo_deadline_watcher(body: WatcherIn, request: Request, session: DbSession) -> WatcherOut:
    clock: Clock = request.app.state.clock
    now = clock.now() + timedelta(hours=body.advance_hours)
    before = session.scalar(select(func.max(AuditEvent.id))) or 0
    job_id = enqueue(session, WATCH_JOB, {"now": now.isoformat()}, now=now)
    session.commit()
    handler = {WATCH_JOB: deadline_watcher_job}
    while run_once(session, worker_id="demo-deadline", now=now, handlers=handler) is not None:
        pass
    session.rollback()
    marked = session.scalars(
        select(AuditEvent.case_id).where(
            AuditEvent.type == "communication.overdue", AuditEvent.id > before
        )
    ).all()
    return WatcherOut(job_id=job_id, marked_overdue=sorted({str(m) for m in marked}))


plugins.register_router(router)
plugins.register_router(demo_router, synthetic_only=True)
