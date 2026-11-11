"""Verification callback command test inputs and reducer extras."""

from command_payloads import register_reducer_extras, register_test_payloads

QUESTIONS = [{"id": "q1", "text": "Did you place the Bayline Industrial Supply order?"}]

register_test_payloads(
    {
        "start_callback": {"questions": QUESTIONS},
        "add_callback_note": {"callback_id": "CALL-1042-1", "text": "Left a note."},
        "retry_callback_agent": {"mode": "replay"},
        "record_callback": {"callback_id": "CALL-1042-1", "run_id": "r", "outcome": "confirmed"},
    }
)
# What start_callback's effect puts in ctx.extra (reducer/declared-events test).
register_reducer_extras({"start_callback": {"callback_id": "CALL-1042-1", "attempt": 1}})
