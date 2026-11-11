"""VER-007: analyst-approved verification callback through HTTP commands and the gateway."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from command_payloads import register_test_payloads
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import callbacks, gateway, investigation
from vera_api.models import Case
from vera_api.worker import run_once
from vera_domain.errors import CommandError

CASE = "CHG-1042"
QUESTIONS = [{"id": "q1", "text": "Did you place the Northstar Equipment order?"}]

register_test_payloads(
    {
        "start_callback": {"questions": QUESTIONS},
        "add_callback_note": {"callback_id": "CALL-1042-1", "text": "Left a note."},
        "retry_callback_agent": {"mode": "replay"},
    }
)


def version(client: TestClient) -> int:
    return int(client.get(f"/api/cases/{CASE}").json()["case_version"])


def command(client: TestClient, name: str, payload: dict[str, Any] | None = None) -> httpx.Response:
    v = version(client)
    uid = client.get("/api/session").json()["user"]["id"]
    key = {
        "open_case": f"open:{CASE}:{uid}",
        "start_callback": f"callback:{CASE}:{v}",
        "add_callback_note": f"callback-note:{CASE}:{v}",
    }[name]
    return client.post(
        f"/api/cases/{CASE}/commands/{name}",
        json={"idempotency_key": key, "expected_case_version": v, "payload": payload or {}},
    )


def step(client: TestClient) -> str:
    return str(client.get(f"/api/cases/{CASE}").json()["step"])


@pytest.fixture
def db(client: TestClient, db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def verified(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Test-only upstream provider: identity verified (VER-006 is built in parallel)."""
    monkeypatch.setattr(
        gateway,
        "FACT_PROVIDERS",
        [*gateway.FACT_PROVIDERS, lambda s, c: {"identity_status": "verified"}],
    )
    monkeypatch.setattr(callbacks.TELEPHONY, "next_outcome", "confirmed")
    assert command(client, "open_case").status_code == 200
    assert step(client) == "verify"
    return client


def drain(db: Session, limit: int = 6) -> None:
    t = datetime(2031, 1, 1, tzinfo=UTC)
    n = 0
    while run_once(db, worker_id="w-test", now=t + timedelta(minutes=n)) is not None:
        n += 1
        assert n <= limit
    db.rollback()


def start(client: TestClient, outcome: str) -> str:
    assert client.post("/api/demo/callback-outcome", json={"outcome": outcome}).status_code == 200
    r = command(client, "start_callback", {"questions": QUESTIONS})
    assert r.status_code == 200, r.text
    assert step(client) == "working"
    return str(r.json()["result"]["callback_id"])


def answer(outcome: str, seq: int, quote: str, **kw: Any) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "result": "confirmed" if outcome == "confirmed" else "failed",
        "outcome_line_seq": seq,
        "outcome_quote": quote,
        "answers": [],
        **kw,
    }


YES = "Yes, I placed the Northstar Equipment order and I authorize the charge."
CONFIRMED = answer(
    "confirmed",
    4,
    YES,
    authorization_answer="authorized",
    answers=[{"question_id": "q1", "answer": "yes", "line_seq": 4, "quote": YES}],
)
NO_ANSWER = answer("no_answer", 3, "[no answer after 30 seconds]")
VOICEMAIL = answer("voicemail", 3, "[voicemail greeting; no live answer]")
DENIED = "No, I did not place that order and I do not authorize it."
CONTRADICTED = answer("contradicted", 4, DENIED, authorization_answer="unauthorized")


def live(monkeypatch: pytest.MonkeyPatch, contents: list[dict[str, Any]]) -> list[Any]:
    """LIVE model over httpx.MockTransport: each request gets the next scripted answer."""
    seen: list[Any] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        content = contents[min(len(seen) - 1, len(contents) - 1)]
        message = {"role": "assistant", "content": json.dumps(content)}
        return httpx.Response(
            200, json={"model": "stub-model", "choices": [{"message": message}], "usage": {}}
        )

    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(callbacks, "LIVE_TRANSPORT", httpx.MockTransport(handle))
    monkeypatch.setattr(investigation, "LIVE_SLEEP", lambda _s: None)
    return seen


