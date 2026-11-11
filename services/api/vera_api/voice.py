"""Voice verification integration boundary: providers, webhook route, attempt bookkeeping.

The provider (ElevenLabs Conversational AI over Twilio/SIP) runs the conversation. Vera only
accepts its output through a signed webhook; answers are extracted for approved questions only,
grounded in transcript lines, and the case changes state solely through `record_callback`
(service principal, command gateway) after the Live Verification Agent validates them.
"""

import hashlib
import hmac
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, TypedDict

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from vera_domain.enums import Role
from vera_domain.errors import CommandError
from vera_domain.voice import (
    FINAL_STATUSES,
    CallStarted,
    CallStatus,
    Question,
    StartVerificationCall,
    VoiceError,
    VoiceEvent,
    dynamic_variables,
    extract_answers,
    mask_number,
    parse_elevenlabs,
    to_e164,
)

from vera_api import callbacks, plugins
from vera_api.graph import postgres_checkpointer
from vera_api.models import Case
from vera_api.models_callbacks import (
    Callback,
    CallbackLine,
    VoiceCall,
    VoiceTranscriptVersion,
    VoiceWebhookEvent,
)
from vera_api.worker import Touch, enqueue, register

log = logging.getLogger(__name__)


def _now() -> datetime:
    from vera_api import investigation  # lazy: this module loads during gateway import

    return investigation._clock().now()


def _emit(*args: Any) -> None:
    from vera_api.intake import _emit as emit

    emit(*args)


API_BASE = "https://api.elevenlabs.io"
OUTBOUND_PATHS = {
    "twilio": "/v1/convai/twilio/outbound-call",
    "sip": "/v1/convai/sip-trunk/outbound-call",
}
REQUIRED_ENV = (
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_AGENT_ID",
    "ELEVENLABS_AGENT_PHONE_NUMBER_ID",
    "ELEVENLABS_WEBHOOK_SECRET",
)
TIMEOUT_JOB = "voice_call_timeout"
CALL_TIMEOUT = timedelta(minutes=10)  # demo clock
SIGNATURE_TOLERANCE_SECS = 30 * 60  # the provider SDK's tolerance
PURPOSE = "Confirm whether the cardholder placed and authorizes the disputed order"


