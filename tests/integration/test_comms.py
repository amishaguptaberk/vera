"""Cardholder follow-up through HTTP commands, cardholder routes and the watcher."""

import json
import re
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import comms, investigation
from vera_api.worker import run_once

CASE = "CHG-1042"
REC = Path("evals/recordings")
SHA = "a" * 64
RECEIPT = {
    "file_name": "northstar-receipt.pdf",
    "content_type": "application/pdf",
    "size_bytes": 48213,
    "sha256": SHA,
}
REPLY = "Attached is the Northstar receipt. I placed this order for the warehouse myself."
SEND = {"channel": "email", "subject": "Question about your Northstar charge", "attachments": []}


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
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", REC)
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


def drain(factory: sessionmaker[Session]) -> None:
    t = datetime(2031, 1, 1, tzinfo=UTC)
    with factory() as s:
        n = 0
        while run_once(s, worker_id="w-test", now=t + timedelta(minutes=n)) is not None:
            n += 1
            assert n < 20


def draft(client: TestClient, factory: sessionmaker[Session]) -> None:
    r = command(client, "draft_follow_up", f"draft:{CASE}")
    assert r.status_code == 200, r.text
    drain(factory)
    assert step(client) == ("investigating", "draft")


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
    draft(client, factory)
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
    assert [(m["request_id"], m["case_id"]) for m in mine] == [("MSG-2201", CASE)]
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
    draft(client, factory)
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
    # case_id names the cardholder's own case (whose view offers them their verification step).
    assert set(body) == {
        "request_id",
        "case_id",
        "status",
        "subject",
        "questions",
        "due_at",
        "responded",
    }
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
    assert r.json()["marked_overdue"] == [CASE]
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
    draft(client, factory)
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
    client.post("/api/requests/MSG-2201/responses", json={"text": REPLY})
    v = version(client)
    r = command(
        client, "review_cardholder_response", f"review:{CASE}:{v}", {"outcome": "conflicting"}
    )
    assert r.status_code == 200, r.text
    rows = q(factory, "select kind, status from findings where id like 'FND-MSG-2201%'")
    assert rows == [("conflict", "open")]
    assert step(client) == ("callback_pending", "idv")


# ---- specialists --------------------------------------------------------------------------------


def test_follow_up_specialist_drafts_only_unresolved_questions_and_never_sends(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_draft(client, factory)
    draft(client, factory)
    detail = client.get(f"/api/cases/{CASE}/communications/MSG-2201").json()
    assert detail["status"] == "drafted"
    assert detail["questions"] == [
        "Please upload the receipt or invoice for this $2,840.00 charge.",
        "Can you tell us more about this charge: did you or someone on your team place this order?",
    ]
    assert detail["draft_versions"] == 1
    assert q(factory, "select count(*) from adapter_executions")[0][0] == 0
    step_row = q(
        factory,
        "select status, execution_mode from workflow_steps where step_key='cardholder_follow_up'",
    )
    assert step_row == [("succeeded", "replay")]


def test_follow_up_question_on_a_supported_item_fails_then_retry_recovers(
    client: TestClient, factory: sessionmaker[Session], tmp_path: Path
) -> None:
    root = tmp_path / "rec"
    shutil.copytree(REC, root)
    d = root / "cardholder_follow_up" / "v1"
    good = json.loads((d / "CHG-1042.1.json").read_text())
    bad = json.loads(json.dumps(good))
    bad["content"]["questions"][0]["resolves"] = {
        "record_id": "PO-219",
        "version": 1,
        "field": "approved_amount_cents",
        "value": 284000,
    }
    for n in (1, 2, 3):  # first answer + two validation retries all cite a supported record
        (d / f"CHG-1042.{n}.json").write_text(json.dumps(bad))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(investigation, "RECORDINGS_ROOT", root)
        to_draft(client, factory)
        assert command(client, "draft_follow_up", f"draft:{CASE}").status_code == 200
        drain(factory)
        assert step(client) == ("investigating", "working")
        assert q(factory, "select count(*) from communications")[0][0] == 0
        failed = q(
            factory,
            "select status, failure_reason from workflow_steps "
            "where step_key='cardholder_follow_up'",
        )
        assert failed == [("failed", "ungrounded")]
        actions = client.get(f"/api/cases/{CASE}").json()["available_actions"]
        assert "retry_follow_up_draft" in [a["command"] for a in actions]
        mp.setattr(investigation, "RECORDINGS_ROOT", REC)
        run_id = q(factory, "select id from workflow_runs where id like 'run_fu_%'")[0][0]
        r = command(
            client,
            "retry_follow_up_draft",
            f"retry-draft:{CASE}:{run_id}:replay",
            {"mode": "replay"},
        )
        assert r.status_code == 200, r.text
        drain(factory)
    assert step(client) == ("investigating", "draft")


def test_live_follow_up_uses_the_provider_through_mock_transport(
    client: TestClient, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    turns = [
        json.loads((REC / "cardholder_follow_up" / "v1" / f).read_text())
        for f in ("CHG-1042.json", "CHG-1042.1.json")
    ]
    seen: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "Cardholder Follow-up" not in body["messages"][0]["content"]:
            return httpx.Response(500)
        turn = turns[min(len(seen), 1)]
        seen.append(1)
        message: dict[str, Any] = {"role": "assistant", "content": json.dumps(turn["content"])}
        if turn["tool_calls"]:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                    }
                    for tc in turn["tool_calls"]
                ],
            }
        return httpx.Response(
            200, json={"model": "stub-model-1", "choices": [{"message": message}], "usage": {}}
        )

    to_draft(client, factory)
    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setattr(investigation, "LIVE_TRANSPORT", httpx.MockTransport(handle))
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    draft(client, factory)
    assert len(seen) == 2
    rows = q(
        factory,
        "select execution_mode from workflow_steps where step_key='cardholder_follow_up'",
    )
    assert rows == [("live",)]


