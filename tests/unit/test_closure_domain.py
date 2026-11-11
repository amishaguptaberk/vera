"""VER-011 domain: deterministic final message and the recorded-actions content policy."""

from vera_domain.closure import content_violations, render_final_message
from vera_domain.facts import CaseFacts

NOTHING = CaseFacts(owner_id="u", decision="clear")
ALL = CaseFacts(
    owner_id="u",
    decision="credit",
    credit_status="issued",
    dispute_status="submitted",
    controls_status="applied",
)


def test_render_is_deterministic_and_passes_its_own_policy() -> None:
    for facts in (NOTHING, ALL):
        body = render_final_message(facts, cardholder_name="Priya Shah", case_id="CHG-1042")
        assert body == render_final_message(facts, cardholder_name="Priya Shah", case_id="CHG-1042")
        assert content_violations(body, facts) == []
    assert "No credit has been issued" in render_final_message(
        NOTHING, cardholder_name="P", case_id="C"
    )


def test_policy_rejects_unrecorded_actions_and_allows_recorded_ones() -> None:
    claims = [
        ("A temporary credit has been issued to your account.", "credit_issued"),
        ("We have submitted a dispute with the merchant.", "dispute_submitted"),
        ("Your card has been locked.", "controls_applied"),
    ]
    for sentence, claim in claims:
        assert content_violations(sentence, NOTHING) == [{"claim": claim, "sentence": sentence}]
        assert content_violations(sentence, ALL) == []


def test_negated_statements_are_not_claims() -> None:
    assert content_violations("No credit has been issued.", NOTHING) == []
    assert content_violations("We have not submitted a dispute.", NOTHING) == []
