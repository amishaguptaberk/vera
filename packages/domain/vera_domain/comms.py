"""Cardholder follow-up (VER-005): payloads, command specs and reducers (pure)."""

from typing import Literal

from pydantic import Field

from vera_domain.commands import CommandSpec, EventDraft, Payload, ReduceContext, Reduction, StepSet
from vera_domain.enums import CaseState, CaseStep, Role, register_event_types
from vera_domain.facts import CaseFacts

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


def _r(event: str, summary: str, update: dict[str, object]) -> object:
    def reduce(f: CaseFacts, p: object, ctx: ReduceContext) -> Reduction:
        upd = dict(update)
        if "followups_sent" in ctx.extra:
            upd["followups_sent"] = ctx.extra["followups_sent"]
        if "response_review" in ctx.extra:
            upd["response_review"] = ctx.extra["response_review"]
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
    "Follow-up drafted for analyst approval",
    {"followup_status": "drafted"},
    "Draft follow-up",
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

HUMAN = {s.name: s for s in (DRAFT, UPDATE, SEND, REMIND, RESPOND, REVIEW)}
SERVICE = {DEADLINE.name: DEADLINE}