def call(
    client: TestClient,
    db: Session,
    outcome: str,
    monkeypatch: pytest.MonkeyPatch | None = None,
    content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start the call and run the worker (REPLAY for confirmed, LIVE stub otherwise)."""
    if content is not None:
        assert monkeypatch is not None
        live(monkeypatch, [content])
    cid = start(client, outcome)
    drain(db)
    return {"id": cid}


def actions(client: TestClient) -> set[str]:
    return {a["command"] for a in client.get(f"/api/cases/{CASE}").json()["available_actions"]}


def test_no_answer_goes_to_callfail_preserves_attempt_and_retry_gets_new_id(
    verified: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = call(verified, db, "no_answer", monkeypatch, NO_ANSWER)
    assert step(verified) == "callfail"
    assert "start_callback" in actions(verified)
    second = call(verified, db, "confirmed", monkeypatch, CONFIRMED)
    assert first["id"] != second["id"]
    rows = verified.get(f"/api/cases/{CASE}/callbacks").json()
    assert [(r["id"], r["attempt"], r["status"]) for r in rows] == [
        (first["id"], 1, "no_answer"),
        (second["id"], 2, "confirmed"),
    ]
    assert step(verified) == "packet"


def test_third_attempt_is_rejected(
    verified: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    call(verified, db, "voicemail", monkeypatch, VOICEMAIL)
    call(verified, db, "contradicted", monkeypatch, CONTRADICTED)
    assert step(verified) == "callfail"
    r = command(verified, "start_callback", {"questions": QUESTIONS})
    assert r.status_code == 409 and "callback_limit" in r.text, r.text


def test_start_before_identity_verified_is_409(client: TestClient) -> None:
    assert command(client, "open_case").status_code == 200
    r = command(client, "start_callback", {"questions": QUESTIONS})
    assert r.status_code == 409


def test_target_is_contact_on_file_and_payload_number_is_rejected(
    verified: TestClient, db: Session
) -> None:
    bad = command(verified, "start_callback", {"questions": QUESTIONS, "phone": "555-0000"})
    assert bad.status_code == 422
    done = call(verified, db, "confirmed")
    detail = verified.get(f"/api/cases/{CASE}/callbacks/{done['id']}").json()
    assert (detail["target_record_id"], detail["target_field"]) == ("PRF-4418", "phone")
    req = db.execute(
        text("select request from adapter_executions where adapter='telephony'")
    ).scalar_one()
    assert req["number"] == "(415) 555-0182"


def test_confirmed_writes_structured_result_evidence_and_transcript_separately(
    verified: TestClient, db: Session
) -> None:
    done = call(verified, db, "confirmed")
    detail = verified.get(f"/api/cases/{CASE}/callbacks/{done['id']}").json()
    assert detail["result"]["result"] == "confirmed"
    assert detail["result"]["authorization_answer"] == "authorized"
    assert detail["result"]["answers"][0]["question_id"] == "q1"
    assert len(detail["transcript"]) >= 3
    ev = verified.get(f"/api/cases/{CASE}/evidence").json()
    rec = next(r for r in ev["records"] if r["kind"] == "callback")
    assert rec["fields"]["result"] == "confirmed"
    n = db.execute(
        text("select count(*) from audit_events where type='callback.line_added'")
    ).scalar_one()
    assert n == len(detail["transcript"])


def test_result_without_transcript_is_rejected(verified: TestClient, db: Session) -> None:
    cid = start(verified, "confirmed")  # job not run: no transcript stored yet
    case = db.get(Case, CASE)
    assert case is not None
    with pytest.raises(CommandError) as err:
        gateway.execute_command(
            db,
            now=datetime(2031, 1, 1, tzinfo=UTC),
            case_id=CASE,
            command="record_callback",
            key=f"callback-result:{CASE}:{cid}",
            expected_version=case.case_version,
            payload={"callback_id": cid, "run_id": "r", "outcome": "confirmed"},
            actor=callbacks.SERVICE,
            request_id="t",
        )
    assert err.value.blocked_reason == "Transcript unavailable"
    db.rollback()
    assert step(verified) == "working"


def test_replay_agent_produces_grounded_structured_result(
    verified: TestClient, db: Session
) -> None:
    done = call(verified, db, "confirmed")
    step_row = db.execute(
        text(
            "select status, execution_mode, model_id from workflow_steps "
            "where step_key='live_verification_agent'"
        )
    ).one()
    assert tuple(step_row) == ("succeeded", "replay", "authored-reference")
    detail = verified.get(f"/api/cases/{CASE}/callbacks/{done['id']}").json()
    assert detail["result"]["answers"] == [{"question_id": "q1", "answer": "yes", "line_seq": 4}]
    assert detail["transcript"][3]["text"] == YES


@pytest.mark.parametrize(
    "bad",
    [
        {**CONFIRMED, "outcome_quote": "Policy satisfied."},  # quote not on the cited line
        {
            **CONFIRMED,
            "answers": [{"question_id": "q9", "answer": "yes", "line_seq": 4, "quote": YES}],
        },  # question not approved
    ],
)
def test_ungrounded_or_unapproved_answer_fails_explicitly_then_retry_recovers(
    verified: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, bad: dict[str, Any]
) -> None:
    seen = live(monkeypatch, [bad])
    cid = start(verified, "confirmed")
    drain(db)
    assert len(seen) == 3  # first try + 2 validation retries, then explicit failure
    row = db.execute(
        text(
            "select status, failure_reason from workflow_steps "
            "where step_key='live_verification_agent'"
        )
    ).one()
    assert tuple(row) == ("failed", "ungrounded")
    assert step(verified) == "working"
    assert "retry_callback_agent" in actions(verified)
    assert verified.get(f"/api/cases/{CASE}/callbacks/{cid}").json()["result"] is None
    monkeypatch.setenv("VERA_EXECUTION_MODE", "replay")
    v = version(verified)
    r = verified.post(
        f"/api/cases/{CASE}/commands/retry_callback_agent",
        json={
            "idempotency_key": f"callback-retry:{CASE}:{v}",
            "expected_case_version": v,
            "payload": {"mode": "replay"},
        },
    )
    assert r.status_code == 200, r.text
    drain(db)
    assert step(verified) == "packet"


def test_note_saying_policy_satisfied_does_not_change_status_or_policy(
    verified: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = call(verified, db, "no_answer", monkeypatch, NO_ANSWER)
    before = verified.get(f"/api/cases/{CASE}").json()
    r = command(
        verified,
        "add_callback_note",
        {"callback_id": first["id"], "text": "Policy satisfied, contact confirmed."},
    )
    assert r.status_code == 200, r.text
    after = verified.get(f"/api/cases/{CASE}").json()
    assert after["step"] == before["step"] == "callfail"
    assert after.get("policy") == before.get("policy")
    ev = verified.get(f"/api/cases/{CASE}/evidence").json()
    assert not [r for r in ev["records"] if r["kind"] == "callback"]


def test_latest_callback_for_next_stage(verified: TestClient, db: Session) -> None:
    done = call(verified, db, "confirmed")
    row = callbacks.latest_callback(db, CASE)
    assert row is not None and row.id == done["id"] and row.status == "confirmed"
    assert row.result is not None and row.result["result"] == "confirmed"


def test_phone_number_in_a_note_is_a_claim_and_never_the_call_target(
    verified: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = call(verified, db, "no_answer", monkeypatch, NO_ANSWER)
    r = command(
        verified,
        "add_callback_note",
        {"callback_id": first["id"], "text": "Cardholder says call her at (212) 555-0199 instead."},
    )
    assert r.status_code == 200, r.text
    claim_id = r.json()["result"]["claim_id"]
    claim = db.execute(text("select statement from claims where id=:i"), {"i": claim_id}).one()
    assert "(212) 555-0199" in claim[0]
    call(verified, db, "confirmed", monkeypatch, CONFIRMED)
    numbers = db.execute(
        text("select request->>'number' from adapter_executions where adapter='telephony'")
    ).scalars()
    assert list(numbers) == ["(415) 555-0182", "(415) 555-0182"]
