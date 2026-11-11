"""Cardholder follow-up: payloads, command specs and reducers (pure)."""

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from vera_domain.commands import CommandSpec, EventDraft, Payload, ReduceContext, Reduction, StepSet
from vera_domain.enums import CaseState, CaseStep, Role, register_event_types
from vera_domain.facts import CaseFacts
from vera_domain.specialists import Finding, SpecialistSpec

ALLOWED_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})
MAX_BYTES = 10 * 1024 * 1024  # gap G7: 10 MB

register_event_types(
    "communication.drafted",
    "communication.updated",
    "communication.sent",
    "communication.reminded",
    "communication.overdue",
    "communication.responded",
    "communication.reviewed",
    "communication.review_recommended",
)

DRAFT_STEP = StepSet(include=frozenset({(CaseState.INVESTIGATING, CaseStep.DRAFT)}))
WAIT_STEPS = frozenset(
    {
        (CaseState.WAITING_ON_CARDHOLDER, CaseStep.WAITING),
        (CaseState.WAITING_ON_CARDHOLDER, CaseStep.NORESP1),
        (CaseState.WAITING_ON_CARDHOLDER, CaseStep.NORESP2),
    }
)


class DraftFollowUpPayload(Payload):
    pass


class RetryDraftPayload(Payload):
    mode: Literal["replay", "live"] = "replay"


# ---- Cardholder Follow-up specialist (typed, grounded; drafts only, never sends) ---------------

FOLLOW_UP = "cardholder_follow_up"
RESPONSE_REVIEWER = "response_reviewer"
PROMPT_VERSION = "v1"


class ItemRef(BaseModel):
    record_id: str
    version: int = Field(ge=1)
    field: str


class Citation(ItemRef):
    value: Any


class OpenFindingRef(BaseModel):
    finding_id: str
    kind: str
    links: list[ItemRef]


class FollowUpInput(BaseModel):
    case_id: str
    open_findings: list[OpenFindingRef]
    missing_records: list[str]
    initial_report_id: str | None


class Question(BaseModel):
    text: str = Field(min_length=5, max_length=500)
    resolves: Citation  # the unresolved register item this question resolves
    finding_id: str | None = None


class FollowUpOutput(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    questions: list[Question] = Field(min_length=1, max_length=5)


class ResponseReviewInput(BaseModel):
    case_id: str
    request_id: str
    response_id: str
    initial_report_id: str


class ReviewCitation(Citation):
    statement: str = Field(min_length=1)


class ResponseReviewOutput(BaseModel):
    classification: Literal["complete", "incomplete", "conflicting"]
    citations: list[ReviewCitation] = Field(min_length=1)


def _follow_up_findings(out: BaseModel) -> list[Finding]:
    assert isinstance(out, FollowUpOutput)
    return [
        Finding(
            record_id=q.resolves.record_id,
            version=q.resolves.version,
            field=q.resolves.field,
            value=q.resolves.value,
            statement=q.text,
        )
        for q in out.questions
    ]


def _review_findings(out: BaseModel) -> list[Finding]:
    assert isinstance(out, ResponseReviewOutput)
    return [
        Finding(
            record_id=c.record_id,
            version=c.version,
            field=c.field,
            value=c.value,
            statement=c.statement,
        )
        for c in out.citations
    ]


_FU_SYSTEM = (
    "Cardholder Follow-up specialist. Purpose: draft ONE short request to the cardholder that "
    "asks only about the unresolved items listed (open findings and missing records). Read every "
    "value you use with the read_field tool; only unresolved items can be read. Each question "
    "must cite the item it resolves as resolves={record_id, version, field, value}, exactly as "
    "read_field returned it, and give finding_id when it resolves an open finding. Do not ask "
    "about anything already supported. Do not mention policy, internal ids of staff, specialists "
    "or findings in the question text. You never send anything. Reply with one JSON object only."
)
_RR_SYSTEM = (
    "Response reviewer (Receipt and Document Reviewer). Purpose: classify the cardholder's reply "
    "as complete (answers every question, consistent with the initial report), incomplete "
    "(leaves a question unanswered) or conflicting (contradicts the initial report). Read the "
    "reply text, the request's questions and the initial report statement with read_field and "
    "cite each value your classification rests on as {record_id, version, field, value, "
    "statement}. This is a recommendation for the analyst, not a decision. Reply with one JSON "
    "object only."
)


def _messages(system: str, schema: type[BaseModel], inputs: BaseModel) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": f"{system}\n\nOutput JSON schema: {json.dumps(schema.model_json_schema())}",
        },
        {"role": "user", "content": json.dumps(inputs.model_dump(), sort_keys=True)},
    ]


