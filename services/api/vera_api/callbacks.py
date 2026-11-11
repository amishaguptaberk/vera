"""Verification callback (VER-007): effects, fact provider, telephony adapter, routes.

The call target is always read from the evidence register (PRF-4418.phone), never from a
payload. The structured result is written only by the service principal (record_callback),
stored apart from the transcript, and mirrored into a `callback` evidence record so the Policy
Controller reads it.
"""

import json
import re
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker
from vera_domain.adapters import AdapterResult
from vera_domain.callbacks import (
    AGENT,
    AGENT_PROMPT_VERSION,
    LIMIT_REASON,
    MAX_ATTEMPTS,
    NOTE_STEPS,
    OUTCOMES,
    START_STEPS,
    TARGET_FIELD,
    TARGET_RECORD,
    WORKING_STEPS,
    AgentInput,
    AgentOutput,
    CallbackNotePayload,
    RecordCallbackPayload,
    RetryAgentPayload,
    StartCallbackPayload,
    StructuredResult,
    build_agent_spec,
    reduce_note,
    reduce_record,
    reduce_retry,
    reduce_start,
)
from vera_domain.commands import CommandSpec
from vera_domain.enums import CaseState, CaseStep, EventType, Role, StateKind, register_event_types
from vera_domain.errors import CommandError
from vera_domain.evidence import RecordClaimPayload, content_hash
from vera_domain.labels import register_event_summaries, register_labels
from vera_domain.specialists import ExecutionMode, StepStatus

from vera_api import adapters, auth, evidence, gateway, plugins
from vera_api import policy as policy_service
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.config import Settings
from vera_api.gateway import EffectContext
from vera_api.intake import _emit
from vera_api.model_client import (
    PROBE_TOOL,
    LiveModelClient,
    ModelClient,
    RecordedModelClient,
    default_mode,
)
from vera_api.models import Case
from vera_api.models_callbacks import Callback, CallbackLine, CallbackNote
from vera_api.models_evidence import EvidenceRecord, EvidenceVersion
from vera_api.models_runs import WorkflowRun, WorkflowStep
from vera_api.runner import SpecialistRunner, create_run
from vera_api.worker import Touch, enqueue, register

SERVICE = Actor("svc-telephony", "Live Verification Agent", Role.SYSTEM, frozenset({Role.SYSTEM}))
STAFF = STAFF_ROLES

register_event_types(
    "callback.started",
    "callback.line_added",
    "callback.recorded",
    "callback.note_added",
    "callback.agent_failed",
    "callback.agent_retried",
)
register_event_summaries(
    {
        "callback.started": "Verification call approved",
        "callback.line_added": "Call transcript line",
        "callback.recorded": "Verification call result recorded",
        "callback.note_added": "Note added to the call",
        "callback.agent_failed": "Live Verification Agent failed",
        "callback.agent_retried": "Live Verification Agent retried",
    }
)

# Prototype PHASE table (Main.dc.html): verify/callfail "Evidence conflict"; working "In progress".
# Blockers for verify/callfail already exist in labels.BLOCKER_BY_STEP with the BLK texts.
register_labels(
    {
        (CaseState.CALLBACK_PENDING, CaseStep.VERIFY): (
            "Evidence conflict",
            StateKind.BLOCKED,
            "Approve the questions and start the verification call",
        ),
        (CaseState.CALLBACK_PENDING, CaseStep.WORKING): (
            "In progress",
            StateKind.WORKING,
            "The Live Verification Agent is running the approved call",
        ),
        (CaseState.CALLBACK_PENDING, CaseStep.CALLFAIL): (
            "Evidence conflict",
            StateKind.BLOCKED,
            "Retry the call once, send a targeted follow-up, or hold",
        ),
    }
)

# ---- simulated telephony adapter (synthetic) -----------------------------------------------

# The cardholder side of the simulated call, per selectable outcome (synthetic).
_SCRIPTS: dict[str, list[tuple[str, str]]] = {
    "confirmed": [  # the cardholder is reached and answers: she did not authorize it
        ("contact", "Hello, this is Priya."),
        (
            "contact",
            "No. I did not place the Northstar Equipment order; a colleague used my card"
            " without my approval, so I did not authorize this charge.",
        ),
    ],
    "contradicted": [
        ("contact", "Hello, this is Priya."),
        ("contact", "No, I did not place that order and I do not authorize it."),
    ],
    "voicemail": [("system", "[voicemail greeting; no live answer]")],
    "no_answer": [("system", "[no answer after 30 seconds]")],
    "incomplete": [("contact", "Hello? ..."), ("system", "[call dropped]")],
}


