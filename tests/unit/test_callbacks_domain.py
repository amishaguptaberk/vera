"""The default verification question set the analyst approves before a call."""

import pytest
from pydantic import ValidationError
from vera_domain.callbacks import (
    QUESTION_SET_VERSION,
    StartCallbackPayload,
    default_questions,
)


def test_default_questions_name_the_charge_from_its_record() -> None:
    qs = default_questions(
        merchant="Bayline Industrial Supply", amount_cents=284000, currency="USD", card_last4="4418"
    )
    assert qs == [
        {
            "id": "q1",
            "text": (
                "Did you place the order with Bayline Industrial Supply on the card ending 4418?"
            ),
        },
        {"id": "q2", "text": "Did you authorize this charge of $2,840.00?"},
        {"id": "q3", "text": "Did anyone else have access to your card?"},
    ]
    assert QUESTION_SET_VERSION == "v1"


def test_the_payload_accepts_only_the_contact_on_file_as_target() -> None:
    q = [{"id": "q1", "text": "Did you place the order?"}]
    ok = StartCallbackPayload.model_validate({"questions": q, "target_record_id": "PRF-4418"})
    assert ok.target_record_id == "PRF-4418"
    with pytest.raises(ValidationError):
        StartCallbackPayload.model_validate({"questions": q, "target_record_id": "PRF-9999"})