class VoiceConfigError(RuntimeError):
    """Typed configuration failure (names the missing settings, never their values)."""

    def __init__(self, reason: str, missing: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.missing = missing


# ---- signature (ElevenLabs-Signature: "t=<unix>,v0=<hex hmac-sha256(secret, f'{t}.{body}')>")


def sign(secret: str, body: bytes, timestamp: int) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v0={mac.hexdigest()}"


def verify_signature(secret: str, body: bytes, header: str, now: float) -> None:
    """Same scheme as the provider SDK's construct_event, with a constant-time compare."""
    if not header:
        raise VoiceError("signature_missing", "Missing signature header.")
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, given = parts.get("t", ""), parts.get("v0", "")
    if not ts.isdigit() or not given:
        raise VoiceError("signature_invalid", "No signature with scheme v0.")
    if abs(now - int(ts)) > SIGNATURE_TOLERANCE_SECS:
        raise VoiceError("signature_expired", "Signature timestamp outside tolerance.")
    expected = sign(secret, body, int(ts)).split("v0=", 1)[1]
    if not hmac.compare_digest(expected, given):
        raise VoiceError("signature_invalid", "Signature does not match.")


# ---- providers


@dataclass(frozen=True)
class ElevenLabsConfig:
    api_key: str
    agent_id: str
    agent_phone_number_id: str
    webhook_secret: str
    telephony: str = "twilio"

    @classmethod
    def from_env(cls) -> "ElevenLabsConfig":
        missing = tuple(n for n in REQUIRED_ENV if not os.environ.get(n))
        if missing:
            raise VoiceConfigError(
                f"VERA_VOICE_PROVIDER=elevenlabs requires {', '.join(missing)}", missing
            )
        telephony = os.environ.get("ELEVENLABS_TELEPHONY", "twilio")
        if telephony not in OUTBOUND_PATHS:
            raise VoiceConfigError("ELEVENLABS_TELEPHONY must be 'twilio' or 'sip'")
        env = os.environ
        return cls(
            env["ELEVENLABS_API_KEY"],
            env["ELEVENLABS_AGENT_ID"],
            env["ELEVENLABS_AGENT_PHONE_NUMBER_ID"],
            env["ELEVENLABS_WEBHOOK_SECRET"],
            telephony,
        )

    def __repr__(self) -> str:  # never print the key or secret
        return f"ElevenLabsConfig(agent_id={self.agent_id!r}, telephony={self.telephony!r})"


class ElevenLabsVoiceProvider:
    name = "elevenlabs"

    def __init__(
        self,
        config: ElevenLabsConfig,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        max_attempts: int = 3,
    ) -> None:
        self._cfg = config
        self._clock = clock
        self._sleep = sleep
        self._now = now or _now
        self._max = max_attempts
        self._http = httpx.Client(
            base_url=API_BASE,
            transport=transport,
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"xi-api-key": config.api_key},
        )

    def start_call(self, inp: StartVerificationCall) -> CallStarted:
        if not inp.consent_recorded:
            raise VoiceError("consent_missing", "Cardholder consent is not recorded.")
        body = {
            "agent_id": self._cfg.agent_id,
            "agent_phone_number_id": self._cfg.agent_phone_number_id,
            "to_number": inp.to_number_e164,
            "conversation_initiation_client_data": {"dynamic_variables": dynamic_variables(inp)},
            "call_recording_enabled": False,
        }
        path = OUTBOUND_PATHS[self._cfg.telephony]
        resp: httpx.Response | None = None
        for i in range(self._max):
            try:
                resp = self._http.post(path, json=body)
            except httpx.TimeoutException:
                # The call may have been placed: never re-dial on an uncertain outcome.
                raise VoiceError(
                    "provider_uncertain", "Provider timed out; call state unknown."
                ) from None
            except httpx.TransportError:
                resp = None  # connection never established: safe to retry
            else:
                if resp.status_code != 429 and resp.status_code < 500:
                    break
            if i + 1 < self._max:
                self._sleep(0.5 * 2**i)
        if resp is None or resp.status_code >= 400:
            code = resp.status_code if resp is not None else "unreachable"
            log.warning("voice provider start_call failed for %s: %s", inp.callback_id, code)
            raise VoiceError("provider_failed", f"Voice provider rejected the call ({code}).")
        doc = resp.json()
        conv = doc.get("conversation_id")
        if not doc.get("success") or not conv:
            raise VoiceError("provider_failed", "Voice provider did not start the call.")
        return CallStarted(self.name, str(conv), str(conv), self._now())

    def get_call_status(self, provider_call_id: str) -> CallStatus:
        resp = self._http.get(f"/v1/convai/conversations/{provider_call_id}")
        resp.raise_for_status()
        status = str(resp.json().get("status", ""))
        return {
            "initiated": CallStatus.QUEUED,
            "in-progress": CallStatus.IN_PROGRESS,
            "processing": CallStatus.IN_PROGRESS,
            "done": CallStatus.COMPLETED,
            "failed": CallStatus.FAILED,
        }.get(status, CallStatus.IN_PROGRESS)

    def handle_webhook(self, payload: bytes, signature: str) -> VoiceEvent:
        verify_signature(self._cfg.webhook_secret, payload, signature, self._clock())
        return parse_elevenlabs(payload)

    def end_call(self, provider_call_id: str) -> None:
        # Conversations end from the agent side; Vera stops tracking and ignores later results.
        return None


class SimulatedVoiceProvider:
    """Synthetic environment only. Produces signed ElevenLabs-shaped payloads so the SAME
    webhook verification, parsing, extraction and gateway path runs."""

    name = "simulated"
    SECRET = "simulated-webhook-secret"  # synthetic only; not a credential

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self.started: dict[str, StartVerificationCall] = {}

    def start_call(self, inp: StartVerificationCall) -> CallStarted:
        if not inp.consent_recorded:
            raise VoiceError("consent_missing", "Cardholder consent is not recorded.")
        cid = f"sim_{inp.callback_id}"
        self.started[cid] = inp
        return CallStarted(self.name, cid, cid, _now())

    def get_call_status(self, provider_call_id: str) -> CallStatus:
        return CallStatus.IN_PROGRESS

    def handle_webhook(self, payload: bytes, signature: str) -> VoiceEvent:
        verify_signature(self.SECRET, payload, signature, self._clock())
        return parse_elevenlabs(payload)

    def end_call(self, provider_call_id: str) -> None:
        return None

    def signed(self, doc: dict[str, Any]) -> tuple[bytes, str]:
        body = json.dumps({**doc, "simulated": True}).encode()
        return body, sign(self.SECRET, body, int(self._clock()))


