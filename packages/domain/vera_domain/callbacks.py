"""Verification callback (VER-007): payloads, command specs, reducers (pure)."""

from typing import Literal

from pydantic import BaseModel, Field

from vera_domain.commands import EventDraft, Payload, ReduceContext, Reduction, StepSet
from vera_domain.enums import CaseState, CaseStep
from vera_domain.facts import CaseFacts

MAX_ATTEMPTS = 2  # Handoff 7.2: two attempts per response
TARGET_RECORD = "PRF-4418"
TARGET_FIELD = "phone"
OUTCOMES = ("confirmed", "contradicted", "voicemail", "no_answer", "incomplete")
Outcome = Literal["confirmed", "contradicted", "voicemail", "no_answer", "incomplete"]
LIMIT_REASON = "Two callback attempts made for this response · send a follow-up or hold."


class Question(Payload):
    id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=500)


class StartCallbackPayload(Payload):
    questions: list[Question] = Field(min_length=1, max_length=10)


class Line(Payload):
    speaker: Literal["agent", "contact"]
    text: str = Field(min_length=1)


class Answer(Payload):
    question_id: str
    answer: str
    line_seq: int  # grounding: the transcript line that carries the answer


class RecordCallbackPayload(Payload):
    callback_id: str
    outcome: Outcome
    transcript: list[Line]
    authorization_answer: Literal["authorized", "unauthorized"] | None = None
    answers: list[Answer] = []


class CallbackNotePayload(Payload):
    callback_id: str
    text: str = Field(min_length=1, max_length=2000)


class StructuredResult(BaseModel):
    result: Literal["confirmed", "failed"]
    outcome: Outcome
    authorization_answer: Literal["authorized", "unauthorized"] | None
    answers: list[Answer]


START_STEPS = StepSet(
    include=frozenset(
        {
            (CaseState.CALLBACK_PENDING, CaseStep.VERIFY),
            (CaseState.CALLBACK_PENDING, CaseStep.CALLFAIL),
        }
    )
)
WORKING_STEPS = StepSet(include=frozenset({(CaseState.CALLBACK_PENDING, CaseStep.WORKING)}))
NOTE_STEPS = StepSet(exclude_states=frozenset({CaseState.CLOSED}))


def reduce_start(f: CaseFacts, p: StartCallbackPayload, ctx: ReduceContext) -> Reduction:
    cid = ctx.extra["callback_id"]
    return Reduction(
        facts=f.model_copy(
            update={"callback_status": "in_progress", "callback_attempts": ctx.extra["attempt"]}
        ),
        reason="Callback approved",
        events=[
            EventDraft(
                "callback.started",
                f"Verification call {cid} approved (attempt {ctx.extra['attempt']})",
                [cid, TARGET_RECORD],
                {"questions": [q.id for q in p.questions]},
            )
        ],
        result={"callback_id": cid, "attempt": ctx.extra["attempt"]},
    )


def reduce_record(f: CaseFacts, p: RecordCallbackPayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f.model_copy(update={"callback_status": p.outcome}),
        reason=f"Callback {p.outcome}",
        events=[
            EventDraft(
                "callback.recorded",
                f"Verification call {p.callback_id}: {p.outcome.replace('_', ' ')}",
                [p.callback_id],
                {"outcome": p.outcome},
            )
        ],
        result={"callback_id": p.callback_id, "status": p.outcome, **ctx.extra},
    )


def reduce_note(f: CaseFacts, p: CallbackNotePayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f,
        reason="Callback note",
        events=[EventDraft("callback.note_added", "Note added to the call", [p.callback_id])],
        result={"callback_id": p.callback_id, "note_id": ctx.extra["note_id"]},
    )
