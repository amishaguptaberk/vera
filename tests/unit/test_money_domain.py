"""Pure rules of the money commands."""

from vera_domain import money
from vera_domain.enums import CaseState, CaseStep, Role


def test_issue_is_analyst_only_policy_and_approval_gated_with_no_amount_payload() -> None:
    spec = money.ISSUE
    assert spec.roles == frozenset({Role.ANALYST})
    assert spec.requires_approval is True and spec.requires_policy == frozenset({"eligible"})
    assert spec.payload_model.model_fields == {}
    assert spec.allowed_steps.allows(CaseState.CREDIT_APPROVED, CaseStep.ISSUE)
    assert not spec.allowed_steps.allows(CaseState.CREDIT_APPROVED, CaseStep.CREDIT_CHECK)


def test_only_lookup_is_allowed_in_credit_check() -> None:
    allowed = {
        name
        for name, spec in money.HUMAN.items()
        if spec.allowed_steps.allows(CaseState.CREDIT_APPROVED, CaseStep.CREDIT_CHECK)
    }
    assert allowed == {"lookup_execution_result"}


def test_card_admin_commands_and_service_commands_keep_roles_separate() -> None:
    for name in ("approve_card_controls", "decline_card_controls", "apply_card_controls"):
        assert money.HUMAN[name].roles == frozenset({Role.CARD_ADMIN})
    human = {Role.ANALYST, Role.REVIEWER, Role.CARD_ADMIN, Role.OPS_ADMIN, Role.CARDHOLDER}
    for spec in money.SERVICE.values():
        assert not spec.roles & human
    for spec in money.HUMAN.values():
        assert spec.roles <= human


def test_track_commands_are_accepted_on_every_track_step_and_nowhere_after() -> None:
    for name in ("prepare_dispute_packet", "propose_card_controls", "apply_card_controls"):
        steps = money.HUMAN[name].allowed_steps
        assert steps.allows(CaseState.CREDIT_ISSUED, CaseStep.CONTROLS)
        assert steps.allows(CaseState.DISPUTE_PREPARED, CaseStep.DSP_REVIEW)
        assert steps.allows(CaseState.CREDIT_ISSUED, CaseStep.WAITCTL)
        assert not steps.allows(CaseState.REMEDIATION_PENDING, CaseStep.FINALPREP)
        assert not steps.allows(CaseState.CLOSED, CaseStep.CLOSED)
