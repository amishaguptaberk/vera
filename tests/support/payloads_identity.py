"""Identity verification command test inputs and reducer extras."""

from command_payloads import register_reducer_extras, register_test_payloads

register_test_payloads(
    {
        "send_verification_request": {"channel": "otp"},
        "resend_verification_request": {"verification_id": "IDV-NONE"},
        "cancel_verification_request": {"verification_id": "IDV-NONE"},
        "submit_otp": {"verification_id": "IDV-NONE", "code": "000000"},
        "answer_verification_push": {"verification_id": "IDV-NONE", "approve": True},
        "expire_verification_request": {"verification_id": "IDV-NONE"},
    }
)
# What each identity effect puts in ctx.extra (reducer/declared-events test).
_IDV_EXTRA = {"verification_id": "IDV-1", "status": "requested", "channel": "otp"}
register_reducer_extras(
    {
        "send_verification_request": _IDV_EXTRA,
        "resend_verification_request": _IDV_EXTRA,
        "cancel_verification_request": {**_IDV_EXTRA, "status": "cancelled"},
        "expire_verification_request": {**_IDV_EXTRA, "status": "expired"},
        "submit_otp": {**_IDV_EXTRA, "status": "verified", "outcome": "accepted"},
        "answer_verification_push": {**_IDV_EXTRA, "status": "verified", "outcome": "approved"},
    }
)
