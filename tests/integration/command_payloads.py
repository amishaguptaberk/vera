"""Payloads the registry-wide tests send (role x command 403 matrix, enabled/blocked parity).

A plug-in test module adds its commands at import:
    from command_payloads import register_test_payloads
    register_test_payloads({"send_communication": {...}}, user_inputs={"send_communication": {...}})
TEST_PAYLOADS is the full valid payload; TEST_USER_INPUTS is what the user types on top of the
action's payload_defaults. A human command without an entry fails the parity test.
"""

from typing import Any

TEST_PAYLOADS: dict[str, dict[str, Any]] = {
    "open_case": {},
    "hold_case": {"reason": "Waiting for the bank", "next_owner": "usr-dana-okafor"},
    "resume_case": {},
    "reassign_case": {"to": "usr-dana-okafor", "reason": "Card program owns this"},
    "link_report": {"report_id": "REP-1047", "statement": "Second call about the same charge."},
    "evaluate_policy": {},
    "start_investigation": {},
    "retry_specialist_step": {"step_key": "charge_investigator", "mode": "replay"},
}

TEST_USER_INPUTS: dict[str, dict[str, Any]] = {
    **TEST_PAYLOADS,
    "link_report": {"statement": "Second call about the same charge."},
}


def register_test_payloads(
    payloads: dict[str, dict[str, Any]], *, user_inputs: dict[str, dict[str, Any]] | None = None
) -> None:
    for name, body in payloads.items():
        if name in TEST_PAYLOADS:
            raise ValueError(f"test payload for '{name}' is already registered")
        TEST_PAYLOADS[name] = body
        TEST_USER_INPUTS[name] = (user_inputs or {}).get(name, body)
