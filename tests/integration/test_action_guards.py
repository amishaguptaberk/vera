"""Case-view actions as the gateway judges them: feature record guards and payload defaults.

An action the case view offers must be accepted when posted as offered (its idempotency key and
payload_defaults echoed), and one it lists as blocked must be refused 409 with the same reason.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from vera_api import investigation
from vera_api.worker import run_once

CASE = "CHG-1042"


@pytest.fixture
def factory(client: TestClient, db_url: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(db_url)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture(autouse=True)
def _replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(investigation, "LIVE_SLEEP", lambda _s: None)
    monkeypatch.setenv("VERA_EXECUTION_MODE", "replay")


def as_role(client: TestClient, role: str) -> dict[str, Any]:
    assert client.post("/api/session/role", json={"role": role}).status_code == 200
    return client.get(f"/api/cases/{CASE}").json()  # type: ignore[no-any-return]


def act(client: TestClient, role: str, name: str, payload: dict[str, Any] | None = None) -> Any:
    """Post the offered action exactly as the case view advertises it."""
    view = as_role(client, role)
    action = next(a for a in view["available_actions"] if a["command"] == name)
    return client.post(
        f"/api/cases/{CASE}/commands/{name}",
        json={
            "idempotency_key": action["idempotency_key"],
            "expected_case_version": view["case_version"],
            "payload": {**action["payload_defaults"], **(payload or {})},
        },
    )


def probe(client: TestClient, name: str, payload: dict[str, Any]) -> httpx.Response:
    view = client.get(f"/api/cases/{CASE}").json()
    return client.post(
        f"/api/cases/{CASE}/commands/{name}",
        json={
            "idempotency_key": "probe",
            "expected_case_version": view["case_version"],
            "payload": payload,
        },
    )


def drain(factory: sessionmaker[Session]) -> None:
    t = datetime(2031, 1, 1, tzinfo=UTC)
    with factory() as s:
        n = 0
        while run_once(s, worker_id="w-test", now=t + timedelta(minutes=n)) is not None:
            n += 1
            assert n < 20


def investigated(client: TestClient, factory: sessionmaker[Session]) -> None:
    assert act(client, "analyst", "open_case").status_code == 200
    assert act(client, "analyst", "start_investigation").status_code == 200
    drain(factory)


def test_edit_and_send_are_blocked_until_a_draft_exists_and_refused_with_that_reason(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    investigated(client, factory)
    view = as_role(client, "analyst")
    assert view["step"] == "draft"
    offered = {a["command"] for a in view["available_actions"]}
    blocked = {b["command"]: b["blocked_reason"] for b in view["blocked_actions"]}
    assert "draft_follow_up" in offered
    assert blocked["update_communication_draft"] == "No follow-up draft yet."
    assert blocked["send_communication"] == "No follow-up draft yet."
    resp = probe(client, "update_communication_draft", {"subject": "Hello", "body": "A question"})
    assert resp.status_code == 409
    assert resp.json()["blocked_reason"] == "No follow-up draft yet."

    assert act(client, "analyst", "draft_follow_up").status_code == 200
    drain(factory)
    view = as_role(client, "analyst")
    offered = {a["command"] for a in view["available_actions"]}
    assert {"update_communication_draft", "send_communication"} <= offered
    assert "draft_follow_up" not in offered


def test_feature_keys_and_defaults_are_resolved_on_the_offered_action(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    investigated(client, factory)
    assert act(client, "analyst", "draft_follow_up").status_code == 200
    drain(factory)
    sent = act(client, "analyst", "send_communication", {"subject": "About your charge"})
    assert sent.status_code == 200, sent.text
    request_id = sent.json()["result"]["request_id"]
    view = as_role(client, "cardholder")
    respond = next(
        a for a in view["available_actions"] if a["command"] == "submit_cardholder_response"
    )
    assert respond["payload_defaults"] == {"request_id": request_id}
    assert respond["idempotency_key"] == f"respond:{request_id}"
    for action in view["available_actions"]:
        assert "{" not in action["idempotency_key"], action
    resp = act(client, "cardholder", "submit_cardholder_response", {"text": "Receipt attached."})
    assert resp.status_code == 200, resp.text


RETRIES = {"retry_follow_up_draft", "retry_decision_packet", "retry_dispute_narrative"}


def test_a_retry_is_listed_only_when_something_failed(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    investigated(client, factory)
    assert act(client, "analyst", "draft_follow_up").status_code == 200
    drain(factory)
    view = as_role(client, "analyst")
    listed = {a["command"] for a in view["available_actions"]}
    listed |= {b["command"] for b in view["blocked_actions"]}
    listed |= {a["command"] for a in view["recovery_actions"]}
    assert listed.isdisjoint(RETRIES), listed & RETRIES
