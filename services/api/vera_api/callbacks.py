"""Verification callback (VER-007): effects, fact provider, telephony adapter, routes.

The call target is always read from the evidence register (PRF-4418.phone), never from a
payload. The structured result is written only by the service principal (record_callback),
stored apart from the transcript, and mirrored into a `callback` evidence record so the Policy
Controller reads it.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.callbacks import (
    LIMIT_REASON,
    MAX_ATTEMPTS,
    NOTE_STEPS,
    OUTCOMES,
    START_STEPS,
    TARGET_FIELD,
    TARGET_RECORD,
    WORKING_STEPS,
    CallbackNotePayload,
    RecordCallbackPayload,
    StartCallbackPayload,
    StructuredResult,
    reduce_note,
    reduce_record,
    reduce_start,
)
from vera_domain.adapters import AdapterResult
from vera_domain.clock import Clock
from vera_domain.commands import CommandSpec
from vera_domain.enums import Role, register_event_types
from vera_domain.errors import CommandError
from vera_domain.evidence import content_hash
from vera_domain.labels import register_event_summaries

from vera_api import adapters, auth, gateway, plugins
from vera_api import policy as policy_service
from vera_api.auth import Actor
from vera_api.config import Settings
from vera_api.auth import STAFF_ROLES
from vera_api.evidence import read_evidence_field, recompute_snapshot
from vera_api.gateway import EffectContext
from vera_api.intake import _emit
from vera_api.models import Case
from vera_api.models_callbacks import Callback, CallbackLine, CallbackNote
from vera_api.models_evidence import EvidenceRecord, EvidenceVersion

SERVICE = Actor("svc-telephony", "Live Verification Agent", Role.SYSTEM, frozenset({Role.SYSTEM}))
STAFF = STAFF_ROLES

register_event_types(
    "callback.started", "callback.line_added", "callback.recorded", "callback.note_added"
)
register_event_summaries(
    {
        "callback.started": "Verification call approved",
        "callback.line_added": "Call transcript line",
        "callback.recorded": "Verification call result recorded",
        "callback.note_added": "Note added to the call",
    }
)

# ---- simulated telephony adapter (synthetic) -----------------------------------------------

_SCRIPTS: dict[str, list[tuple[str, str]]] = {
    "confirmed": [("contact", "Hello, this is Priya."), ("contact", "Yes, I recognize it.")],
    "contradicted": [("contact", "Hello, this is Priya."), ("contact", "No, I did not.")],
    "voicemail": [("contact", "[voicemail greeting]")],
    "no_answer": [],
    "incomplete": [("contact", "Hello? ... [call dropped]")],
}


class SimulatedTelephony:
    """Synthetic telephony: deterministic `confirmed` unless the demo route selects another."""

    def __init__(self) -> None:
        self.next_outcome = "confirmed"

    def call(self, operation: str, request: dict[str, Any]) -> AdapterResult:
        outcome = self.next_outcome
        lines = [{"speaker": "agent", "text": f"Calling {request['target']['record_id']}."}]
        for q in request["questions"]:
            lines.append({"speaker": "agent", "text": q["text"]})
        lines += [{"speaker": s, "text": t} for s, t in _SCRIPTS[outcome]]
        return AdapterResult(
            status="succeeded",
            result={"outcome": outcome, "lines": lines, "synthetic": True},
        )


TELEPHONY = SimulatedTelephony()
adapters.register_adapter("telephony", TELEPHONY)

# ---- reads -----------------------------------------------------------------------------------


def _callbacks(session: Session, case_id: str) -> list[Callback]:
    return list(
        session.scalars(
            select(Callback).where(Callback.case_id == case_id).order_by(Callback.attempt)
        )
    )


def latest_callback(session: Session, case_id: str) -> Callback | None:
    rows = _callbacks(session, case_id)
    return rows[-1] if rows else None


def _facts(session: Session, case: Case) -> dict[str, Any]:
    rows = _callbacks(session, case.id)
    return {
        "callback_status": rows[-1].status if rows else "none",
        "callback_attempts": len(rows),
    }


# ---- effects ---------------------------------------------------------------------------------


def _start_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    attempts = len(_callbacks(session, case.id))
    if attempts >= MAX_ATTEMPTS:
        raise CommandError("callback_limit", 409, LIMIT_REASON, blocked_reason=LIMIT_REASON)
    _, version = read_evidence_field(session, case.id, TARGET_RECORD, TARGET_FIELD)
    attempt = attempts + 1
    row = Callback(
        id=f"CALL-{case.id.split('-')[-1]}-{attempt}",
        case_id=case.id,
        attempt=attempt,
        status="in_progress",
        target_record_id=TARGET_RECORD,
        target_field=TARGET_FIELD,
        target_version=version,
        questions=[q.model_dump() for q in p.questions],
        approved_by=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return {"callback_id": row.id, "attempt": attempt}


def _own(session: Session, case_id: str, callback_id: str) -> Callback:
    row = session.get(Callback, callback_id)
    if row is None or row.case_id != case_id:
        raise CommandError("callback_not_found", 404, f"No callback '{callback_id}'.")
    return row


def _write_evidence(session: Session, case: Case, row: Callback, now: datetime) -> None:
    assert row.result is not None
    fields = {
        "result": row.result["result"],
        "authorization_answer": row.result["authorization_answer"],
        "callback_id": row.id,
    }
    rid = f"EV-{row.id}"
    session.add(EvidenceRecord(id=rid, case_id=case.id, kind="callback", created_at=now))
    session.flush()
    session.add(
        EvidenceVersion(
            record_id=rid,
            version=1,
            material_version=1,
            fields=fields,
            content_hash=content_hash("callback", fields),
            source=f"callback {row.id}",
            created_by=SERVICE.user_id,
            created_at=now,
        )
    )
    session.flush()
    recompute_snapshot(session, case)
    if policy_service.has_evaluation(session, case.id):
        policy_service.reevaluate_on_evidence_change(session, case.id, now)


def _record_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _own(session, case.id, p.callback_id)
    if row.status != "in_progress":
        raise CommandError("callback_recorded", 409, f"{row.id} already has a result.")
    if not p.transcript:
        reason = "Transcript unavailable"
        raise CommandError("transcript_unavailable", 422, reason, blocked_reason=reason)
    asked = {q["id"] for q in row.questions}
    for a in p.answers:
        if a.question_id not in asked:
            raise CommandError("schema_invalid", 422, f"{a.question_id} was not approved.")
        if not 1 <= a.line_seq <= len(p.transcript):
            raise CommandError("schema_invalid", 422, f"{a.question_id}: line not in transcript.")
    for i, line in enumerate(p.transcript, start=1):
        session.add(
            CallbackLine(
                callback_id=row.id, seq=i, speaker=line.speaker, text=line.text, created_at=now
            )
        )
        _emit(
            session,
            "callback.line_added",
            case,
            actor.user_id,
            actor.active_role,
            now,
            [row.id],
            f"{line.speaker}: {line.text}"[:200],
            {"seq": i},
        )
    result = StructuredResult(
        result="confirmed" if p.outcome == "confirmed" else "failed",
        outcome=p.outcome,
        authorization_answer=p.authorization_answer,
        answers=p.answers,
    )
    row.status = p.outcome
    row.result = result.model_dump()
    row.updated_at = now
    session.flush()
    if p.outcome == "confirmed" or p.authorization_answer:
        _write_evidence(session, case, row, now)
    return {"result": row.result}


def _note_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _own(session, case.id, p.callback_id)
    note = CallbackNote(callback_id=row.id, author=actor.user_id, text=p.text, created_at=now)
    session.add(note)
    session.flush()
    return {"note_id": note.id}


_A = frozenset({Role.ANALYST})
START = CommandSpec(
    "start_callback",
    _A,
    StartCallbackPayload,
    START_STEPS,
    "callback:{case_id}:{case_version}",
    reduce_start,
    ("callback.started",),
    "Start verification call",
    "primary",
    adapter="telephony",
)
RECORD = CommandSpec(
    "record_callback",
    frozenset({Role.SYSTEM}),
    RecordCallbackPayload,
    WORKING_STEPS,
    "callback-result:{case_id}:{callback_id}",
    reduce_record,
    ("callback.recorded",),
    "Record call result",
    "secondary",
)
NOTE = CommandSpec(
    "add_callback_note",
    _A,
    CallbackNotePayload,
    NOTE_STEPS,
    "callback-note:{case_id}:{case_version}",
    reduce_note,
    ("callback.note_added",),
    "Add call note",
    "ghost",
)


def _keys(session: Session, case: Case, body: dict[str, Any]) -> dict[str, object]:
    return {"callback_id": body.get("callback_id", "")}


gateway.register_commands(
    __name__,
    human={START.name: START, NOTE.name: NOTE},
    service={RECORD.name: RECORD},
    effects={START.name: _start_effect, RECORD.name: _record_effect, NOTE.name: _note_effect},
    key_context=_keys,
)
gateway.register_fact_provider(_facts)
plugins.register_reset_tables(["callback_notes", "callback_transcript_lines", "callbacks"])


# ---- the call (Live Verification Agent drives the scripted call; service principal records) --


def run_call(session: Session, case_id: str, callback_id: str, now: datetime) -> dict[str, Any]:
    """Dial the contact on file through the telephony adapter and record the structured result."""
    row = _own(session, case_id, callback_id)
    target, _ = read_evidence_field(session, case_id, row.target_record_id, row.target_field)
    out = adapters.execute(
        session,
        case_id=case_id,
        adapter="telephony",
        operation="call",
        key=f"callback:{callback_id}",
        request={
            "target": {"record_id": row.target_record_id, "field": row.target_field},
            "number": target,
            "questions": row.questions,
        },
        now=now,
    )
    if out.status != "succeeded":
        raise CommandError("adapter_failed", 502, f"Telephony {out.status}: call not recorded.")
    lines = out.result["lines"]
    outcome = out.result["outcome"]
    answers = []
    if outcome == "confirmed":
        answers = [
            {"question_id": q["id"], "answer": "yes", "line_seq": len(lines)}
            for q in row.questions
        ]
    payload = {
        "callback_id": callback_id,
        "outcome": outcome,
        "transcript": lines,
        "authorization_answer": "authorized" if outcome == "confirmed" else None,
        "answers": answers,
    }
    case = session.get(Case, case_id)
    assert case is not None
    session.refresh(case)
    version = case.case_version
    session.commit()
    res = gateway.execute_command(
        session,
        now=now,
        case_id=case_id,
        command="record_callback",
        key=f"callback-result:{case_id}:{callback_id}",
        expected_version=version,
        payload=payload,
        actor=SERVICE,
        request_id=f"call-{callback_id}",
    )
    return res.result


# ---- routes ----------------------------------------------------------------------------------


class LineView(BaseModel):
    seq: int
    speaker: str
    text: str


class NoteView(BaseModel):
    author: str
    text: str
    created_at: datetime


class CallbackView(BaseModel):
    id: str
    attempt: int
    status: str
    target_record_id: str
    target_field: str
    target_version: int
    questions: list[dict[str, Any]]
    result: dict[str, Any] | None
    approved_by: str
    created_at: datetime


class CallbackDetail(CallbackView):
    transcript: list[LineView]
    notes: list[NoteView]


def _view(row: Callback) -> CallbackView:
    return CallbackView.model_validate(row, from_attributes=True)


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def _actor(request: Request, session: Annotated[Session, Depends(_session)]) -> Actor:
    settings: Settings = request.app.state.settings
    actor = auth.load_actor(
        session, settings.secret(), request.cookies.get(auth.COOKIE), settings.synthetic
    )
    if actor.active_role not in STAFF or actor.active_role not in actor.roles:
        raise CommandError("role_forbidden", 403, "This role cannot read callbacks.")
    return actor


DbSession = Annotated[Session, Depends(_session)]
StaffDep = Annotated[Actor, Depends(_actor)]
router = APIRouter(prefix="/api")
demo_router = APIRouter(prefix="/api/demo")


@router.get("/cases/{case_id}/callbacks")
def list_callbacks(case_id: str, session: DbSession, actor: StaffDep) -> list[CallbackView]:
    return [_view(r) for r in _callbacks(session, case_id)]


@router.get("/cases/{case_id}/callbacks/{callback_id}")
def get_callback(
    case_id: str, callback_id: str, session: DbSession, actor: StaffDep
) -> CallbackDetail:
    row = _own(session, case_id, callback_id)
    lines = session.scalars(
        select(CallbackLine).where(CallbackLine.callback_id == row.id).order_by(CallbackLine.seq)
    )
    notes = session.scalars(
        select(CallbackNote).where(CallbackNote.callback_id == row.id).order_by(CallbackNote.id)
    )
    return CallbackDetail(
        **_view(row).model_dump(),
        transcript=[LineView(seq=x.seq, speaker=x.speaker, text=x.text) for x in lines],
        notes=[NoteView(author=n.author, text=n.text, created_at=n.created_at) for n in notes],
    )


class OutcomeIn(BaseModel):
    outcome: str = "confirmed"


class OutcomeOut(BaseModel):
    outcome: str


@demo_router.post("/callback-outcome")
def set_callback_outcome(body: OutcomeIn) -> OutcomeOut:
    if body.outcome not in OUTCOMES:
        raise CommandError("schema_invalid", 422, f"outcome must be one of {list(OUTCOMES)}.")
    TELEPHONY.next_outcome = body.outcome
    return OutcomeOut(outcome=body.outcome)


class RunCallIn(BaseModel):
    case_id: str
    callback_id: str


@demo_router.post("/callback-run")
def run_callback(body: RunCallIn, request: Request, session: DbSession) -> dict[str, Any]:
    clock: Clock = request.app.state.clock
    return run_call(session, body.case_id, body.callback_id, clock.now())


plugins.register_router(router)
plugins.register_router(demo_router, synthetic_only=True)
