"""Decisions domain: Ask Vera intents and the policy statuses each decision needs."""

import pytest
from vera_domain.decisions import COMMANDS, DECISION_POLICY, ask_intent
from vera_domain.enums import Role


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("Approve it", "approve"),
        ("please approve this packet", "approve"),
        ("Why is credit blocked?", "credit_blocked"),
        ("issue the credit", "issue_credit"),
        ("Is the approval stale?", "stale"),
        ("Who do I call?", "contact"),
        ("Phone on file", "phone"),
        ("Can we close?", "can_close"),
        ("What is the weather?", "unknown"),
    ],
)
def test_ask_intent(question: str, intent: str) -> None:
    assert ask_intent(question) == intent


def test_credit_needs_eligible_and_only_the_reviewer_approves() -> None:
    assert DECISION_POLICY["credit"] == frozenset({"eligible"})
    by_name = {c.name: c for c in COMMANDS}
    assert by_name["approve_decision"].roles == frozenset({Role.REVIEWER})
    assert by_name["return_decision"].roles == frozenset({Role.REVIEWER})
    assert Role.REVIEWER not in by_name["request_reviewer_approval"].roles
    assert not any(c.requires_approval for c in COMMANDS)