def test_response_reviewer_recommends_conflicting_but_analyst_decides(
    client: TestClient, factory: sessionmaker[Session], tmp_path: Path
) -> None:
    drafted_and_sent(client, factory)
    conflicts = q(factory, "select count(*) from findings where kind='conflict'")[0][0]
    role(client, "cardholder")
    assert client.post("/api/requests/MSG-2201/responses", json={"text": REPLY}).status_code == 200
    drain(factory)
    rec = q(factory, "select review_recommendation, response_review from communications")
    assert rec[0][0]["classification"] == "conflicting"
    assert rec[0][1] == "none"
    assert step(client) == ("response_received", "response")
    with factory() as s:  # the committed request files match what the specialists are sent
        for path in comms.dump_requests(s, CASE, tmp_path):
            rel = path.relative_to(tmp_path)

            def norm(t: str) -> str:  # finding ids carry the random investigation run id
                return re.sub(r"run_[0-9a-f]{6,}", "run_ID", t)

            assert norm(path.read_text()) == norm((Path("evals/requests") / rel).read_text()), rel
    # a recommendation only: the reviewer opens no finding; the analyst's review decides
    assert q(factory, "select count(*) from findings where kind='conflict'")[0][0] == conflicts
    v = version(client)
    r = command(client, "review_cardholder_response", f"review:{CASE}:{v}", {"outcome": "complete"})
    assert r.status_code == 200, r.text
    rec = q(factory, "select review_recommendation, response_review from communications")
    assert (rec[0][0]["classification"], rec[0][1]) == ("conflicting", "complete")


OTHER_REPLY = "Yes, that was me. I ordered two units; the receipt is attached."


def _suggestion(client: TestClient) -> dict[str, Any]:
    role(client, "analyst")
    detail = client.get(f"/api/cases/{CASE}/communications/MSG-2201").json()
    return detail["review_suggestion"]  # type: ignore[no-any-return]


def test_reviewer_that_cannot_ground_another_reply_leaves_an_honest_unavailable_suggestion(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """REPLAY has a recording for the canonical reply only: other text fails the step. Nothing
    is faked: the suggestion is unavailable, no retry is offered, and the analyst reviews."""
    drafted_and_sent(client, factory)
    role(client, "cardholder")
    r = client.post("/api/requests/MSG-2201/responses", json={"text": OTHER_REPLY})
    assert r.status_code == 200
    assert _suggestion(client)["status"] == "pending"
    drain(factory)
    s = _suggestion(client)
    assert s["status"] == "unavailable" and s["classification"] is None
    assert step(client) == ("response_received", "response")
    role(client, "analyst")
    case = client.get(f"/api/cases/{CASE}").json()
    assert case["recovery_actions"] == []  # no generic graph retry for this step
    assert "review_cardholder_response" in [a["command"] for a in case["available_actions"]]
    summary = q(factory, "select summary from audit_events where type='specialist.failed'")
    assert [x[0] for x in summary] == [
        f"Review suggestion unavailable ({s['reason']}). Review the reply yourself."
    ]
    v = version(client)
    r = command(client, "review_cardholder_response", f"review:{CASE}:{v}", {"outcome": "complete"})
    assert r.status_code == 200, r.text


def test_live_reviewer_classifies_any_reply_through_mock_transport(
    client: TestClient, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[dict[str, Any]]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["messages"])
        if len(seen) == 1:
            message: dict[str, Any] = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c0",
                        "type": "function",
                        "function": {
                            "name": "read_field",
                            "arguments": json.dumps({"record_id": "RSP-2201", "field": "text"}),
                        },
                    }
                ],
            }
        else:  # the model saw the stored reply as tool data and cites it verbatim
            read = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
            assert read[0]["value"] == OTHER_REPLY
            out = {
                "classification": "complete",
                "citations": [
                    {
                        "record_id": "RSP-2201",
                        "version": 1,
                        "field": "text",
                        "value": OTHER_REPLY,
                        "statement": "The cardholder confirms the order and attaches the receipt.",
                    }
                ],
            }
            message = {"role": "assistant", "content": json.dumps(out)}
        return httpx.Response(
            200, json={"model": "stub-live-1", "choices": [{"message": message}], "usage": {}}
        )

    drafted_and_sent(client, factory)
    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(investigation, "LIVE_TRANSPORT", httpx.MockTransport(handle))
    role(client, "cardholder")
    r = client.post("/api/requests/MSG-2201/responses", json={"text": OTHER_REPLY})
    assert r.status_code == 200
    drain(factory)
    s = _suggestion(client)
    assert (s["status"], s["classification"]) == ("ready", "complete")
    assert s["citations"][0]["record_id"] == "RSP-2201"
    rows = q(
        factory,
        "select execution_mode, model_id from workflow_steps where step_key='response_reviewer'",
    )
    assert rows == [("live", "stub-live-1")]
