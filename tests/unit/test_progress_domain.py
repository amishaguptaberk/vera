"""Progress steps (display only) and the event summary label table."""

from vera_domain.enums import CaseStep, EventType, RunEventType
from vera_domain.labels import EVENT_SUMMARIES, event_summary
from vera_domain.progress import progress_steps

KEYS = [
    "report_received",
    "investigate",
    "request_info",
    "review_response",
    "verify",
    "prepare_decision",
    "reviewer_decision",
    "credit_dispute",
    "card_controls",
    "final_followup",
    "close_or_monitor",
]


def statuses(steps: list) -> list[str]:  # type: ignore[type-arg]
    return [s.status for s in steps]


def test_intake_is_investigate_current_report_done_rest_upcoming() -> None:
    steps = progress_steps(CaseStep.INTAKE)
    assert [s.key for s in steps] == KEYS
    assert steps[0].label == "Report received"
    assert steps[1].label == "Investigate"
    assert statuses(steps) == ["done", "current"] + ["upcoming"] * 9


def test_reviewer_wait_is_step_seven() -> None:
    steps = progress_steps(CaseStep.WAITRV)
    assert statuses(steps) == ["done"] * 6 + ["current"] + ["upcoming"] * 4


def test_held_case_blocks_the_step_it_was_held_on() -> None:
    steps = progress_steps(CaseStep.ONHOLD, held_step=CaseStep.INTAKE)
    assert statuses(steps) == ["done", "blocked"] + ["upcoming"] * 9


def test_failed_run_blocks_the_current_step() -> None:
    steps = progress_steps(CaseStep.RESPONSE, run_failed=True)
    assert statuses(steps) == ["done"] * 3 + ["blocked"] + ["upcoming"] * 7


def test_closed_case_has_every_step_done() -> None:
    assert statuses(progress_steps(CaseStep.CLOSED)) == ["done"] * 11


def test_every_case_step_maps_to_a_position() -> None:
    for step in CaseStep:
        steps = progress_steps(step, held_step=CaseStep.INTAKE)
        assert len(steps) == 11


def test_every_event_type_has_a_summary_label() -> None:
    for member in [*EventType, *RunEventType]:
        assert member.value in EVENT_SUMMARIES, member
        assert EVENT_SUMMARIES[member.value]


def test_event_summary_examples_and_fallback() -> None:
    assert event_summary("case.held") == "Case put on hold"
    assert event_summary("case.opened") == "Case opened"
    # An event type without a table entry still gets a readable sentence.
    assert event_summary("callback.scheduled") == "Callback scheduled"
