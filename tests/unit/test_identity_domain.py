"""VER-006 pure domain: reducers mirror the effect's status; events never carry a code."""

from datetime import UTC, datetime

import pytest
from vera_domain import identity as dom
from vera_domain.commands import ReduceContext
from vera_domain.enums import CaseState, CaseStep, Role
from vera_domain.facts import CaseFacts, derive_step

NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
OPENED = CaseFacts(owner_id="u", opened_at=NOW, response_review="incomplete")


def ctx(status: str, **extra: object) -> ReduceContext:
    c = ReduceContext("C", "u", "U", Role.CARDHOLDER, NOW, lambda r: (r, r), "REP-1")
    c.extra.update({"verification_id": "IDV-1", "status": status, **extra, "code": "123456"})
    return c


@pytest.mark.parametrize(
    ("status", "step"),
    [
        ("requested", CaseStep.IDV),
        ("failed", CaseStep.IDV),
        ("declined", CaseStep.IDV),
        ("expired", CaseStep.IDV),
        ("cancelled", CaseStep.IDV),
        ("verified", CaseStep.VERIFY),
    ],
)
def test_submit_reducer_mirrors_status_and_derives_the_step(status: str, step: CaseStep) -> None:
    payload = dom.SubmitOtpPayload(verification_id="IDV-1", code="123456")
    red = dom.SUBMIT_OTP.reducer(OPENED, payload, ctx(status, outcome="rejected"))
    assert red.facts.identity_status == status
    assert derive_step(red.facts) == (CaseState.CALLBACK_PENDING, step)


def test_every_identity_reducer_emits_its_declared_events_and_never_the_code() -> None:
    payloads = {
        "send_verification_request": dom.SendVerificationPayload(channel="otp"),
        "submit_otp": dom.SubmitOtpPayload(verification_id="IDV-1", code="123456"),
        "answer_verification_push": dom.AnswerPushPayload(verification_id="IDV-1", approve=False),
    }
    for spec in (*dom.HUMAN.values(), *dom.SERVICE.values()):
        p = payloads.get(spec.name, dom.VerificationRefPayload(verification_id="IDV-1"))
        red = spec.reducer(OPENED, p, ctx("requested"))
        assert tuple(e.type for e in red.events) == spec.events
        assert "123456" not in repr(red.events) + repr(red.result)


def test_payloads_strip_and_validate_codes() -> None:
    assert dom.SubmitOtpPayload(verification_id=" IDV-1 ", code=" 123456 ").code == "123456"
    with pytest.raises(ValueError):
        dom.SubmitOtpPayload(verification_id="IDV-1", code="12ab56")
    with pytest.raises(ValueError):
        dom.SendVerificationPayload(channel="sms")  # type: ignore[arg-type]


def test_only_the_cardholder_answers_and_expiry_is_system_only() -> None:
    assert dom.SUBMIT_OTP.roles == dom.ANSWER_PUSH.roles == frozenset({Role.CARDHOLDER})
    assert dom.EXPIRE.roles == frozenset({Role.SYSTEM})
    assert dom.MAX_ATTEMPTS == 3 and dom.MAX_SENDS == 3
