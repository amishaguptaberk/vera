"""Cardholder follow-up (VER-005): effects, fact provider, messaging adapter, routes, watcher."""

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vera_domain import comms as dom
from vera_domain.adapters import AdapterResult
from vera_domain.clock import Clock
from vera_domain.enums import CaseState, CaseStep, Role, StateKind
from vera_domain.errors import CommandError
from vera_domain.evidence import content_hash
from vera_domain.labels import register_event_summaries, register_labels

from vera_api import adapters, auth, gateway, plugins
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.config import Settings
from vera_api.evidence import recompute_snapshot
from vera_api.gateway import EffectContext
from vera_api.models import CardTransaction, Case, User
from vera_api.models_comms import Communication, CommunicationDraft, CommunicationResponse
from vera_api.models_evidence import Attachment, EvidenceRecord, EvidenceVersion, Finding

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
        return AdapterResult(
            status="succeeded",
            result={
                "delivery_id": f"DLV-{request['communication_id']}-{operation}",
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

_QUESTIONS = [
    "Please upload the receipt or invoice for the Northstar Equipment charge.",
    "Did you receive the items on this order?",
]


def _open_questions(session: Session, case_id: str) -> list[str]:
    """Only unresolved questions: missing records and open findings in the evidence register."""
    missing = session.scalars(
        select(EvidenceRecord.kind).where(
            EvidenceRecord.case_id == case_id, EvidenceRecord.status == "missing"
        )
    ).all()
    qs = [f"Please provide the {k.replace('_', ' ')} for this charge." for k in missing]
    return qs or _QUESTIONS


def _draft(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    if latest_communication(session, case.id) is not None:
        raise CommandError("followup_exists", 409, "This case already has a cardholder request.")
    n = session.scalar(select(func.count()).select_from(Communication)) or 0
    questions = _open_questions(session, case.id)
    subject = f"Question about your charge on case {case.id}"
    body = "Hello,\n\n" + "\n".join(f"- {q}" for q in questions) + "\n\nThank you."
    row = Communication(
        id=f"MSG-{FIRST_MESSAGE + n}",
        case_id=case.id,
        status="drafted",
        subject=subject,
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
            subject=subject,
            body=body,
            created_by=actor.user_id,
            created_at=now,
        )
    )
    session.flush()
    return {"request_id": row.id, "questions": questions}


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
        recompute_snapshot(session, case)
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
    return {"request_id": row.id, "response_id": rsp.id, "evidence_record_id": record_id}


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
    return {"request_id": row.id if row else "none"}


gateway.register_commands(
    __name__,
    human=dom.HUMAN,
    service=dom.SERVICE,
    effects={
        "draft_follow_up": _draft,
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


class WatcherIn(BaseModel):
    advance_hours: int = 0


class WatcherOut(BaseModel):
    marked_overdue: list[str]


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
    return WatcherOut(marked_overdue=run_deadline_watcher(session, now))


plugins.register_router(router)
plugins.register_router(demo_router, synthetic_only=True)