def follow_up_spec(allowed: frozenset[str]) -> SpecialistSpec:
    return SpecialistSpec(
        name=FOLLOW_UP,
        prompt_version=PROMPT_VERSION,
        input_schema=FollowUpInput,
        output_schema=FollowUpOutput,
        allowed_tools=frozenset({"read_field"}),
        allowed_record_ids=lambda _c: allowed,
        build_messages=lambda i: _messages(_FU_SYSTEM, FollowUpOutput, i),
        findings_of=_follow_up_findings,
    )


def response_review_spec(allowed: frozenset[str]) -> SpecialistSpec:
    return SpecialistSpec(
        name=RESPONSE_REVIEWER,
        prompt_version=PROMPT_VERSION,
        input_schema=ResponseReviewInput,
        output_schema=ResponseReviewOutput,
        allowed_tools=frozenset({"read_field"}),
        allowed_record_ids=lambda _c: allowed,
        build_messages=lambda i: _messages(_RR_SYSTEM, ResponseReviewOutput, i),
        findings_of=_review_findings,
    )


class StoreDraftPayload(Payload):
    run_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=3, max_length=200)
    questions: list[Question] = Field(min_length=1, max_length=5)


class RecommendationPayload(Payload):
    response_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=64)
    classification: Literal["complete", "incomplete", "conflicting"]
    citations: list[ReviewCitation] = Field(min_length=1)


class UpdateDraftPayload(Payload):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=4000)


class SendPayload(Payload):
    channel: Literal["email", "portal"] = "email"
    subject: str = Field(min_length=3, max_length=200)
    attachments: list[str] = Field(default_factory=list, max_length=5)


class ReminderPayload(Payload):
    pass


class DeadlinePayload(Payload):
    pass


