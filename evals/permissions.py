"""Permission matrix: every registered command, under every human role that does not hold it.

For each (command, role) pair the command is posted as that role on a freshly seeded CHG-1042.
It must not be offered, must be refused with role_forbidden, and must write nothing. Service
commands (specialist, system, Policy Controller) are probed under every human role. This is
the per-command permission coverage; the cases add role probes at the states where they matter
(e.g. a reviewer acting on card controls while the plan awaits a card admin).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evals.harness import World

HUMAN_ROLES = ("analyst", "ops_admin", "reviewer", "card_admin", "cardholder")


def run(w: World) -> dict[str, Any]:
    from vera_domain.commands import REGISTRY, SERVICE_COMMANDS
    from vera_domain.enums import Role

    from evals.harness import do_probe

    w.reset()
    rows = []
    try:
        for name, spec in sorted({**REGISTRY, **SERVICE_COMMANDS}.items()):
            for role in HUMAN_ROLES:
                if Role(role) in spec.roles:
                    continue
                res = do_probe(
                    w,
                    {"as": role, "command": name, "expect_code": "role_forbidden"},
                    f"[permission-matrix] {name} as {role}",
                    where="matrix",
                )
                rows.append(
                    {
                        "command": name,
                        "role": role,
                        "service": name in SERVICE_COMMANDS,
                        "passed": res["passed"],
                        "http": res["http"],
                        "code": res["code"],
                    }
                )
    finally:
        w.probes = []
        w.trace = []
        w.restore()
    failures = [r for r in rows if not r["passed"]]
    return {
        "status": "ran",
        "commands": len({r["command"] for r in rows}),
        "pairs": len(rows),
        "refused": len(rows) - len(failures),
        "failures": failures,
    }
