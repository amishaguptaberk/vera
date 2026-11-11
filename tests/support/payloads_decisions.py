"""Decision packet, decision and reviewer approval command test inputs and extras."""

from command_payloads import register_reducer_extras, register_test_payloads

register_test_payloads(
    {
        "create_decision_packet": {},
        "retry_decision_packet": {"mode": "replay"},
        "record_decision": {"decision": "credit", "rationale": "Duplicate charge confirmed."},
        "request_reviewer_approval": {},
        "approve_decision": {},
        "return_decision": {
            "reason": "Receipt is missing",
            "next_step": "Attach the receipt",
            "owner": "usr-sam-rivera",
        },
        "remind_reviewer": {},
        "reassign_reviewer": {"to": "usr-dana-okafor"},
        "complete_decision_packet": {"packet_version": 1, "run_id": "r"},
    }
)
# What each decisions effect puts in ctx.extra (reducer/declared-events test).
_PACKET_EXTRA = {"packet_version": 1, "snapshot_hash": "s", "policy_version": 1}
_APPROVAL_EXTRA = {"approval_id": "APR-1"}
register_reducer_extras(
    {
        "create_decision_packet": _PACKET_EXTRA,
        "record_decision": _PACKET_EXTRA,
        "request_reviewer_approval": _APPROVAL_EXTRA,
        "approve_decision": _APPROVAL_EXTRA,
        "return_decision": _APPROVAL_EXTRA,
        "remind_reviewer": _APPROVAL_EXTRA,
        "reassign_reviewer": _APPROVAL_EXTRA,
    }
)
