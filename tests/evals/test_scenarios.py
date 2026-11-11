"""Every scenario under evals/scenarios, replayed; pending ones are skipped with their reason."""

from collections.abc import Iterator

import pytest

from evals import harness


@pytest.fixture(scope="module")
def eval_world() -> Iterator[harness.World]:
    with harness.world() as w:
        yield w


SCENARIOS = harness.load_scenarios()


@pytest.mark.parametrize(("path", "scenario"), SCENARIOS, ids=[p.stem for p, _ in SCENARIOS])
def test_scenario(eval_world: harness.World, path: object, scenario: dict[str, object]) -> None:
    result = harness.run_scenario(eval_world, path, scenario)  # type: ignore[arg-type]
    if result.status == "SKIPPED":
        pytest.skip(result.detail)
    assert result.status == "PASS", result.detail
