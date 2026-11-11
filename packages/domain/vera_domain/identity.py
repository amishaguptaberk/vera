"""Identity verification (VER-006): payloads, reducers and command specs. Pure; no I/O.

The raw one-time code never appears here: payloads carry it only into the effect, which compares
it against a salted HMAC; reducers and events see only the outcome (decision D8).
"""

from typing import Literal

from pydantic import Field

from vera_domain.commands import (
    CommandSpec,
    EventDraft,
    Payload,
    ReduceContext,
    Reduction,
    StepSet,
)
from vera_domain.enums import CaseState, CaseStep, Role, register_event_types
from vera_domain.facts import CaseFacts
from vera_domain.labels import register_event_summaries

MAX_ATTEMPTS = 3
RESEND_COOLDOWN_SECONDS = 60
EXPIRES_AFTER_SECONDS = 600
MAX_SENDS = 3  # first send + 2 resends per verification request
SEND_LIMIT_REASON = "No resends remain on this request. Cancel it and send a new one."

IdentityStatus = Literal["requested", "verified", "failed", "expired", "declined", "cancelled"]

EVENTS = {
    "verification.requested": "Identity verification sent to the cardholder",
    "verification.resent": "Identity verification resent to the cardholder",
    "verification.cancelled": "Identity verification cancelled",
    "verification.expired": "Identity verification expired",
    "verification.code_submitted": "Cardholder submitted a verification code",
    "verification.code_rejected": "Cardholder entered an incorrect code",
    "verification.locked": "Verification failed: no attempts remain",
    "verification.verified": "Cardholder identity verified",
    "verification.push_answered": "Cardholder answered the verification prompt",
    "verification.declined": "Cardholder denied the verification prompt",
}
register_event_types(*EVENTS)
register_event_summaries(EVENTS)

IDV = StepSet(include=frozenset({(CaseState.CALLBACK_PENDING, CaseStep.IDV)}))


class SendVerificationPayload(Payload):
    channel: Literal["otp", "push"]


class VerificationRefPayload(Payload):
    verification_id: str = Field(min_length=1, max_length=64)


class SubmitOtpPayload(VerificationRefPayload):
    code: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]+$")


class AnswerPushPayload(VerificationRefPayload):
    approve: bool


def _status(ctx: ReduceContext) -> IdentityStatus:
    status: IdentityStatus = ctx.extra["status"]
    return status


def _reduce(event: str, reason: str):  # type: ignore[no-untyped-def]
    def reducer(f: CaseFacts, p: Payload, ctx: ReduceContext) -> Reduction:
        vid = str(ctx.extra["verification_id"])
        result = {k: v for k, v in ctx.extra.items() if k in RESULT_FIELDS}
        return Reduction(
            facts=f.model_copy(update={"identity_status": _status(ctx)}),
            reason=reason,
            events=[EventDraft(event, EVENTS[event], [ctx.case_id, vid], dict(result))],
            result=result,
        )

    return reducer


# Only these effect outputs reach events and idempotency rows; the code is never one of them.
RESULT_FIELDS = (
    "verification_id",
    "status",
    "channel",
    "outcome",
    "attempts",
    "attempts_left",
    "expires_at",
)

_ANALYST = frozenset({Role.ANALYST})
_CARDHOLDER = frozenset({Role.CARDHOLDER})

SEND = CommandSpec(
    "send_verification_request",
    _ANALYST,
    SendVerificationPayload,
    IDV,
    "idv:{case_id}:{case_version}",
    _reduce("verification.requested", "Verification sent"),
    ("verification.requested",),
    "Send verification",
    "primary",
)
RESEND = CommandSpec(
    "resend_verification_request",
    _ANALYST,
    VerificationRefPayload,
    IDV,
    "idv-resend:{verification_id}:{sends}",
    _reduce("verification.resent", "Verification resent"),
    ("verification.resent",),
    "Resend verification",
    "secondary",
)
CANCEL = CommandSpec(
    "cancel_verification_request",
    _ANALYST,
    VerificationRefPayload,
    IDV,
    "idv-cancel:{verification_id}",
    _reduce("verification.cancelled", "Verification cancelled"),
    ("verification.cancelled",),
    "Cancel verification",
    "secondary",
)
EXPIRE = CommandSpec(
    "expire_verification_request",
    frozenset({Role.SYSTEM}),
    VerificationRefPayload,
    IDV,
    "idv-expire:{verification_id}",
    _reduce("verification.expired", "Verification expired"),
    ("verification.expired",),
    "Expire verification",
    "secondary",
)
SUBMIT_OTP = CommandSpec(
    "submit_otp",
    _CARDHOLDER,
    SubmitOtpPayload,
    IDV,
    "otp:{verification_id}:{attempt_no}",
    _reduce("verification.code_submitted", "Code checked"),
    ("verification.code_submitted",),
    "Enter code",
    "primary",
)
ANSWER_PUSH = CommandSpec(
    "answer_verification_push",
    _CARDHOLDER,
    AnswerPushPayload,
    IDV,
    "push:{verification_id}",
    _reduce("verification.push_answered", "Push answered"),
    ("verification.push_answered",),
    "Answer prompt",
    "primary",
)

HUMAN = {s.name: s for s in (SEND, RESEND, CANCEL, SUBMIT_OTP, ANSWER_PUSH)}
SERVICE = {EXPIRE.name: EXPIRE}
