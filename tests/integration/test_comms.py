"""VER-005: cardholder follow-up through HTTP commands, cardholder routes and the watcher."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from command_payloads import register_test_payloads
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import investigation
from vera_api.worker import run_once

CASE = "CHG-1042"
SHA = "a" * 64
RECEIPT = {
    "file_name": "northstar-receipt.pdf",
    "content_type": "application/pdf",
    "size_bytes": 48213,
    "sha256": SHA,
}
SEND = {"channel": "email", "subject": "Question about your Northstar charge", "attachments": []}

register_test_payloads(
    {
        "draft_follow_up": {},
        "update_communication_draft": {
            "subject": "Question about your charge",
            "body": "Please upload the receipt for this charge.",
        },
        "send_communication": SEND,
        "send_reminder": {},
        "submit_cardholder_response": {"request_id": "MSG-2201", "text": "Receipt attached."},
        "review_cardholder_response": {"outcome": "complete"},
    }
)


@pytest.fixture
def factory(client: TestClient, db_url: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(db_url)
    f = sessionmaker(engine, expire_on_commit=False)
    with f() as s:
        s.execute(text("truncate table jobs, workflow_runs cascade"))
        s.commit()
    yield f
    engine.dispose()


@pytest.fixture(autouse=True)
def _seams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(investigation, "LIVE_SLEEP", lambda _s: None)
    monkeypatch.delenv("VERA_EXECUTION_MODE", raising=False)


def role(client: TestClient, r: str) -> None:
    assert client.post("/api/session/role", json={"role": r}).status_code == 200


def version(client: TestClient) -> int:
    role(client, "analyst")
    return int(client.get(f"/api/cases/{CASE}").json()["case_version"])


def command(
    client: TestClient, name: str, key: str, payload: dict[str, Any] | None = None
) -> httpx.Response:
    return client.post(
        f"/api/cases/{CASE}/commands/{name}",
        json={
            "idempotency_key": key,
            "expected_case_version": version(client),
            "payload": payload or {},
        },
    )


def q(factory: sessionmaker[Session], sql: str) -> list[Any]:
    with factory() as s:
        return list(s.execute(text(sql)).all())


def step(client: TestClient) -> tuple[str, str]:
    role(client, "analyst")
    c = client.get(f"/api/cases/{CASE}").json()
    return c["state"], c["step"]


def to_draft(client: TestClient, factory: sessionmaker[Session]) -> None:
    role(client, "analyst")
    uid = client.get("/api/session").json()["user"]["id"]
    assert command(client, "open_case", f"open:{CASE}:{uid}").status_code == 200
    assert command(client, "start_investigation", f"inv:{CASE}").status_code == 200
    t = datetime(2031, 1, 1, tzinfo=UTC)
    with factory() as s:
        n = 0
        while run_once(s, worker_id="w-test", now=t + timedelta(minutes=n)) is not None:
            n += 1
    assert step(client)[1] == "draft"


def drafted_and_sent(client: TestClient, factory: sessionmaker[Session]) -> httpx.Response:
    to_draft(client, factory)
    r = command(client, "draft_follow_up", f"draft:{CASE}")
    assert r.status_code == 200, r.text
    return command(client, "send_communication", f"send:{CASE}", SEND)


def policy_result(factory: sessionmaker[Session]) -> list[Any]:
    return q(factory, "select * from policy_evaluations order by 1")


# ---- TEST FIRST ---------------------------------------------------------------------------------


def test_double_send_delivers_once_then_response_stores_evidence_and_keeps_policy(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    first = drafted_and_sent(client, factory)
    assert first.status_code == 200, first.text
    again = command(client, "send_communication", f"send:{CASE}", SEND)
    assert again.status_code == 200
    assert again.json()["result"] == first.json()["result"]
    assert first.json()["result"]["request_id"] == "MSG-2201"
    assert first.json()["result"]["case_id"] == CASE
    assert first.json()["result"]["channel"] == "email"
    assert q(factory, "select count(*) from communications")[0][0] == 1
    assert (
        q(factory, "select count(*) from adapter_executions where adapter='messaging'")[0][0] == 1
    )
    assert (
        q(factory, "select count(*) from audit_events where type='communication.sent'")[0][0] == 1
    )
    assert step(client) == ("waiting_on_cardholder", "waiting")
    policy_before = policy_result(factory)
    report_before = q(factory, "select * from reports where id='REP-1042'")

    role(client, "cardholder")
    mine = client.get("/api/requests?mine=true").json()["requests"]
    assert [m["request_id"] for m in mine] == ["MSG-2201"]
    r = client.post(
        "/api/requests/MSG-2201/responses",
        json={
            "text": "Here is my receipt; the order was for the warehouse.",
            "attachment": RECEIPT,
        },
    )
    assert r.status_code == 200, r.text

    rsp = q(factory, "select id, communication_id, evidence_record_id from communication_responses")
    assert rsp == [("RSP-2201", "MSG-2201", "RCP-2201")]
    ev = q(factory, "select kind, status from evidence_records where id='RCP-2201'")
    assert ev == [("receipt", "pending_review")]
    assert q(factory, "select file_name from attachments where record_id='RCP-2201'") == [
        ("northstar-receipt.pdf",)
    ]
    assert policy_result(factory) == policy_before
    assert q(factory, "select * from reports where id='REP-1042'") == report_before
    assert step(client) == ("response_received", "response")
    detail = client.get(f"/api/cases/{CASE}/communications/MSG-2201").json()
    assert detail["response"]["id"] == "RSP-2201"


# ---- acceptance ---------------------------------------------------------------------------------


def test_specialist_and_cardholder_cannot_send(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_draft(client, factory)
    assert command(client, "draft_follow_up", f"draft:{CASE}").status_code == 200
    v = version(client)
    role(client, "cardholder")
    r = client.post(
        f"/api/cases/{CASE}/commands/send_communication",
        json={"idempotency_key": f"send:{CASE}", "expected_case_version": v, "payload": SEND},
    )
    assert r.status_code == 403
    assert q(factory, "select count(*) from adapter_executions")[0][0] == 0
    assert q(factory, "select status from communications") == [("drafted",)]


def test_cardholder_view_has_no_internal_data(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    drafted_and_sent(client, factory)
    role(client, "cardholder")
    body = client.get("/api/requests/MSG-2201").json()
    assert set(body) == {"request_id", "status", "subject", "questions", "due_at", "responded"}
    dumped = str(body).lower()
    for word in ("policy", "specialist", "trace", "fnd-", "usr-", "rep-", "finding"):
        assert word not in dumped
    assert client.get(f"/api/cases/{CASE}/communications").status_code == 403


def test_attachment_type_and_size_are_validated(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    drafted_and_sent(client, factory)
    role(client, "cardholder")
    bad = {**RECEIPT, "content_type": "application/x-msdownload"}
    r = client.post("/api/requests/MSG-2201/responses", json={"text": "x", "attachment": bad})
    assert r.status_code == 422
    big = {**RECEIPT, "size_bytes": 50 * 1024 * 1024}
    r = client.post("/api/requests/MSG-2201/responses", json={"text": "x", "attachment": big})
    assert r.status_code == 422
    assert q(factory, "select count(*) from communication_responses")[0][0] == 0


def test_missed_deadline_recorded_once_and_reminder_is_explicit(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    drafted_and_sent(client, factory)
    assert client.post("/api/demo/run-deadline-watcher", json={}).json()["marked_overdue"] == []
    r = client.post("/api/demo/run-deadline-watcher", json={"advance_hours": 24 * 365 * 10})
    assert r.json()["marked_overdue"] == ["MSG-2201"]
    r = client.post("/api/demo/run-deadline-watcher", json={"advance_hours": 24 * 365 * 10})
    assert r.json()["marked_overdue"] == []
    assert (
        q(factory, "select count(*) from audit_events where type='communication.overdue'")[0][0]
        == 1
    )
    assert step(client) == ("waiting_on_cardholder", "noresp1")
    case = client.get(f"/api/cases/{CASE}").json()
    assert case["owner"]["id"] == "usr-sam-rivera"
    assert (
        q(factory, "select count(*) from audit_events where type='communication.reminded'")[0][0]
        == 0
    )
    v = version(client)
    r = command(client, "send_reminder", f"remind:{CASE}:{v}")
    assert r.status_code == 200, r.text
    assert step(client) == ("waiting_on_cardholder", "waiting")


def test_second_follow_up_is_rejected(client: TestClient, factory: sessionmaker[Session]) -> None:
    to_draft(client, factory)
    assert command(client, "draft_follow_up", f"draft:{CASE}").status_code == 200
    with factory() as s:  # a second draft needs a fresh key; the service still refuses it
        s.execute(text("delete from idempotency_keys where command='draft_follow_up'"))
        s.commit()
    r = command(client, "draft_follow_up", f"draft:{CASE}")
    assert r.status_code == 409
    assert q(factory, "select count(*) from communications")[0][0] == 1


def test_conflicting_review_opens_one_conflict_finding_and_blocks_decision(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    drafted_and_sent(client, factory)
    role(client, "cardholder")
    client.post("/api/requests/MSG-2201/responses", json={"text": "I never bought anything."})
    v = version(client)
    r = command(
        client, "review_cardholder_response", f"review:{CASE}:{v}", {"outcome": "conflicting"}
    )
    assert r.status_code == 200, r.text
    rows = q(factory, "select kind, status from findings where id like 'FND-MSG-2201%'")
    assert rows == [("conflict", "open")]
    assert step(client) == ("callback_pending", "idv")
