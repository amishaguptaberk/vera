"""Pure extension seams: command registration, approval gate, event types, labels."""

import dataclasses

import pytest
from vera_domain import commands, enums, labels
from vera_domain.commands import (
    REGISTRY,
    SERVICE_COMMANDS,
    ApprovalBinding,
    ApprovalState,
    CommandSpec,
    NoPayload,
    StepSet,
    approval_gate,
    available_actions,
    reduce_open,
    register_commands,
)
from vera_domain.enums import CaseState, CaseStep, EventType, Role

BINDING = ApprovalBinding("sha256:a", 1, 3, "txn-1")


def spec(name: str, **kw: object) -> CommandSpec:
    return CommandSpec(
        name,
        frozenset({Role.ANALYST}),
        NoPayload,
        StepSet(),
        name + ":{case_id}",
        reduce_open,
        (EventType.CASE_OPENED,),
        "Test action",
        "primary",
        **kw,  # type: ignore[arg-type]
    )


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commands, "REGISTRY", REGISTRY)  # same objects; entries removed below
    yield
    for table in (REGISTRY, SERVICE_COMMANDS):
        for name in [n for n in table if n.startswith("t_")]:
            del table[name]


def test_register_commands_adds_human_and_service_and_rejects_duplicates(clean: None) -> None:
    register_commands("feat", human={"t_h": spec("t_h")}, service={"t_s": svc("t_s")})
    assert "t_h" in REGISTRY and "t_s" in SERVICE_COMMANDS and "t_s" not in REGISTRY
    with pytest.raises(ValueError, match="already registered by feat"):
        register_commands("other", service={"t_h": svc("t_h")})
    with pytest.raises(ValueError, match="already registered"):
        register_commands("other", human={"open_case": spec("open_case")})


def test_existing_service_commands_are_in_the_shared_table() -> None:
    from vera_domain.evidence import SERVICE_REGISTRY

    assert set(SERVICE_REGISTRY) | {"complete_investigation"} <= set(SERVICE_COMMANDS)


def approval(**kw: object) -> ApprovalState:
    base = {**vars(BINDING), "approval_id": "APR-1", "status": "approved"}
    return ApprovalState(**{**base, **kw})  # type: ignore[arg-type]


def test_approval_gate_blocks_missing_unapproved_stale_and_unbound() -> None:
    gated = spec("t_gated", requires_approval=True)
    assert approval_gate(spec("t_open"), None, None) is None
    missing = approval_gate(gated, None, BINDING)
    assert missing is not None and (missing.code, missing.http_status) == ("approval_required", 422)
    assert missing.blocked_reason == "No approval recorded"
    pending = approval_gate(gated, approval(status="requested"), BINDING)
    assert pending is not None and pending.code == "approval_required"
    for changed in (
        approval(status="stale"),
        approval(snapshot_hash="sha256:b"),
        approval(policy_version=2),
        approval(workflow_version=4),
        approval(transaction_id="txn-2"),
    ):
        err = approval_gate(gated, changed, BINDING)
        assert err is not None and (err.code, err.http_status) == ("approval_stale", 409)
    assert approval_gate(gated, approval(), BINDING) is None


def test_available_actions_shows_the_approval_blocked_reason(clean: None) -> None:
    register_commands("feat", human={"t_gated": spec("t_gated", requires_approval=True)})
    args = (Role.ANALYST, CaseState.INVESTIGATING, CaseStep.INTAKE)
    kw = {"case_id": "C", "case_version": 1, "user_id": "u", "next_report_id": "REP-1"}
    _, blocked = available_actions(*args, **kw)  # type: ignore[arg-type]
    assert [(b.command, b.reason) for b in blocked if b.command == "t_gated"] == [
        ("t_gated", "No approval recorded")
    ]
    enabled, _ = available_actions(*args, **kw, approval=approval(), approval_binding=BINDING)  # type: ignore[arg-type]
    assert "t_gated" in {a.command for a in enabled}


def test_event_types_register_once_and_commands_must_declare_registered_events(clean: None) -> None:
    assert {str(m) for m in EventType} <= enums.EVENT_TYPES
    assert {"adapter.succeeded", "adapter.failed", "adapter.uncertain"} <= enums.EVENT_TYPES
    with pytest.raises(ValueError, match="already registered"):
        enums.register_event_types("case.opened")
    with pytest.raises(ValueError, match="subject.verb"):
        enums.register_event_types("nodot")
    bad = CommandSpec(
        "t_bad",
        frozenset({Role.ANALYST}),
        NoPayload,
        StepSet(),
        "k",
        reduce_open,
        ("nope.never",),
        "Bad",
        "ghost",
    )
    with pytest.raises(ValueError, match="unregistered events"):
        register_commands("feat", human={"t_bad": bad})


def test_every_registered_event_type_has_a_summary() -> None:
    assert set(labels.EVENT_SUMMARIES) >= enums.EVENT_TYPES


def test_label_registration_rejects_a_conflicting_entry() -> None:
    labels.register_event_summaries({"case.opened": "Case opened"})  # same value: idempotent
    with pytest.raises(ValueError, match="already registered"):
        labels.register_event_summaries({"case.opened": "Something else"})
    with pytest.raises(ValueError, match="already registered"):
        labels.register_blockers({CaseStep.INTAKE: "Other"})
    with pytest.raises(ValueError, match="already registered"):
        labels.register_wait_kinds({CaseStep.WAITING: "reviewer"})


def svc(name: str, *roles: Role, **kw: object) -> CommandSpec:
    return dataclasses.replace(spec(name, **kw), roles=frozenset(roles or {Role.SYSTEM}))


def test_service_spec_with_a_human_role_is_rejected(clean: None) -> None:
    with pytest.raises(ValueError, match="service command 't_s' lists human role"):
        register_commands("feat", service={"t_s": svc("t_s", Role.SYSTEM, Role.ANALYST)})
    assert "t_s" not in SERVICE_COMMANDS


@pytest.mark.parametrize(
    "role", [Role.SYSTEM, Role.ADAPTER, Role.SPECIALIST, Role.POLICY_CONTROLLER]
)
def test_human_spec_with_a_service_role_is_rejected(clean: None, role: Role) -> None:
    with pytest.raises(ValueError, match="human command 't_h' lists service role"):
        register_commands("feat", human={"t_h": svc("t_h", Role.ANALYST, role)})
    assert "t_h" not in REGISTRY


def test_dual_is_reserved_for_evaluate_policy(clean: None) -> None:
    with pytest.raises(ValueError, match="dual"):
        register_commands("feat", human={"t_h": svc("t_h", Role.ANALYST, Role.SYSTEM, dual=True)})
    policy = REGISTRY["evaluate_policy"]
    assert policy.dual and policy.roles == frozenset({Role.POLICY_CONTROLLER, Role.ANALYST})
    assert "evaluate_policy" not in SERVICE_COMMANDS


def test_every_existing_registration_satisfies_the_role_rule() -> None:
    for name, s in REGISTRY.items():
        assert s.dual or s.roles <= commands.HUMAN_ROLES, name
    for name, s in SERVICE_COMMANDS.items():
        assert not s.roles & commands.HUMAN_ROLES, name