def provider_name() -> str:
    name = os.environ.get("VERA_VOICE_PROVIDER", "simulated")
    if name not in ("elevenlabs", "simulated"):
        raise VoiceConfigError("VERA_VOICE_PROVIDER must be 'elevenlabs' or 'simulated'")
    return name


_PROVIDER: Any = None
# Test seam (never switched by product code), as in investigation.py.
LIVE_TRANSPORT: httpx.BaseTransport | None = None


def get_provider() -> Any:
    """No silent fallback: elevenlabs without its settings is a typed configuration error."""
    global _PROVIDER
    name = provider_name()
    if _PROVIDER is None or _PROVIDER.name != name:
        if name == "elevenlabs":
            _PROVIDER = ElevenLabsVoiceProvider(ElevenLabsConfig.from_env(), LIVE_TRANSPORT)
        else:
            _PROVIDER = SimulatedVoiceProvider()
    return _PROVIDER


def reset_provider() -> None:
    global _PROVIDER
    _PROVIDER = None


# ---- start (called from the start_callback effect, inside the gateway transaction)


def start_provider_call(
    session: Session, case: Case, row: Callback, run_id: str, consent: bool, now: datetime
) -> bool:
    """Returns False when the legacy synthetic telephony adapter should run the call."""
    if provider_name() != "elevenlabs":
        return False
    if not consent:
        reason = "Record the cardholder's consent before starting the call"
        raise CommandError("consent_missing", 422, reason, blocked_reason=reason)
    try:
        provider = get_provider()
    except VoiceConfigError as exc:
        raise CommandError("voice_unconfigured", 503, exc.reason) from None
    existing = session.scalars(select(VoiceCall).where(VoiceCall.callback_id == row.id)).first()
    if existing is not None:  # idempotency guard: one provider call per attempt
        return True
    from vera_api.evidence import read_evidence_field

    number, _ = read_evidence_field(session, case.id, row.target_record_id, row.target_field)
    e164 = to_e164(str(number))
    masked = mask_number(e164)
    inp = StartVerificationCall(
        case.id,
        row.id,
        row.attempt,
        e164,
        masked,
        PURPOSE,
        tuple(Question(q["id"], q["text"]) for q in row.questions),
        consent,
    )
    try:
        started = provider.start_call(inp)
    except VoiceError as exc:
        raise CommandError(exc.code, 502, exc.reason) from None
    session.add(
        VoiceCall(
            callback_id=row.id,
            attempt=row.attempt,
            provider=started.provider,
            provider_call_id=started.provider_call_id,
            conversation_id=started.conversation_id,
            masked_number=masked,
            run_id=run_id,
            status=CallStatus.QUEUED.value,
            started_at=now,
        )
    )
    session.flush()
    pause_for_call(session, row.id)
    enqueue(
        session,
        TIMEOUT_JOB,
        {"callback_id": row.id, "provider_call_id": started.provider_call_id},
        now=now,
        run_after=now + CALL_TIMEOUT,
    )
    return True


@register(TIMEOUT_JOB)
def run_timeout_job(session: Session, payload: dict[str, Any], touch: Touch) -> None:
    """A call with no final event by the deadline is timed out through the same event path."""
    call = session.scalars(
        select(VoiceCall).where(VoiceCall.provider_call_id == str(payload["provider_call_id"]))
    ).first()
    if call is None or call.status in {s.value for s in FINAL_STATUSES}:
        session.rollback()
        return
    event = VoiceEvent(
        "initiation_failure",
        f"timeout:{call.callback_id}",
        call.provider_call_id,
        failure_reason="timed_out",
        status=CallStatus.TIMED_OUT,
    )
    process_event(session, event, b"", call.provider)


# ---- LangGraph: the attempt pauses (interrupt) until a verified provider result resumes it


class CallState(TypedDict, total=False):
    callback_id: str
    result: dict[str, Any]


def _db_url(session: Session) -> str:
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    return engine.url.render_as_string(hide_password=False)


