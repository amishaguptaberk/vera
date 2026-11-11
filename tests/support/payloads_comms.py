"""Cardholder follow-up command test inputs."""

from command_payloads import register_test_payloads

register_test_payloads(
    {
        "draft_follow_up": {},
        "retry_follow_up_draft": {"mode": "replay"},
        "update_communication_draft": {
            "subject": "Question about your charge",
            "body": "Please upload the receipt for this charge.",
        },
        "send_communication": {
            "channel": "email",
            "subject": "Question about your Bayline charge",
            "attachments": [],
        },
        "send_reminder": {},
        "submit_cardholder_response": {"request_id": "MSG-2201", "text": "Receipt attached."},
        "review_cardholder_response": {"outcome": "complete"},
    }
)
