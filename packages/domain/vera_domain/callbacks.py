"""Verification callback: payloads, command specs, reducers (pure)."""

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from vera_domain.commands import EventDraft, Payload, ReduceContext, Reduction, StepSet
from vera_domain.enums import CaseState, CaseStep
from vera_domain.facts import CaseFacts
from vera_domain.specialists import Finding, SpecialistSpec

MAX_ATTEMPTS = 2  # two attempts per response
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
    consent_recorded: bool = False  # required (true) when a real voice provider places the call
    # Echo of the offered target (payload_defaults). The call target is always read from the
    # register; any other record is refused, never dialled.
    target_record_id: str | None = None

    @model_validator(mode="after")
    def _contact_on_file(self) -> "StartCallbackPayload":
        if self.target_record_id not in (None, TARGET_RECORD):
            raise ValueError(f"target_record_id must be {TARGET_RECORD} (the contact on file)")
        return self


# Default verification questions (versioned), offered on start_callback for the analyst to edit
# and approve. Values come from the case's charge record; no other cardholder data is used.
QUESTION_SET_VERSION = "v1"
_CURRENCY_SIGN = {"USD": "$"}


def _amount(amount_cents: int, currency: str) -> str:
    sign = _CURRENCY_SIGN.get(currency)
    value = f"{amount_cents // 100:,}.{amount_cents % 100:02d}"
    return f"{sign}{value}" if sign else f"{value} {currency}"


def default_questions(
    *, merchant: str, amount_cents: int, currency: str, card_last4: str
) -> list[dict[str, str]]:
    return [
        {
            "id": "q1",
            "text": f"Did you place the order with {merchant} on the card ending {card_last4}?",
        },
        {
            "id": "q2",
            "text": f"Did you authorize this charge of {_amount(amount_cents, currency)}?",
        },
        {"id": "q3", "text": "Did anyone else have access to your card?"},
    ]


class Line(Payload):
    speaker: Literal["agent", "contact"]
    text: str = Field(min_length=1)


class Answer(Payload):
    question_id: str
    answer: str
    line_seq: int  # grounding: the transcript line that carries the answer


class RecordCallbackPayload(Payload):
    """The validated Live Verification Agent output for one call (service principal only)."""

    callback_id: str
    run_id: str
    outcome: Outcome
    authorization_answer: Literal["authorized", "unauthorized"] | None = None
    answers: list[Answer] = []


class RetryAgentPayload(Payload):
    mode: Literal["live", "replay"]


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
NOTE_STEPS = StepSet(  # a note needs a call on the current cycle
    include=frozenset(
        {
            (CaseState.CALLBACK_PENDING, CaseStep.WORKING),
            (CaseState.CALLBACK_PENDING, CaseStep.CALLFAIL),
        }
    )
)


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
        result={
            "callback_id": cid,
            "attempt": ctx.extra["attempt"],
            "run_id": ctx.extra.get("run_id"),
            "job_id": ctx.extra.get("job_id"),
        },
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
        result={
            "callback_id": p.callback_id,
            "note_id": ctx.extra.get("note_id"),
            "claim_id": ctx.extra.get("claim_id"),
        },
    )


# ---- Live Verification Agent (specialist) ----------------------------------------------------

AGENT = "live_verification_agent"
AGENT_PROMPT_VERSION = "v1"


class AgentInput(BaseModel):
    case_id: str
    callback_id: str
    question_fields: list[str]  # "question:{id}" field names on the callback record
    line_fields: list[str]  # "line:{seq}" field names on the callback record


class AgentAnswer(BaseModel):
    question_id: str
    answer: Literal["yes", "no", "unclear"]
    line_seq: int = Field(ge=1)
    quote: str  # exact text of the cited transcript line


class AgentOutput(BaseModel):
    outcome: Outcome
    result: Literal["confirmed", "failed"]
    authorization_answer: Literal["authorized", "unauthorized"] | None = None
    outcome_line_seq: int = Field(ge=1)
    outcome_quote: str
    answers: list[AgentAnswer] = []

    @model_validator(mode="after")
    def _consistent(self) -> "AgentOutput":
        if (self.result == "confirmed") != (self.outcome == "confirmed"):
            raise ValueError("result is confirmed exactly when the outcome is confirmed")
        return self


def agent_findings(callback_id: str) -> Callable[[BaseModel], list[Finding]]:
    """Every answer cites its approved question and one transcript line (exact text)."""

    def findings(output: BaseModel) -> list[Finding]:
        out = AgentOutput.model_validate(output.model_dump())
        found = [
            Finding(
                record_id=callback_id,
                version=1,
                field=f"line:{out.outcome_line_seq}",
                value=out.outcome_quote,
                statement=f"outcome {out.outcome}",
            )
        ]
        for a in out.answers:
            found.append(
                Finding(
                    record_id=callback_id,
                    version=1,
                    field=f"question:{a.question_id}",
                    value=a.question_id,
                    statement="approved question",
                )
            )
            found.append(
                Finding(
                    record_id=callback_id,
                    version=1,
                    field=f"line:{a.line_seq}",
                    value=a.quote,
                    statement=f"answer to {a.question_id}",
                )
            )
        return found

    return findings


AGENT_PURPOSE = (
    "Live Verification Agent. Purpose: you ran an analyst-approved verification call to the "
    "contact on file. Read the approved questions and the call transcript with the read_field "
    "tool (record = the callback id; fields 'question:{id}' return the question id, 'line:{seq}' "
    "return the exact transcript line). Report the structured result: outcome (confirmed = the "
    "contact answered and confirmed every approved question; contradicted = the contact denied; "
    "voicemail; no_answer; incomplete = the call ended before the questions were answered), "
    "result (confirmed only when outcome is confirmed, else failed), authorization_answer when "
    "the contact stated it, and one answer per approved question you could ask. Cite the "
    "transcript line that supports the outcome and each answer with its exact text. You may "
    "answer only the approved questions. You make no credit or policy decision. Reply with one "
    "JSON object only."
)


def agent_messages(inputs: AgentInput) -> list[dict[str, Any]]:
    import json

    schema = AgentOutput.model_json_schema()
    return [
        {
            "role": "system",
            "content": f"{AGENT_PURPOSE}\n\nOutput JSON schema: {json.dumps(schema)}",
        },
        {"role": "user", "content": json.dumps(inputs.model_dump(), sort_keys=True)},
    ]


def build_agent_spec(callback_id: str) -> SpecialistSpec:
    def messages(inputs: BaseModel) -> list[dict[str, Any]]:
        return agent_messages(AgentInput.model_validate(inputs.model_dump()))

    return SpecialistSpec(
        name=AGENT,
        prompt_version=AGENT_PROMPT_VERSION,
        input_schema=AgentInput,
        output_schema=AgentOutput,
        allowed_tools=frozenset({"read_field"}),
        allowed_record_ids=lambda _case_id: frozenset({callback_id}),
        build_messages=messages,
        findings_of=agent_findings(callback_id),
    )


def reduce_retry(f: CaseFacts, p: RetryAgentPayload, ctx: ReduceContext) -> Reduction:
    cid = ctx.extra.get("callback_id", "")
    return Reduction(
        facts=f,
        reason="Agent retried",
        events=[
            EventDraft(
                "callback.agent_retried",
                f"Live Verification Agent retried ({p.mode})",
                [cid],
                {"mode": p.mode},
            )
        ],
        result={k: ctx.extra.get(k) for k in ("callback_id", "run_id", "mode", "job_id")},
    )