class ResponseAttachment(Payload):
    file_name: str = Field(min_length=1, max_length=64)
    content_type: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(ge=1, le=MAX_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SubmitResponsePayload(Payload):
    request_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    attachment: ResponseAttachment | None = None


class ReviewResponsePayload(Payload):
    outcome: Literal["complete", "incomplete", "conflicting"]
    note: str = Field(default="", max_length=1000)
    # The attached receipt is accepted as evidence. A complete review accepts it; on an
    # incomplete or conflicting review it stays pending review unless the analyst accepts it.
    receipt_accepted: bool = False


def _r(event: str, summary: str, update: dict[str, object]) -> object:
    def reduce(f: CaseFacts, p: object, ctx: ReduceContext) -> Reduction:
        upd = dict(update)
        if "followups_sent" in ctx.extra:
            upd["followups_sent"] = ctx.extra["followups_sent"]
        if "response_review" in ctx.extra:
            upd["response_review"] = ctx.extra["response_review"]
        upd.update(ctx.extra.get("_facts", {}))
        return Reduction(
            facts=f.model_copy(update=upd),
            reason=summary,
            events=[EventDraft(event, summary, [ctx.extra.get("request_id", ctx.case_id)])],
            result={k: v for k, v in ctx.extra.items() if not k.startswith("_")},
        )

    return reduce


def _spec(
    name: str,
    roles: set[Role],
    model: type[Payload],
    steps: StepSet,
    key: str,
    event: str,
    summary: str,
    update: dict[str, object],
    label: str,
    style: Literal["primary", "secondary", "dark", "ghost"] = "secondary",
) -> CommandSpec:
    return CommandSpec(
        name,
        frozenset(roles),
        model,
        steps,
        key,
        _r(event, summary, update),  # type: ignore[arg-type]
        (event,),
        label,
        style,
    )


DRAFT = _spec(
    "draft_follow_up",
    {Role.ANALYST},
    DraftFollowUpPayload,
    DRAFT_STEP,
    "draft:{case_id}",
    "communication.drafted",
    "Follow-up drafting started",
    {"investigation_run_status": "running"},
    "Draft follow-up",
)
STORE = _spec(
    "store_communication_draft",
    {Role.SPECIALIST},
    StoreDraftPayload,
    StepSet(include=frozenset({(CaseState.INVESTIGATING, CaseStep.WORKING)})),
    "store-draft:{case_id}:{run_id}",
    "communication.updated",
    "Follow-up draft stored for analyst approval",
    {"followup_status": "drafted", "investigation_run_status": "succeeded"},
    "Store draft",
)
RETRY = _spec(
    "retry_follow_up_draft",
    {Role.ANALYST},
    RetryDraftPayload,
    StepSet(include=frozenset({(CaseState.INVESTIGATING, CaseStep.WORKING)})),
    "retry-draft:{case_id}:{run_id}:{mode}",
    "communication.drafted",
    "Follow-up drafting retried",
    {"investigation_run_status": "running"},
    "Retry follow-up draft",
)
RECOMMEND = _spec(
    "store_review_recommendation",
    {Role.SPECIALIST},
    RecommendationPayload,
    StepSet(include=frozenset({(CaseState.RESPONSE_RECEIVED, CaseStep.RESPONSE)})),
    "recommend:{case_id}:{response_id}",
    "communication.review_recommended",
    "Response review recommendation stored",
    {},
    "Store recommendation",
)
UPDATE = _spec(
    "update_communication_draft",
    {Role.ANALYST},
    UpdateDraftPayload,
    DRAFT_STEP,
    "draft-edit:{case_id}:{case_version}",
    "communication.updated",
    "Follow-up draft edited",
    {"followup_status": "drafted"},
    "Edit draft",
)
SEND = _spec(
    "send_communication",
    {Role.ANALYST},
    SendPayload,
    DRAFT_STEP,
    "send:{case_id}",
    "communication.sent",
    "Request sent to the cardholder",
    {"followup_status": "sent"},
    "Approve and send",
    "primary",
)
REMIND = _spec(
    "send_reminder",
    {Role.ANALYST},
    ReminderPayload,
    StepSet(include=WAIT_STEPS),
    "remind:{case_id}:{case_version}",
    "communication.reminded",
    "Reminder sent to the cardholder",
    {"followup_status": "reminded"},
    "Send reminder",
)
RESPOND = _spec(
    "submit_cardholder_response",
    {Role.CARDHOLDER},
    SubmitResponsePayload,
    StepSet(include=WAIT_STEPS),
    "respond:{request_id}",
    "communication.responded",
    "Cardholder replied to the request",
    {"followup_status": "responded"},
    "Submit response",
)
REVIEW = _spec(
    "review_cardholder_response",
    {Role.ANALYST},
    ReviewResponsePayload,
    StepSet(include=frozenset({(CaseState.RESPONSE_RECEIVED, CaseStep.RESPONSE)})),
    "review:{case_id}:{case_version}",
    "communication.reviewed",
    "Cardholder response reviewed",
    {},
    "Review response",
    "primary",
)
DEADLINE = _spec(
    "mark_deadline_missed",
    {Role.SYSTEM},
    DeadlinePayload,
    StepSet(include=frozenset({(CaseState.WAITING_ON_CARDHOLDER, CaseStep.WAITING)})),
    "deadline:{case_id}:{request_id}",
    "communication.overdue",
    "Reply deadline missed",
    {"followup_status": "overdue"},
    "Mark deadline missed",
)

HUMAN = {s.name: s for s in (DRAFT, RETRY, UPDATE, SEND, REMIND, RESPOND, REVIEW)}
SERVICE = {s.name: s for s in (DEADLINE, STORE, RECOMMEND)}
