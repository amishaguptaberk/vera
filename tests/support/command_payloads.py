"""Test inputs for the registry-wide tests. Importable from every test directory
(tests/conftest.py puts tests/support on sys.path).

Each feature registers its commands in tests/support/payloads_<feature>.py (listed in FEATURES
below and loaded by load_features(), which tests/conftest.py calls), so any test file runs alone:
    from command_payloads import register_reducer_extras, register_test_payloads
    register_test_payloads({"send_x": {...}}, user_inputs={"send_x": {...}})
    register_reducer_extras({"send_x": {"x_id": "X-1"}})   # what your effect puts in ctx.extra

TEST_PAYLOADS: the full valid payload (403 matrix, reducer/declared-events test).
TEST_USER_INPUTS: what the user types on top of the action's payload_defaults (parity test).
REDUCER_EXTRAS: ReduceContext.extra the reducer needs (reducer/declared-events test).
A registered human command with no TEST_PAYLOADS entry FAILS those tests; it is never skipped.
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
    "review_related_charge": {
        "record_id": "CHG-1051",
        "decision": "not_related",
        "reason": "Different cost centre",
    },
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


# command -> ReduceContext.extra its reducer reads (normally written by the command's effect).
REDUCER_EXTRAS: dict[str, dict[str, Any]] = {
    "start_investigation": {"run": {"run_id": "r", "mode": "replay"}},
    "retry_specialist_step": {"run": {"run_id": "r", "mode": "replay"}},
    "review_related_charge": {"status": "not_relevant"},
    "evaluate_policy": {
        "policy": {
            "status": "eligible",
            "code": "CREDIT_ELIGIBLE",
            "label": "Eligible",
            "rules_failed": [],
            "evidence_used": [],
            "snapshot_hash": "s",
            "policy_version": 1,
        }
    },
}


def register_reducer_extras(extras: dict[str, dict[str, Any]]) -> None:
    for name, extra in extras.items():
        if name in REDUCER_EXTRAS:
            raise ValueError(f"reducer extras for '{name}' are already registered")
        REDUCER_EXTRAS[name] = extra


# One module per feature under tests/support/; each registers at import.
FEATURES = (
    "payloads_comms",
    "payloads_identity",
    "payloads_callbacks",
    "payloads_decisions",
    "payloads_money",
    "payloads_closure",
)


def load_features() -> None:
    """Import every feature's payload module once (idempotent: modules are cached)."""
    import importlib

    for name in FEATURES:
        importlib.import_module(name)
