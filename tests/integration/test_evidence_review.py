"""Review outcomes reach the evidence register through its service commands, so the canonical
CHG-1042 journey can reach an eligible policy result from real evidence."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import callbacks, investigation
from vera_api.worker import run_once

CASE = "CHG-1042"
REC = Path("evals/recordings")
RECEIPT = {
    "file_name": "northstar-receipt.pdf",
    "content_type": "application/pdf",
    "size_bytes": 48213,
    "sha256": "b" * 64,
}
SEND = {"channel": "email", "subject": "Question about your Northstar charge", "attachments": []}
QUESTIONS = [{"id": "q1", "text": "Did you place the Northstar Equipment order?"}]


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
    monkeypatch.setattr(callbacks.TELEPHONY, "next_outcome", "confirmed")
    monkeypatch.delenv("VERA_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("VERA_VOICE_PROVIDER", raising=False)


# ---- helpers: everything goes through HTTP, as the roles ----------------------------------------


def role(client: TestClient, r: str) -> None:
    assert client.post("/api/session/role", json={"role": r}).status_code == 200


def view(client: TestClient) -> dict[str, Any]:
    role(client, "analyst")
    return client.get(f"/api/cases/{CASE}").json()  # type: ignore[no-any-return]


def act(client: TestClient, name: str, payload: dict[str, Any] | None = None) -> httpx.Response:
    """Post the command with the key the server offers on the action (analyst)."""
    v = view(client)
    action = next((a for a in v["available_actions"] if a["command"] == name), None)
    assert action is not None, (name, v["state"], v["step"], v["blocked_actions"])
    return client.post(
        f"/api/cases/{CASE}/commands/{name}",
        json={
            "idempotency_key": action["idempotency_key"],
            "expected_case_version": v["case_version"],
            "payload": {**action["payload_defaults"], **(payload or {})},
        },
    )


def ok(client: TestClient, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    r = act(client, name, payload)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def drain(factory: sessionmaker[Session]) -> None:
    t = datetime(2031, 1, 1, tzinfo=UTC)
    with factory() as s:
        n = 0
        while run_once(s, worker_id="w-test", now=t + timedelta(minutes=n)) is not None:
            n += 1
            assert n < 30


def step(client: TestClient) -> tuple[str, str]:
    v = view(client)
    return v["state"], v["step"]


def records(client: TestClient) -> dict[str, str]:
    role(client, "analyst")
    ev = client.get(f"/api/cases/{CASE}/evidence").json()
    return {r["record_id"]: r["status"] for r in ev["records"]}


def q(factory: sessionmaker[Session], sql: str) -> list[Any]:
    with factory() as s:
        return list(s.execute(text(sql)).all())


def latest_policy(factory: sessionmaker[Session]) -> tuple[str, list[str], str]:
    row = q(
        factory,
        "select status, result, snapshot_hash from policy_evaluations order by id desc limit 1",
    )[0]
    return row[0], list(row[1]["rules_failed"]), row[2]


def to_response(client: TestClient, factory: sessionmaker[Session], *, receipt: bool = True) -> str:
    """open -> investigation (replay) -> follow-up drafted and sent -> cardholder replies."""
    ok(client, "open_case")
    ok(client, "start_investigation")
    drain(factory)
    assert step(client) == ("investigating", "draft")
    ok(client, "draft_follow_up")
    drain(factory)
    ok(client, "send_communication", SEND)
    role(client, "cardholder")
    req = client.get("/api/requests").json()["requests"][0]["request_id"]
    body: dict[str, Any] = {"text": "Attached is the receipt I was sent for this charge."}
    if receipt:
        body["attachment"] = RECEIPT
    r = client.post(f"/api/requests/{req}/responses", json=body)
    assert r.status_code == 200, r.text
    drain(factory)  # response reviewer recommendation
    assert step(client) == ("response_received", "response")
    return f"RCP-{req.removeprefix('MSG-')}"


def verify_identity(client: TestClient) -> None:
    """send_verification_request (OTP); the cardholder reads the code from their outbox."""
    vid = ok(client, "send_verification_request", {"channel": "otp"})["result"]["verification_id"]
    version = view(client)["case_version"]
    role(client, "cardholder")
    box = client.get(f"/api/verifications/{vid}/outbox").json()
    r = client.post(
        f"/api/verifications/{vid}/submit_otp",
        json={
            "idempotency_key": f"otp:{vid}:{box['next_attempt_no']}",
            "expected_case_version": version,
            "code": box["code"],
        },
    )
    assert r.status_code == 200, r.text
    assert step(client) == ("callback_pending", "verify")


def call(client: TestClient, factory: sessionmaker[Session]) -> str:
    out = ok(client, "start_callback", {"questions": QUESTIONS, "consent_recorded": True})
    drain(factory)
    return str(out["result"]["callback_id"])


def events(factory: sessionmaker[Session], kind: str) -> list[Any]:
    return q(
        factory,
        f"select record_ids, actor_role, detail from audit_events where type='{kind}' order by id",
    )


# ---- 1. receipt acceptance ----------------------------------------------------------------------


def test_complete_review_accepts_the_receipt_and_marks_the_report_reviewed(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    rcp = to_response(client, factory)
    assert records(client)[rcp] == "pending_review"
    ok(client, "review_cardholder_response", {"outcome": "complete"})
    recs = records(client)
    assert (recs[rcp], recs["REP-1042"]) == ("supporting", "supporting")
    changed = events(factory, "evidence.status_changed")
    assert sorted(e[0][0] for e in changed) == sorted(["REP-1042", rcp])
    assert {e[1] for e in changed} == {"system"}  # the register's service principal
    keys = [k for (k,) in q(factory, "select key from idempotency_keys")]
    assert f"recstatus:{CASE}:{rcp}:supporting" in keys


def test_conflicting_review_keeps_the_receipt_pending_unless_accepted(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    rcp = to_response(client, factory)
    ok(client, "review_cardholder_response", {"outcome": "conflicting", "note": "Contradicts"})
    recs = records(client)
    assert (recs[rcp], recs["REP-1042"]) == ("pending_review", "supporting")


def test_conflicting_review_with_the_receipt_accepted_makes_the_receipt_rule_pass(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    rcp = to_response(client, factory)
    ok(client, "evaluate_policy")
    assert "receipt_required_above_threshold" in latest_policy(factory)[1]
    ok(
        client,
        "review_cardholder_response",
        {"outcome": "conflicting", "note": "Contradicts", "receipt_accepted": True},
    )
    assert records(client)[rcp] == "supporting"
    # The case had an evaluation: the status change re-evaluated it on the new snapshot.
    status, failed, snapshot = latest_policy(factory)
    assert "receipt_required_above_threshold" not in failed
    assert snapshot == view(client)["pins"]["evidence_snapshot"].removeprefix("sha256:")


# ---- 2. a confirmed callback resolves the open conflicts ---------------------------------------


def test_confirmed_callback_resolves_open_conflicts_with_the_callback_id(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_response(client, factory)
    ok(client, "review_cardholder_response", {"outcome": "conflicting", "receipt_accepted": True})
    ok(client, "evaluate_policy")
    assert "purchase_records_agree" in latest_policy(factory)[1]
    role(client, "analyst")
    open_before = client.get(f"/api/cases/{CASE}/evidence").json()["open_conflicts"]
    assert open_before  # the investigation's conflict and the reply's conflict
    verify_identity(client)
    cid = call(client, factory)
    assert step(client) == ("decision_pending", "packet")
    ev = client.get(f"/api/cases/{CASE}/evidence").json()
    assert ev["open_conflicts"] == []
    resolved = {f["finding_id"]: f for f in ev["findings"]}
    for c in open_before:
        assert (resolved[c["finding_id"]]["status"], resolved[c["finding_id"]]["resolved_by"]) == (
            "resolved",
            cid,
        )
    linked = {rid for c in open_before for rid in c["record_ids"]}
    assert all(records(client)[rid] == "supporting" for rid in linked)
    assert len(events(factory, "finding.resolved")) == len(open_before)
    _, failed, _ = latest_policy(factory)  # re-evaluated after each resolution
    assert "purchase_records_agree" not in failed
    assert "structured_verification" not in failed
    assert "verification_not_failed" not in failed


# ---- 3. related charges -------------------------------------------------------------------------


def test_review_related_charge_sets_the_status_through_the_register(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    ok(client, "open_case")
    ok(client, "start_investigation")
    drain(factory)
    ok(client, "evaluate_policy")
    assert "no_pending_review" in latest_policy(factory)[1]
    evaluated = len(q(factory, "select id from policy_evaluations"))
    reason = "Same merchant, separate order"
    ok(
        client,
        "review_related_charge",
        {"record_id": "CHG-1051", "decision": "related", "reason": reason},
    )
    ok(
        client,
        "review_related_charge",
        {"record_id": "CHG-1048", "decision": "not_related", "reason": "Cleared last month"},
    )
    recs = records(client)
    assert (recs["CHG-1051"], recs["CHG-1048"]) == ("supporting", "not_relevant")
    again = act(
        client,
        "review_related_charge",
        {"record_id": "CHG-1048", "decision": "related", "reason": "Changed my mind"},
    )
    assert again.status_code == 409 and "related_charge_reviewed" in again.text
    wrong = act(
        client,
        "review_related_charge",
        {"record_id": "PO-219", "decision": "related", "reason": "x"},
    )
    assert wrong.status_code == 404
    # REP-1042 is still pending (no response review yet), so the rule still fails, but the
    # case re-evaluated after each decision.
    assert len(q(factory, "select id from policy_evaluations")) == evaluated + 2


def test_review_related_charge_is_analyst_only(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    ok(client, "open_case")
    ok(client, "start_investigation")
    drain(factory)
    v = view(client)
    role(client, "reviewer")
    r = client.post(
        f"/api/cases/{CASE}/commands/review_related_charge",
        json={
            "idempotency_key": f"related:{CASE}:{v['case_version']}",
            "expected_case_version": v["case_version"],
            "payload": {"record_id": "CHG-1051", "decision": "related", "reason": "x"},
        },
    )
    assert r.status_code == 403


# ---- 5. the real path to an eligible result -----------------------------------------------------


def walk_to_packet(client: TestClient, factory: sessionmaker[Session]) -> None:
    to_response(client, factory)
    ok(
        client,
        "review_cardholder_response",
        {"outcome": "conflicting", "note": "Receipt total differs", "receipt_accepted": True},
    )
    verify_identity(client)
    call(client, factory)
    for rid, decision in (("CHG-1051", "not_related"), ("CHG-1048", "not_related")):
        ok(client, "review_related_charge", {"record_id": rid, "decision": decision, "reason": "r"})


def test_real_path_reaches_an_eligible_policy_result(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    walk_to_packet(client, factory)
    assert step(client) == ("decision_pending", "packet")
    out = ok(client, "evaluate_policy")
    pol = out["case"]["policy"]
    assert (pol["status"], pol["rules_failed"]) == ("eligible", []), pol
    assert pol["code"] == "CREDIT_ELIGIBLE"
    detail = client.get(f"/api/cases/{CASE}/callbacks").json()[-1]
    assert detail["result"]["authorization_answer"] == "unauthorized"


def test_an_authorized_answer_on_a_verified_case_is_ineligible(
    client: TestClient, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    said = "Yes, this is Priya, and I placed and authorize the Northstar Equipment order."
    monkeypatch.setitem(
        callbacks._SCRIPTS, "confirmed", [("contact", "Hello, this is Priya."), ("contact", said)]
    )
    content = {
        "outcome": "confirmed",
        "result": "confirmed",
        "authorization_answer": "authorized",
        "outcome_line_seq": 4,
        "outcome_quote": said,
        "answers": [{"question_id": "q1", "answer": "yes", "line_seq": 4, "quote": said}],
    }

    def handle(request: httpx.Request) -> httpx.Response:
        message = {"role": "assistant", "content": json.dumps(content)}
        return httpx.Response(
            200, json={"model": "stub-model", "choices": [{"message": message}], "usage": {}}
        )

    to_response(client, factory)
    ok(client, "review_cardholder_response", {"outcome": "conflicting", "receipt_accepted": True})
    verify_identity(client)
    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(callbacks, "LIVE_TRANSPORT", httpx.MockTransport(handle))
    call(client, factory)
    for rid in ("CHG-1051", "CHG-1048"):
        ok(
            client,
            "review_related_charge",
            {"record_id": rid, "decision": "not_related", "reason": "r"},
        )
    pol = ok(client, "evaluate_policy")["case"]["policy"]
    assert (pol["status"], pol["rules_failed"]) == ("ineligible", ["charge_not_authorized"])
