"""Enabled-action acceptance, generic over every case state the eval scenarios reach.

For each reachable (state, step, run status): every enabled action is accepted with the key the
case view advertises, and every blocked action is rejected 409 with the same blocked_reason.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from command_payloads import TEST_PAYLOADS, TEST_USER_INPUTS

from evals import harness

ROLES = ["analyst", "reviewer", "card_admin", "cardholder"]
# Inputs a human supplies on top of the action's payload_defaults, from the registry-wide test
# payloads every feature registers (tests/support/payloads_<feature>.py).
USER_INPUTS = TEST_USER_INPUTS
# A blocked action must be refused for its state, not for a malformed body: probe with the
# command's full valid test payload.
PROBE_INPUTS = TEST_PAYLOADS


@pytest.fixture(scope="module")
def world() -> Iterator[harness.World]:
    with harness.world() as w:
        yield w


def reachable_states(w: harness.World) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    """First step prefix (over all runnable scenarios) that reaches each distinct case state."""
    seen: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for path, sc in harness.load_scenarios():
        if sc.get("status") == "pending":
            continue
        steps = [
            {k: v for k, v in s.items() if k not in ("assert", "expect", "expect_each")}
            for s in sc["steps"]
        ]
        for n in range(len(steps) + 1):
            w.reset()
            try:
                harness.play(w, path.stem, steps[:n])
            except harness.ScenarioFailure:
                break  # steps that expect a rejection are not state-changing prefixes
            finally:
                runs = w.client.get(f"/api/cases/{harness.CASE}/runs").json()
            view = w.view()
            sig = (view["state"], view["step"], runs[-1]["status"] if runs else "-")
            seen.setdefault(sig, steps[:n])
    w.restore()
    return seen


def test_every_enabled_action_is_accepted_and_every_blocked_one_rejected(
    world: harness.World,
) -> None:
    states = reachable_states(world)
    assert len(states) >= 5, sorted(states)
    checked = 0
    for sig, steps in sorted(states.items()):
        for role in ROLES:

            def setup(steps: list[dict[str, Any]] = steps, role: str = role) -> dict[str, Any]:
                world.reset()
                harness.play(world, "setup", steps)
                world.switch(role)
                return world.view()

            view = setup()
            for action in view["available_actions"]:
                view = setup()
                body = {**action["payload_defaults"], **USER_INPUTS[action["command"]]}
                resp = world.client.post(
                    f"/api/cases/{harness.CASE}/commands/{action['command']}",
                    json={
                        "idempotency_key": action["idempotency_key"],
                        "expected_case_version": view["case_version"],
                        "payload": body,
                    },
                )
                assert resp.status_code == 200, (sig, role, action["command"], resp.text)
                checked += 1
            view = setup()
            for blocked in view["blocked_actions"]:
                setup()
                resp = world.client.post(
                    f"/api/cases/{harness.CASE}/commands/{blocked['command']}",
                    json={
                        "idempotency_key": "blocked-probe",
                        "expected_case_version": view["case_version"],
                        "payload": PROBE_INPUTS[blocked["command"]],
                    },
                )
                assert resp.status_code == 409, (sig, role, blocked["command"], resp.text)
                assert resp.json()["blocked_reason"] == blocked["blocked_reason"], (sig, role)
                checked += 1
    assert checked > 30