def _investigation() -> ModuleType:
    """vera_api.investigation, imported on use: it imports vera_api.evidence, which loads the
    gateway and with it this feature, so a top-level import is circular."""
    from vera_api import investigation

    return investigation


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
    _, version = evidence.read_evidence_field(session, case.id, TARGET_RECORD, TARGET_FIELD)
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
    try:
        mode = default_mode()
    except (RuntimeError, ValueError) as exc:
        raise CommandError("execution_mode_unset", 503, str(exc)) from None
    run_id = create_run(session, case_id=case.id, mode=mode, now=now, commit=False)
    from vera_api import voice  # feature module loaded after this one

    if voice.start_provider_call(session, case, row, run_id, p.consent_recorded, now):
        # A real voice provider places the call; its signed webhook enqueues the agent step.
        return {"callback_id": row.id, "attempt": attempt, "run_id": run_id, "job_id": None}
    job_id = enqueue(
        session, JOB_KIND, {"case_id": case.id, "callback_id": row.id, "run_id": run_id}, now=now
    )
    return {"callback_id": row.id, "attempt": attempt, "run_id": run_id, "job_id": job_id}


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
    evidence.recompute_snapshot(session, case)
    if policy_service.has_evaluation(session, case.id):
        policy_service.reevaluate_on_evidence_change(session, case.id, now)


def _lines(session: Session, callback_id: str) -> list[CallbackLine]:
    return list(
        session.scalars(
            select(CallbackLine)
            .where(CallbackLine.callback_id == callback_id)
            .order_by(CallbackLine.seq)
        )
    )


def _record_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _own(session, case.id, p.callback_id)
    if row.status != "in_progress":
        raise CommandError("callback_recorded", 409, f"{row.id} already has a result.")
    lines = _lines(session, row.id)
    if not lines:
        reason = "Transcript unavailable"
        raise CommandError("transcript_unavailable", 422, reason, blocked_reason=reason)
    asked = {q["id"] for q in row.questions}
    for a in p.answers:
        if a.question_id not in asked:
            raise CommandError("schema_invalid", 422, f"{a.question_id} was not approved.")
        if not 1 <= a.line_seq <= len(lines):
            raise CommandError("schema_invalid", 422, f"{a.question_id}: line not in transcript.")
    result = StructuredResult(
        result="confirmed" if p.outcome == "confirmed" else "failed",
        outcome=p.outcome,
        authorization_answer=p.authorization_answer,
        answers=p.answers,
    )
    row.status = p.outcome
    row.result = {**result.model_dump(), "run_id": p.run_id}
    row.updated_at = now
    session.flush()
    if p.outcome == "confirmed" or p.authorization_answer:
        _write_evidence(session, case, row, now)
    return {"result": row.result}


def _record_after(
    session: Session,
    case: Case,
    actor: Actor,
    p: Any,
    now: datetime,
    ctx: EffectContext,
    out: gateway.Outcome,
) -> None:
    """A confirmed call is the structured verification the open conflicts were waiting on:
    each open conflict finding is resolved by this callback (resolve_finding)."""
    if p.outcome == "confirmed":
        evidence.resolve_open_conflicts(session, case, p.callback_id, SERVICE, now)


def _note_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _own(session, case.id, p.callback_id)
    note = CallbackNote(callback_id=row.id, author=actor.user_id, text=p.text, created_at=now)
    session.add(note)
    session.flush()
    claim_id = None
    if PHONE.search(p.text) and ctx.first_report is not None:
        # A number typed into a note is a claim, never a call target (target = PRF-4418.phone).
        claim_id = f"CLM-{row.id}-N{note.id}"
        claim = RecordClaimPayload(
            claim_id=claim_id,
            report_id=ctx.first_report.id,
            statement=f"Phone number stated in a call note: {p.text}"[:500],
        )
        evidence.run_effect(
            session,
            case,
            "record_claim",
            claim,
            now=now,
            actor_id=actor.user_id,
            actor_role=actor.active_role,
        )
        _emit(
            session,
            EventType.CLAIM_RECORDED,
            case,
            actor.user_id,
            actor.active_role,
            now,
            [claim_id],
            f"Claim {claim_id} recorded (phone number in a call note)",
        )
    return {"note_id": note.id, "claim_id": claim_id}


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
    after_effects={RECORD.name: _record_after},
    key_context=_keys,
)
gateway.register_fact_provider(_facts)
plugins.register_reset_tables(["callback_notes", "callback_transcript_lines", "callbacks"])


# ---- the call: telephony (cardholder side) then the Live Verification Agent -----------------

