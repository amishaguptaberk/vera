"""Final communication and closure command test inputs and reducer extras."""

from command_payloads import register_reducer_extras, register_test_payloads

register_test_payloads(
    {
        "draft_final_message": {},
        "update_final_message": {"body": "Hello, no further action is needed from you."},
        "send_final_message": {},
        "close_case": {"reason": "All outcomes recorded and sent", "outcome": "resolved"},
    }
)
# What each closure effect puts in ctx.extra (reducer/declared-events test).
register_reducer_extras(
    {
        "draft_final_message": {"message_id": "FM-1"},
        "update_final_message": {"message_id": "FM-1"},
        "send_final_message": {"message_id": "FM-1", "execution_id": "EX-1"},
        "close_case": {"closure_id": "CLS-1", "monitoring": False},
    }
)