def _call_graph(saver: Any, on_result: Callable[[dict[str, Any]], None]) -> Any:
    def await_result(state: CallState) -> CallState:
        return {"result": interrupt({"waiting_for": "verified_voice_result"})}

    def continue_after_result(state: CallState) -> CallState:
        on_result(state["result"])
        return {}

    g = StateGraph(CallState)
    g.add_node("await_result", await_result)
    g.add_node("continue", continue_after_result)
    g.add_edge(START, "await_result")
    g.add_edge("await_result", "continue")
    g.add_edge("continue", END)
    return g.compile(checkpointer=saver)


def pause_for_call(session: Session, callback_id: str) -> None:
    """Run the attempt's graph to its interrupt (thread_id = callback attempt id)."""
    with postgres_checkpointer(_db_url(session)) as saver:
        graph = _call_graph(saver, lambda _r: None)
        config = {"configurable": {"thread_id": callback_id}}
        if graph.get_state(config).created_at is None:
            graph.invoke({"callback_id": callback_id}, config)


def resume_call(
    session: Session,
    callback_id: str,
    result: dict[str, Any],
    on_result: Callable[[dict[str, Any]], None],
) -> bool:
    """Resume only an interrupted attempt; a replay finds it finished and does nothing."""
    with postgres_checkpointer(_db_url(session)) as saver:
        graph = _call_graph(saver, on_result)
        config = {"configurable": {"thread_id": callback_id}}
        if graph.get_state(config).next != ("await_result",):
            return False
        graph.invoke(Command(resume=result), config)
        return True


def call_graph_state(session: Session, callback_id: str) -> tuple[str, ...]:
    with postgres_checkpointer(_db_url(session)) as saver:
        graph = _call_graph(saver, lambda _r: None)
        return tuple(graph.get_state({"configurable": {"thread_id": callback_id}}).next)


# ---- webhook


def _factory(session: Session) -> sessionmaker[Session]:
    bind = session.get_bind()
    engine = bind.engine if not isinstance(bind, Engine) else bind
    return sessionmaker(engine, expire_on_commit=False)


def process_event(session: Session, event: VoiceEvent, raw: bytes, provider: str) -> str:
    """Apply one verified event exactly once. Returns the recorded result."""
    now = _now()
    call = session.scalars(
        select(VoiceCall).where(VoiceCall.provider_call_id == event.provider_call_id)
    ).first()
    if event.kind == "ignored":
        result = "ignored"
    elif call is None:
        result = "orphan"
    else:
        result = "applied"
    ledger = VoiceWebhookEvent(
        event_id=event.event_id,
        provider=provider,
        provider_call_id=event.provider_call_id,
        kind=event.kind,
        received_at=now,
        raw_digest=hashlib.sha256(raw).hexdigest(),
        processed_at=now if result != "applied" else None,
        result=result,
    )
    session.add(ledger)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return "duplicate"
    if result != "applied":
        session.commit()
        return result
    assert call is not None
    row = session.get(Callback, call.callback_id)
    case = session.get(Case, row.case_id) if row else None
    if (
        row is None
        or case is None
        or row.status != "in_progress"
        or call.status in ("completed", "failed", "no_answer", "busy", "timed_out")
    ):
        ledger.result = "stale"
        ledger.processed_at = now
        session.commit()
        return "stale"
    call.last_event_at = now
    if event.kind == "transcript_final":
        _apply_transcript(session, case, row, call, event, now)
    else:
        _apply_failure(session, case, row, call, event, now)
    ledger.processed_at = now
    session.commit()
    case_id, callback_id, run_id = case.id, row.id, call.run_id or ""

    def on_result(result: dict[str, Any]) -> None:
        if result["kind"] == "transcript_final":
            # The Live Verification Agent validates the grounded answers, then record_callback.
            with _factory(session)() as s:
                payload = {"case_id": case_id, "callback_id": callback_id, "run_id": run_id}
                enqueue(s, callbacks.JOB_KIND, payload, now=now)
                s.commit()
        else:
            _record_failure(session, case_id, callback_id, run_id, event)

    resume_call(session, callback_id, {"kind": event.kind, "event_id": event.event_id}, on_result)
    return "applied"