JOB_KIND = "live_verification"
PHONE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
# Test seams (never switched by product code), as in investigation.py.
LIVE_TRANSPORT: httpx.BaseTransport | None = None
RECORDINGS_ROOT: Path | None = None


def _client_for(mode: ExecutionMode, case_id: str) -> ModelClient:
    if mode is ExecutionMode.LIVE:
        return LiveModelClient(transport=LIVE_TRANSPORT, sleep=_investigation().LIVE_SLEEP)
    root = RECORDINGS_ROOT or _investigation().recordings_root()
    return RecordedModelClient(root, case_id=case_id)


def _place_call(session: Session, case: Case, row: Callback, now: datetime) -> None:
    """Dial the contact on file (PRF-4418.phone) once; store each line as it arrives."""
    if _lines(session, row.id):
        return
    number, _ = evidence.read_evidence_field(
        session, case.id, row.target_record_id, row.target_field
    )
    out = adapters.execute(
        session,
        case_id=case.id,
        adapter="telephony",
        operation="call",
        key=f"callback:{row.id}",
        request={
            "target": {"record_id": row.target_record_id, "field": row.target_field},
            "number": number,
            "questions": row.questions,
        },
        now=now,
    )
    if out.status != "succeeded":  # never act on uncertain; failed retries with the same key
        raise RuntimeError(f"telephony {out.status}")
    for i, line in enumerate(out.result["lines"], start=1):
        session.add(
            CallbackLine(
                callback_id=row.id,
                seq=i,
                speaker=line["speaker"],
                text=line["text"],
                created_at=now,
            )
        )
        _emit(
            session,
            "callback.line_added",
            case,
            SERVICE.user_id,
            Role.SYSTEM,
            now,
            [row.id],
            f"{line['speaker']}: {line['text']}"[:200],
            {"seq": i, "callback_id": row.id},
        )
    session.commit()


def _call_reader(session: Session, callback_id: str) -> Callable[[str, str], tuple[Any, int]]:
    """Fields scoped to one callback: 'question:{id}' (approved only) and 'line:{seq}'."""

    def read(record_id: str, field: str) -> tuple[Any, int]:
        row = session.get(Callback, record_id)
        if row is None or record_id != callback_id:
            raise LookupError(f"no callback {record_id}")
        kind, _, ref = field.partition(":")
        if kind == "question" and ref in {q["id"] for q in row.questions}:
            return ref, 1
        if kind == "line":
            for line in _lines(session, callback_id):
                if str(line.seq) == ref:
                    return line.text, 1
        raise LookupError(f"{record_id} has no '{field}'")

    return read


def agent_input(session: Session, case_id: str, row: Callback) -> AgentInput:
    return AgentInput(
        case_id=case_id,
        callback_id=row.id,
        question_fields=[f"question:{q['id']}" for q in row.questions],
        line_fields=[f"line:{x.seq}" for x in _lines(session, row.id)],
    )


