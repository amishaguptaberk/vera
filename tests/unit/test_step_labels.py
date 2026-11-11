"""Every step the case can reach has its own state label and next action (no generic fallback)."""

import vera_api.gateway  # noqa: F401  (loads every feature's labels)
from vera_domain.enums import CaseState, CaseStep
from vera_domain.labels import describe

_C, _D = CaseState.CREDIT_ISSUED, CaseState.DISPUTE_PREPARED
REACHABLE = [
    (CaseState.CALLBACK_PENDING, CaseStep.IDV),
    (CaseState.CREDIT_APPROVED, CaseStep.CREDIT_CHECK),
    *[(s, st) for s in (_C, _D) for st in (CaseStep.CONTROLS, CaseStep.CTL_PREP)],
    *[(s, st) for s in (_C, _D) for st in (CaseStep.WAITCTL, CaseStep.CTL_APPLY)],
    *[
        (_D, st)
        for st in (
            CaseStep.DSP_PREPARE,
            CaseStep.DSP_OPEN,
            CaseStep.DSP_REVIEW,
            CaseStep.DSP_SUBMIT,
            CaseStep.DSP_FAILED,
        )
    ],
]


def test_reachable_steps_have_specific_labels() -> None:
    for state, step in REACHABLE:
        label, _kind, next_action = describe(state, step)
        assert next_action != "Review the case", (state, step)


def test_identity_and_dispute_copy() -> None:
    assert describe(CaseState.CALLBACK_PENDING, CaseStep.IDV)[0] == "Identity check needed"
    assert describe(_D, CaseStep.DSP_PREPARE)[2] == "Prepare the dispute packet"
    assert describe(_C, CaseStep.WAITCTL)[0] == "Waiting on card admin"
