"""Credit, dispute and card controls (VER-010) command test inputs and reducer extras."""

from command_payloads import register_reducer_extras, register_test_payloads

register_test_payloads(
    {
        "issue_provisional_credit": {},
        "lookup_execution_result": {"idempotency_key": "credit:TXN-1042"},
        "prepare_dispute_packet": {},
        "open_dispute_packet": {},
        "review_dispute_packet": {},
        "submit_dispute": {},
        "propose_card_controls": {"controls": ["lock", "replace"]},
        "skip_card_controls": {"reason": "Card already replaced"},
        "approve_card_controls": {},
        "decline_card_controls": {"reason": "Not needed"},
        "apply_card_controls": {},
        "retry_dispute_narrative": {"mode": "replay"},
    }
)
# What each money effect puts in ctx.extra: the stored track fact it mirrors.
_CREDIT = {"credit_status": "requested"}
_DISPUTE = {"dispute_status": "prepared"}
_CONTROLS = {"controls_status": "proposed"}
register_reducer_extras(
    {
        "issue_provisional_credit": _CREDIT,
        "lookup_execution_result": _CREDIT,
        "prepare_dispute_packet": _DISPUTE,
        "open_dispute_packet": _DISPUTE,
        "review_dispute_packet": _DISPUTE,
        "submit_dispute": _DISPUTE,
        "propose_card_controls": _CONTROLS,
        "skip_card_controls": _CONTROLS,
        "approve_card_controls": _CONTROLS,
        "decline_card_controls": _CONTROLS,
        "apply_card_controls": _CONTROLS,
    }
)
