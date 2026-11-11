from datetime import UTC, datetime

import pytest
from vera_domain.commands import (
    REGISTRY,
    CommandSpec,
    NoPayload,
    ReduceContext,
    StepSet,
    blocked_reason,
    check_role,
    reduce_open,
)
from vera_domain.enums import CaseState, CaseStep, Role
from vera_domain.errors import CommandError
from vera_domain.facts import CaseFacts, Hold, derive_step

NOW = datetime(2026, 11, 10, 17, 8, tzinfo=UTC)


def test_derive_step_is_a_pure_function_of_facts() -> None:
    base = CaseFacts(owner_id="u")
    assert derive_step(base) == (CaseState.REPORTED, CaseStep.INTAKE)
    opened = base.model_copy(update={"opened_at": NOW})
    assert derive_step(opened) == (CaseState.INVESTIGATING, CaseStep.INTAKE)
    hold = Hold(reason="r" * 5, next_owner_id="u", held_by="u", held_at=NOW)
    held = opened.model_copy(update={"hold": hold})
    assert derive_step(held) == (CaseState.HELD, CaseStep.ONHOLD)
    # Clearing the hold re-derives from the facts that were kept, not from a saved result.
    assert derive_step(held.model_copy(update={"hold": None})) == derive_step(opened)
    assert derive_step(base.model_copy(update={"closed": True})) == (
        CaseState.CLOSED,
        CaseStep.CLOSED,
    )


def reduce_registered(name: str) -> tuple[str, ...]:
    """Run a registered command's reducer on its registered test payload and extras."""
    from command_payloads import REDUCER_EXTRAS, TEST_PAYLOADS

    spec = REGISTRY[name]
    if name not in TEST_PAYLOADS:
        pytest.fail(
            f"command '{name}' is registered but has no test payload: call "
            f"register_test_payloads({{'{name}': {{...}}}}) (tests/support/command_payloads.py)"
        )
    payload = spec.payload_model.model_validate(TEST_PAYLOADS[name])
    ctx = ReduceContext("C", "u", "U", Role.ANALYST, NOW, lambda r: (r, r), "REP-1")
    ctx.extra.update(REDUCER_EXTRAS.get(name, {}))
    try:
        red = spec.reducer(CaseFacts(owner_id="u"), payload, ctx)
    except KeyError as missing:
        pytest.fail(
            f"reducer of '{name}' read ctx.extra[{missing}] and found nothing: call "
            f"register_reducer_extras({{'{name}': {{...}}}}) (tests/support/command_payloads.py)"
        )
    return tuple(e.type for e in red.events)


def test_every_reducer_emits_exactly_its_declared_events() -> None:
    for name, spec in list(REGISTRY.items()):
        assert reduce_registered(name) == spec.events, name


def test_reducer_test_fails_loudly_for_a_command_without_payload_or_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from command_payloads import REDUCER_EXTRAS, TEST_PAYLOADS

    monkeypatch.setitem(REGISTRY, "t_unregistered", REGISTRY["open_case"])
    with pytest.raises(pytest.fail.Exception, match="register_test_payloads"):
        reduce_registered("t_unregistered")
    monkeypatch.setitem(REGISTRY, "t_needs_extra", REGISTRY["evaluate_policy"])
    monkeypatch.setitem(TEST_PAYLOADS, "t_needs_extra", {})
    with pytest.raises(pytest.fail.Exception, match="register_reducer_extras"):
        reduce_registered("t_needs_extra")
    monkeypatch.setitem(REDUCER_EXTRAS, "t_needs_extra", REDUCER_EXTRAS["evaluate_policy"])
    assert reduce_registered("t_needs_extra") == ("policy.evaluated",)


def test_closed_and_step_gates_share_one_reason() -> None:
    spec = REGISTRY["hold_case"]
    err = blocked_reason(spec, CaseState.CLOSED, CaseStep.CLOSED)
    assert err is not None and err.code == "case_closed"
    err = blocked_reason(spec, CaseState.HELD, CaseStep.ONHOLD)
    assert err is not None and err.code == "invalid_step" and err.blocked_reason
    assert blocked_reason(spec, CaseState.REPORTED, CaseStep.INTAKE) is None


@pytest.mark.parametrize(
    ("required", "active", "ok"),
    [
        ({Role.REVIEWER}, Role.REVIEWER, True),
        ({Role.REVIEWER}, Role.CARD_ADMIN, False),  # holding both roles never merges them
        ({Role.CARD_ADMIN}, Role.REVIEWER, False),
        ({Role.CARD_ADMIN}, Role.CARD_ADMIN, True),
        ({Role.ANALYST}, Role.OPS_ADMIN, False),
    ],
)
def test_role_stage_checks_only_the_single_role_acted_under(
    required: set[Role], active: Role, ok: bool
) -> None:
    spec = CommandSpec(
        "test_only",
        frozenset(required),
        NoPayload,
        StepSet(),
        "t:{case_id}",
        reduce_open,
        (),
        "T",
        "ghost",
    )
    if ok:
        check_role(spec, active)
    else:
        with pytest.raises(CommandError) as err:
            check_role(spec, active)
        assert err.value.code == "role_forbidden"