def _apply_transcript(
    session: Session, case: Case, row: Callback, call: VoiceCall, event: VoiceEvent, now: datetime
) -> None:
    approved = tuple(Question(q["id"], q["text"]) for q in row.questions)
    ex = extract_answers(event, approved)
    version = (
        session.scalar(
            select(func.max(VoiceTranscriptVersion.version)).where(
                VoiceTranscriptVersion.callback_id == row.id
            )
        )
        or 0
    ) + 1
    lines = [{"index": ln.index, "role": ln.role, "message": ln.message} for ln in event.transcript]
    session.add(
        VoiceTranscriptVersion(
            callback_id=row.id,
            version=version,
            event_id=event.event_id,
            lines=lines,
            answers=[
                # line_index = seq of the cited line in CallbackDetail.transcript
                {"question_id": a.question_id, "answer": a.answer, "line_index": a.line_index + 1}
                for a in ex.answers
            ],
            rejected=list(ex.rejected),
            confidence=ex.confidence,
            created_at=now,
        )
    )
    if not callbacks._lines(session, row.id):
        for ln in event.transcript:
            session.add(
                CallbackLine(
                    callback_id=row.id,
                    seq=ln.index + 1,
                    speaker="agent" if ln.role == "agent" else "contact",
                    text=ln.message,
                    created_at=now,
                )
            )
    call.status = CallStatus.COMPLETED.value
    call.ended_at = now
    _emit(
        session,
        "callback.line_added",
        case,
        callbacks.SERVICE.user_id,
        Role.SYSTEM,
        now,
        [row.id],
        f"Call transcript received (version {version}, {len(lines)} lines)",
        {"callback_id": row.id, "version": version, "simulated": event.simulated},
    )


def _apply_failure(
    session: Session, case: Case, row: Callback, call: VoiceCall, event: VoiceEvent, now: datetime
) -> None:
    call.status = (event.status or CallStatus.FAILED).value
    call.ended_at = now
    if not callbacks._lines(session, row.id):
        session.add(
            CallbackLine(
                callback_id=row.id,
                seq=1,
                speaker="system",
                text=f"[call not connected: {event.failure_reason or call.status}]",
                created_at=now,
            )
        )


def _record_failure(
    session: Session, case_id: str, callback_id: str, run_id: str, event: VoiceEvent
) -> None:
    outcome = (
        "no_answer" if event.status in (CallStatus.NO_ANSWER, CallStatus.BUSY) else ("incomplete")
    )
    from vera_api import investigation

    investigation._execute_retrying(
        _factory(session),
        case_id,
        "record_callback",
        f"callback-result:{case_id}:{callback_id}",
        {"callback_id": callback_id, "run_id": run_id, "outcome": outcome, "answers": []},
        callbacks.SERVICE,
    )


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


webhook_router = APIRouter(prefix="/api/webhooks/voice")


@webhook_router.post("/elevenlabs")
async def elevenlabs_webhook(
    request: Request, session: Annotated[Session, Depends(_session)]
) -> JSONResponse:
    raw = await request.body()
    try:
        provider = get_provider()
    except VoiceConfigError as exc:
        return JSONResponse({"error": "voice_unconfigured", "reason": exc.reason}, 503)
    try:
        event = provider.handle_webhook(raw, request.headers.get("ElevenLabs-Signature", ""))
    except VoiceError as exc:
        return JSONResponse({"error": exc.code}, 401 if exc.code.startswith("signature") else 400)
    result = process_event(session, event, raw, provider.name)
    return JSONResponse({"result": result, "simulated": provider.name == "simulated"})


def voice_view(session: Session, callback_id: str) -> dict[str, Any] | None:
    """Read model for the case workspace (masked number only)."""
    call = session.scalars(select(VoiceCall).where(VoiceCall.callback_id == callback_id)).first()
    if call is None:
        return None
    versions = list(
        session.scalars(
            select(VoiceTranscriptVersion)
            .where(VoiceTranscriptVersion.callback_id == callback_id)
            .order_by(VoiceTranscriptVersion.version)
        )
    )
    latest = versions[-1] if versions else None
    return {
        "provider": call.provider,
        "simulated": call.provider == "simulated",
        "provider_call_id": call.provider_call_id,
        "masked_number": call.masked_number,
        "purpose": PURPOSE,
        "call_status": call.status,
        "started_at": call.started_at.isoformat(),
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "transcript_version": latest.version if latest else 0,
        "structured_answers": latest.answers if latest else [],
        "rejected": latest.rejected if latest else [],
        "confidence": latest.confidence if latest else None,
    }


plugins.register_router(webhook_router)
plugins.register_reset_tables(["voice_transcript_versions", "voice_webhook_events", "voice_calls"])
