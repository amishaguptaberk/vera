"""Evaluator sensitivity: does the suite fail when a safeguard is broken?

Each mutation disables one real safeguard in-process (a test seam, restored after the case),
then re-runs the case that guards it. The mutation is "detected" only if that case FAILS. A
suite that still passes with a gate removed would be measuring nothing; this is the check that
it is not.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evals.harness import World

# (name, what it breaks, case that must catch it, module, attribute, replacement)
MUTATIONS: list[tuple[str, str, str, str, str, Callable[..., Any]]] = [
    (
        "role check removed",
        "the gateway no longer checks the active role against the command (stage 1)",
        "EC-35",
        "gateway",
        "check_role",
        lambda spec, role: None,
    ),
    (
        "policy gate removed",
        "commands that need an eligible policy result run without one (stage 7)",
        "EC-28",
        "gateway",
        "policy_gate",
        lambda spec, current: None,
    ),
    (
        "idempotent replay removed",
        "a repeated idempotency key is processed again instead of replayed (stage 3)",
        "EC-41",
        "gateway",
        "find_key",
        lambda *a, **k: None,
    ),
    (
        "grounding validator removed",
        "specialist findings are stored without checking their cited values",
        "EC-23",
        "runner",
        "validate_grounding",
        lambda findings, read: [],
    ),
]


def run(w: World) -> dict[str, Any]:
    from evals import cases

    by_id = {c["id"]: (p, c) for p, c in cases.load_cases()}
    rows = []
    for name, breaks, case_id, module, attr, repl in MUTATIONS:
        path, case = by_id[case_id]

        def prepare(
            world: World, module: str = module, attr: str = attr, repl: Callable[..., Any] = repl
        ) -> None:
            world.patch(attr, repl, module=module)

        try:
            res = cases.run_case(w, path, case, prepare=prepare)
            detected = res.status == "FAIL"
            caught = sorted({c.evaluator for c in res.checks if not c.passed})[:4]
        except Exception as exc:  # a crash under mutation also means the defect surfaced
            detected, caught = True, [f"crash: {type(exc).__name__}"]
        rows.append(
            {
                "mutation": name,
                "breaks": breaks,
                "case": case_id,
                "detected": detected,
                "caught_by": caught,
            }
        )
    return {
        "status": "ran",
        "detected": sum(r["detected"] for r in rows),
        "total": len(rows),
        "mutations": rows,
    }
