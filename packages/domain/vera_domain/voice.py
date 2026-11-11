"""Voice verification boundary (pure): provider-neutral types, masking, webhook parsing, and the
extractor that turns provider output into structured answers for approved questions only.

The voice provider runs the conversation; it never decides anything. Its output is evidence to
be grounded: an answer counts only when it belongs to an approved question id and its value is
found in a transcript line (the cited line index). Anything else is rejected, never applied.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol


class CallStatus(StrEnum):
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    TIMED_OUT = "timed_out"


FINAL_STATUSES = frozenset(
    {
        CallStatus.COMPLETED,
        CallStatus.FAILED,
        CallStatus.NO_ANSWER,
        CallStatus.BUSY,
        CallStatus.TIMED_OUT,
    }
)


@dataclass(frozen=True)
class Question:
    id: str
    text: str


@dataclass(frozen=True)
class StartVerificationCall:
    case_id: str
    callback_id: str
    attempt: int
    to_number_e164: str
    masked_number: str
    purpose: str
    questions: tuple[Question, ...]
    consent_recorded: bool


@dataclass(frozen=True)
class CallStarted:
    provider: str
    provider_call_id: str
    conversation_id: str
    started_at: datetime


@dataclass(frozen=True)
class TranscriptLine:
    index: int
    role: str
    message: str
    time_in_call_secs: float | None = None


@dataclass(frozen=True)
class VoiceEvent:
    kind: Literal["transcript_final", "initiation_failure", "status", "ignored"]
    event_id: str
    provider_call_id: str
    transcript: tuple[TranscriptLine, ...] = ()
    raw_answers: dict[str, Any] = field(default_factory=dict)
    call_successful: str | None = None
    summary: str | None = None
    failure_reason: str | None = None
    status: CallStatus | None = None
    simulated: bool = False


class VoiceVerificationProvider(Protocol):
    name: str

    def start_call(self, inp: StartVerificationCall) -> CallStarted: ...

    def get_call_status(self, provider_call_id: str) -> CallStatus: ...

    def handle_webhook(self, payload: bytes, signature: str) -> VoiceEvent: ...

    def end_call(self, provider_call_id: str) -> None: ...


class VoiceError(Exception):
    """Typed boundary failure; `reason` is safe to show (never carries secrets or numbers)."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def mask_number(number: str) -> str:
    """'+15551234567' -> '+1 *** *** 4567'. Only the last four digits ever leave the backend."""
    digits = re.sub(r"\D", "", number)
    if len(digits) < 4:
        return "***"
    prefix = "+1 " if digits.startswith("1") and len(digits) == 11 else "+"
    return f"{prefix}*** *** {digits[-4:]}"


def to_e164(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) == 10:
        digits = "1" + digits
    if not 11 <= len(digits) <= 15:
        raise VoiceError("invalid_number", "The number on file is not a dialable number.")
    return "+" + digits


def dynamic_variables(inp: StartVerificationCall) -> dict[str, str]:
    """Only the case reference, purpose and approved questions; never PII or secrets."""
    return {
        "case_ref": inp.case_id,
        "purpose": inp.purpose,
        "questions": "\n".join(f"{i}. {q.text}" for i, q in enumerate(inp.questions, start=1)),
        "question_ids": ",".join(q.id for q in inp.questions),
    }


_FAILURES = {"busy": CallStatus.BUSY, "no-answer": CallStatus.NO_ANSWER}


def event_id_for(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def parse_elevenlabs(raw: bytes) -> VoiceEvent:
    """Parse a verified ElevenLabs webhook body into a provider-neutral VoiceEvent."""
    try:
        doc = json.loads(raw)
    except ValueError:
        raise VoiceError("schema_invalid", "Webhook body is not JSON.") from None
    kind = doc.get("type")
    data = doc.get("data") or {}
    eid = str(doc.get("event_id") or event_id_for(raw))
    cid = str(data.get("conversation_id") or "")
    simulated = bool(doc.get("simulated"))
    if kind == "post_call_transcription":
        lines = tuple(
            TranscriptLine(
                i, str(t.get("role", "")), str(t.get("message") or ""), t.get("time_in_call_secs")
            )
            for i, t in enumerate(data.get("transcript") or [])
        )
        analysis = data.get("analysis") or {}
        return VoiceEvent(
            "transcript_final",
            eid,
            cid,
            transcript=lines,
            raw_answers=dict(analysis.get("data_collection_results") or {}),
            call_successful=analysis.get("call_successful"),
            summary=analysis.get("transcript_summary"),
            status=CallStatus.COMPLETED,
            simulated=simulated,
        )
    if kind == "call_initiation_failure":
        reason = str(data.get("failure_reason") or "unknown")
        return VoiceEvent(
            "initiation_failure",
            eid,
            cid,
            failure_reason=reason,
            status=_FAILURES.get(reason, CallStatus.FAILED),
            simulated=simulated,
        )
    return VoiceEvent("ignored", eid, cid, simulated=simulated)


@dataclass(frozen=True)
class GroundedAnswer:
    question_id: str
    answer: str
    line_index: int


@dataclass(frozen=True)
class Extraction:
    answers: tuple[GroundedAnswer, ...]
    rejected: tuple[str, ...]
    confidence: float


_ALLOWED_ITEM_KEYS = {"data_collection_id", "value", "json_schema", "rationale"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def extract_answers(event: VoiceEvent, approved: tuple[Question, ...]) -> Extraction:
    """Map data-collection results to approved questions; ground each value in a transcript line.

    Rejects: items for non-approved ids, items carrying anything but a value (e.g. an action),
    and values not found in a non-agent transcript line. Confidence = grounded / approved.
    """
    ids = {q.id for q in approved}
    answers: list[GroundedAnswer] = []
    rejected: list[str] = []
    for key, item in event.raw_answers.items():
        if key not in ids:
            rejected.append(f"{key}: not an approved question")
            continue
        if not isinstance(item, dict) or set(item) - _ALLOWED_ITEM_KEYS:
            rejected.append(f"{key}: unexpected content")
            continue
        value = item.get("value")
        if value is None or str(value).strip() == "":
            continue
        needle = _norm(str(value))
        cite = next(
            (
                ln.index
                for ln in event.transcript
                if ln.role != "agent" and needle and needle in _norm(ln.message)
            ),
            None,
        )
        if cite is None:
            rejected.append(f"{key}: answer not found in transcript")
            continue
        answers.append(GroundedAnswer(key, str(value), cite))
    conf = round(len(answers) / len(approved), 2) if approved else 0.0
    return Extraction(tuple(answers), tuple(rejected), conf)
