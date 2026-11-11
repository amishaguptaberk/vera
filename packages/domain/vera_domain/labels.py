from vera_domain.enums import CaseState, CaseStep, StateKind

# (state, step) -> (state_label, state_kind, next_action). Grows with later tickets.
_LABELS: dict[tuple[CaseState, CaseStep], tuple[str, StateKind, str]] = {
    (CaseState.REPORTED, CaseStep.INTAKE): (
        "New report",
        StateKind.IDLE,
        "Open the case and start the investigation",
    ),
    (CaseState.INVESTIGATING, CaseStep.INTAKE): (
        "Needs investigation",
        StateKind.WORKING,
        "Start the investigation",
    ),
    (CaseState.HELD, CaseStep.ONHOLD): (
        "On hold",
        StateKind.WAITING,
        "Resume when the next owner is ready",
    ),
}


def describe(state: CaseState, step: CaseStep) -> tuple[str, StateKind, str]:
    found = _LABELS.get((state, step))
    if found:
        return found
    return (state.value.replace("_", " ").capitalize(), StateKind.IDLE, "Review the case")