@register(JOB_KIND)
def run_callback_job(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    case_id, callback_id = str(payload["case_id"]), str(payload["callback_id"])
    run_id = str(payload["run_id"])
    now = _investigation()._clock().now()
    row = session.get(Callback, callback_id)
    case = session.get(Case, case_id)
    run = session.get(WorkflowRun, run_id)
    if row is None or case is None or run is None or row.status != "in_progress":
        session.rollback()
        return
    mode = ExecutionMode(str(payload.get("mode") or run.mode))
    _place_call(session, case, row, now)
    row = session.get(Callback, callback_id)
    assert row is not None
    spec = build_agent_spec(callback_id)

    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    factory = sessionmaker(engine, expire_on_commit=False)

    def apply(output: BaseModel) -> None:
        out = AgentOutput.model_validate(output.model_dump())
        body = {
            "callback_id": callback_id,
            "run_id": run_id,
            "outcome": out.outcome,
            "authorization_answer": out.authorization_answer,
            "answers": [
                {"question_id": a.question_id, "answer": a.answer, "line_seq": a.line_seq}
                for a in out.answers
            ],
        }
        _investigation()._execute_retrying(
            factory,
            case_id,
            "record_callback",
            f"callback-result:{case_id}:{callback_id}",
            body,
            SERVICE,
        )

    runner = SpecialistRunner(
        _client_for, _call_reader(session, callback_id), _investigation()._clock()
    )
    outcome = runner.run_step(
        session, run_id, AGENT, spec, agent_input(session, case_id, row), mode, apply, touch
    )
    with factory() as s:
        r = s.get(WorkflowRun, run_id, with_for_update=True)
        assert r is not None
        # A failed agent step leaves the run `running` (the call is still in progress) so only
        # this module's retry_callback_agent recovers it; investigation recovery never sees it.
        r.status = "succeeded" if outcome.status == StepStatus.SUCCEEDED.value else "running"
        r.updated_at = _investigation()._clock().now()
        s.commit()
    if outcome.status != StepStatus.SUCCEEDED.value:
        with factory() as s:
            c = s.get(Case, case_id, with_for_update=True)
            assert c is not None
            _emit(
                s,
                "callback.agent_failed",
                c,
                SERVICE.user_id,
                Role.SYSTEM,
                _investigation()._clock().now(),
                [callback_id],
                f"Live Verification Agent failed: {outcome.failure_reason}. Retry or hold.",
                {"run_id": run_id, "reason": outcome.failure_reason},
            )
            s.commit()


def agent_step(session: Session, case_id: str) -> WorkflowStep | None:
    row = latest_callback(session, case_id)
    if row is None or row.status != "in_progress":
        return None
    return session.scalars(
        select(WorkflowStep)
        .join(WorkflowRun, WorkflowRun.id == WorkflowStep.run_id)
        .where(WorkflowRun.case_id == case_id, WorkflowStep.step_key == AGENT)
        .order_by(WorkflowRun.created_at.desc())
    ).first()


def _retry_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = latest_callback(session, case.id)
    step = agent_step(session, case.id)
    if row is None or step is None or step.status != StepStatus.FAILED.value:
        raise CommandError("invalid_step", 409, "The Live Verification Agent has not failed.")
    job_id = enqueue(
        session,
        JOB_KIND,
        {"case_id": case.id, "callback_id": row.id, "run_id": step.run_id, "mode": p.mode},
        now=now,
    )
    return {"callback_id": row.id, "run_id": step.run_id, "mode": p.mode, "job_id": job_id}


RETRY = CommandSpec(
    "retry_callback_agent",
    _A,
    RetryAgentPayload,
    WORKING_STEPS,
    "callback-retry:{case_id}:{case_version}",
    reduce_retry,
    ("callback.agent_retried",),
    "Retry Live Verification Agent",
    "secondary",
)
gateway.register_commands(__name__, human={RETRY.name: RETRY}, effects={RETRY.name: _retry_effect})


# ---- what the case view offers: the same preconditions the effects check -------------------------


def _limit_reached(session: Session, case: Case) -> CommandError | None:
    if len(_callbacks(session, case.id)) >= MAX_ATTEMPTS:
        return gateway.blocked("callback_limit", LIMIT_REASON)
    return None


def _no_call(session: Session, case: Case) -> CommandError | None:
    if latest_callback(session, case.id) is None:
        return gateway.blocked("callback_not_found", "No verification call on this case.")
    return None


def _note_defaults(session: Session, case: Case) -> dict[str, Any]:
    row = latest_callback(session, case.id)
    return {"callback_id": row.id} if row is not None else {}


def _failed_agent(session: Session, case: Case) -> WorkflowStep | None:
    step = agent_step(session, case.id)
    return step if step is not None and step.status == StepStatus.FAILED.value else None


def _agent_not_failed(session: Session, case: Case) -> CommandError | None:
    if _failed_agent(session, case) is None:
        return gateway.blocked("invalid_step", "The Live Verification Agent has not failed.")
    return None


def _retry_defaults(session: Session, case: Case) -> dict[str, Any]:
    step = _failed_agent(session, case)
    run = session.get(WorkflowRun, step.run_id) if step is not None else None
    return {"mode": run.mode} if run is not None else {}


gateway.register_actions(
    __name__,
    defaults={NOTE.name: _note_defaults, RETRY.name: _retry_defaults},
    guards={START.name: _limit_reached, NOTE.name: _no_call, RETRY.name: _agent_not_failed},
)


def dump_request(session: Session, case_id: str, root: Path) -> Path:
    """Request file for a real capture on a networked machine (latest callback)."""
    row = latest_callback(session, case_id)
    assert row is not None
    spec = build_agent_spec(row.id)
    path = root / AGENT / AGENT_PROMPT_VERSION / f"{case_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "messages": spec.build_messages(agent_input(session, case_id, row)),
        "response_schema": AgentOutput.model_json_schema(),
        "tools": [PROBE_TOOL],
    }
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return path


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
    voice: dict[str, Any] | None = None


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
        voice=_voice_view(session, row.id),
    )


def _voice_view(session: Session, callback_id: str) -> dict[str, Any] | None:
    from vera_api import voice

    return voice.voice_view(session, callback_id)


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


plugins.register_router(router)
plugins.register_router(demo_router, synthetic_only=True)
