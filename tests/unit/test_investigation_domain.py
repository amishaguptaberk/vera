"""VER-003B domain: derive_step for investigation facts, recovery actions, specialist schemas."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from vera_domain.commands import FailedStep, available_actions, recovery_actions
from vera_domain.enums import CaseState, CaseStep, Role
from vera_domain.facts import CaseFacts, Hold, derive_step
from vera_domain.investigation import INVESTIGATION_V3, PERMITTED_KINDS, RelatedOutput, build_spec

T = datetime(2026, 11, 10, 17, tzinfo=UTC)
OPEN = CaseFacts(owner_id="u", opened_at=T)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("none", (CaseState.INVESTIGATING, CaseStep.INTAKE)),
        ("running", (CaseState.INVESTIGATING, CaseStep.WORKING)),
        ("failed", (CaseState.INVESTIGATING, CaseStep.WORKING)),
        ("succeeded", (CaseState.INVESTIGATING, CaseStep.DRAFT)),
    ],
)
def test_derive_step_follows_the_investigation_run(
    status: str, expected: tuple[CaseState, CaseStep]
) -> None:
    assert derive_step(OPEN.model_copy(update={"investigation_run_status": status})) == expected


def test_hold_and_close_win_over_a_running_investigation() -> None:
    hold = Hold(reason="wait", next_owner_id="u", held_by="u", held_at=T)
    running = OPEN.model_copy(update={"investigation_run_status": "running"})
    assert derive_step(running.model_copy(update={"hold": hold}))[1] == CaseStep.ONHOLD
    assert derive_step(running.model_copy(update={"closed": True}))[1] == CaseStep.CLOSED


def test_failed_step_offers_retry_and_hold_with_resolved_keys() -> None:
    out = recovery_actions(
        Role.ANALYST,
        CaseState.INVESTIGATING,
        CaseStep.WORKING,
        case_id="CHG-1042",
        case_version=7,
        failed_steps=[FailedStep("run_1", "charge_investigator", 1, "live")],
    )
    assert [a.command for a in out] == ["retry_specialist_step", "hold_case"]
    assert out[0].idempotency_key == "retry:run_1:charge_investigator:1"
    assert out[0].payload_defaults == {"step_key": "charge_investigator", "mode": "live"}
    assert out[1].idempotency_key == "hold:CHG-1042:7"
    assert (
        recovery_actions(
            Role.ANALYST,
            CaseState.INVESTIGATING,
            CaseStep.WORKING,
            case_id="CHG-1042",
            case_version=7,
            failed_steps=[],
        )
        == []
    )


def test_start_investigation_is_offered_only_after_open() -> None:
    def names(state: CaseState, step: CaseStep) -> set[str]:
        enabled, _ = available_actions(
            Role.ANALYST,
            state,
            step,
            case_id="CHG-1042",
            case_version=1,
            user_id="u",
            next_report_id="REP-1",
        )
        return {a.command for a in enabled}

    assert "start_investigation" not in names(CaseState.REPORTED, CaseStep.INTAKE)
    assert "start_investigation" in names(CaseState.INVESTIGATING, CaseStep.INTAKE)
    assert "start_investigation" not in names(CaseState.INVESTIGATING, CaseStep.WORKING)


def test_scope_comes_from_record_kinds_and_graph_is_data() -> None:
    kinds = {"CHG-1042": "charge", "PO-219": "purchase_order", "PRF-4418": "cardholder_profile"}
    spec = build_spec("charge_investigator", kinds)
    assert spec.allowed_record_ids("CHG-1042") == frozenset({"CHG-1042", "PO-219"})
    assert {n["key"] for n in INVESTIGATION_V3["nodes"]} == {*PERMITTED_KINDS, "pc1"}


def test_related_charge_on_card_digits_alone_is_rejected() -> None:
    cite = {"record_id": "CHG-1051", "version": 1, "field": "card_last4", "value": "4418"}
    with pytest.raises(ValidationError):
        RelatedOutput.model_validate(
            {
                "findings": [
                    {"kind": "related_charge", "statement": "same card", "citations": [cite]}
                ],
                "related_transaction_ids": ["CHG-1051"],
            }
        )
