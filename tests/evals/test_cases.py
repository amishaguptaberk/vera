"""Every evaluation case under tests/fixtures/eval_cases, replayed against Postgres in REPLAY.

A case passes only if every declared expectation and every global invariant holds. The
sensitivity test then breaks one safeguard at a time and requires the guarding case to fail.
"""

from collections.abc import Iterator

import pytest

from evals import cases, harness, sensitivity


@pytest.fixture(scope="module")
def eval_world() -> Iterator[harness.World]:
    with harness.world() as w:
        yield w


CASES = cases.load_cases()


@pytest.mark.parametrize(("path", "case"), CASES, ids=[c["id"] for _, c in CASES])
def test_case(eval_world: harness.World, path: object, case: dict[str, object]) -> None:
    result = cases.run_case(eval_world, path, case)  # type: ignore[arg-type]
    failed = [f"{c.evaluator}: {c.detail}" for c in result.checks if not c.passed]
    assert result.status == "PASS", "\n".join(failed)


def test_each_injected_defect_makes_its_guarding_case_fail(eval_world: harness.World) -> None:
    out = sensitivity.run(eval_world)
    missed = [m["mutation"] for m in out["mutations"] if not m["detected"]]
    assert not missed, f"the suite still passed with these safeguards removed: {missed}"


def test_every_command_refuses_every_role_that_does_not_hold_it(
    eval_world: harness.World,
) -> None:
    from evals import permissions

    out = permissions.run(eval_world)
    assert out["pairs"] > 200
    assert out["failures"] == [], out["failures"][:5]
