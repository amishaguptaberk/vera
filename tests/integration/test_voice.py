"""Voice verification boundary: real provider client over MockTransport, signed webhooks."""

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import callbacks, gateway, investigation, voice
from vera_api.worker import run_once

CASE = "CHG-1042"
QUESTIONS = [{"id": "q1", "text": "Did you place the Northstar Equipment order?"}]
SECRET = "whsec-test-not-real"
KEY = "xi-test-key-not-real"
YES = "Yes, I placed the Northstar Equipment order and I authorize the charge."
CONFIRMED = {
    "outcome": "confirmed",
    "result": "confirmed",
    "outcome_line_seq": 4,
    "outcome_quote": YES,
    "authorization_answer": "authorized",
    "answers": [{"question_id": "q1", "answer": "yes", "line_seq": 4, "quote": YES}],
}
URL = "/api/webhooks/voice/elevenlabs"


@pytest.fixture
def db(client: TestClient, db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def provider_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "message": "ok",
                "conversation_id": "conv_abc",
                "callSid": "CA123",
            },
        )

    for name, value in {
        "VERA_VOICE_PROVIDER": "elevenlabs",
        "ELEVENLABS_API_KEY": KEY,
        "ELEVENLABS_AGENT_ID": "agent_1",
        "ELEVENLABS_AGENT_PHONE_NUMBER_ID": "phnum_1",
        "ELEVENLABS_WEBHOOK_SECRET": SECRET,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(voice, "LIVE_TRANSPORT", httpx.MockTransport(handle))
    voice.reset_provider()
    yield seen
    voice.reset_provider()


def version(client: TestClient) -> int:
    return int(client.get(f"/api/cases/{CASE}").json()["case_version"])


def command(client: TestClient, name: str, payload: dict[str, Any] | None = None) -> httpx.Response:
    v = version(client)
    uid = client.get("/api/session").json()["user"]["id"]
    key = {"open_case": f"open:{CASE}:{uid}", "start_callback": f"callback:{CASE}:{v}"}[name]
    return client.post(
        f"/api/cases/{CASE}/commands/{name}",
        json={"idempotency_key": key, "expected_case_version": v, "payload": payload or {}},
    )


def step(client: TestClient) -> str:
    return str(client.get(f"/api/cases/{CASE}").json()["step"])


@pytest.fixture
def verified(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        gateway,
        "FACT_PROVIDERS",
        [*gateway.FACT_PROVIDERS, lambda s, c: {"identity_status": "verified"}],
    )
    assert command(client, "open_case").status_code == 200
    return client


def live_agent(monkeypatch: pytest.MonkeyPatch, content: dict[str, Any]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        message = {"role": "assistant", "content": json.dumps(content)}
        return httpx.Response(
            200, json={"model": "stub-model", "choices": [{"message": message}], "usage": {}}
        )

    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(callbacks, "LIVE_TRANSPORT", httpx.MockTransport(handle))
    monkeypatch.setattr(investigation, "LIVE_SLEEP", lambda _s: None)


def drain(db: Session) -> None:
    t = datetime(2031, 1, 1, tzinfo=UTC)
    n = 0
    while run_once(db, worker_id="w-test", now=t + timedelta(minutes=n)) is not None:
        n += 1
        assert n <= 6
    db.rollback()


def post_signed(client: TestClient, doc: dict[str, Any], secret: str = SECRET) -> httpx.Response:
    body = json.dumps(doc).encode()
    sig = voice.sign(secret, body, int(time.time()))
    return client.post(URL, content=body, headers={"ElevenLabs-Signature": sig})


def transcript_doc(conv: str = "conv_abc", results: dict[str, Any] | None = None) -> dict[str, Any]:
    lines = [
        {"role": "agent", "message": "Hello, this is a verification call from the card issuer."},
        {"role": "agent", "message": QUESTIONS[0]["text"]},
        {"role": "user", "message": "Hello, this is Priya."},
        {"role": "user", "message": YES},
    ]
    return {
        "type": "post_call_transcription",
        "event_timestamp": 1,
        "data": {
            "conversation_id": conv,
            "status": "done",
            "transcript": lines,
            "analysis": {
                "data_collection_results": results
                if results is not None
                else {"q1": {"data_collection_id": "q1", "value": "I placed the Northstar"}},
                "call_successful": "success",
                "transcript_summary": "Cardholder confirmed.",
            },
            "metadata": {"start_time_unix_secs": 1, "call_duration_secs": 40},
        },
    }


def count(db: Session, table: str) -> int:
    n = int(db.execute(text(f"select count(*) from {table}")).scalar_one())
    db.rollback()
    return n


def start(client: TestClient) -> str:
    r = command(client, "start_callback", {"questions": QUESTIONS, "consent_recorded": True})
    assert r.status_code == 200, r.text
    return str(r.json()["result"]["callback_id"])


def test_start_calls_elevenlabs_with_approved_questions_only(
    verified: TestClient, db: Session, provider_calls: list[httpx.Request]
) -> None:
    cid = start(verified)
    assert step(verified) == "working"
    assert len(provider_calls) == 1
    req = provider_calls[0]
    assert req.url.path == "/v1/convai/twilio/outbound-call"
    assert req.headers["xi-api-key"] == KEY
    body = json.loads(req.content)
    assert body["agent_id"] == "agent_1" and body["agent_phone_number_id"] == "phnum_1"
    number = body["to_number"]
    assert number.startswith("+")
    dv = body["conversation_initiation_client_data"]["dynamic_variables"]
    assert dv == {
        "case_ref": CASE,
        "purpose": voice.PURPOSE,
        "questions": "1. Did you place the Northstar Equipment order?",
        "question_ids": "q1",
    }
    detail = verified.get(f"/api/cases/{CASE}/callbacks/{cid}")
    assert detail.json()["voice"]["masked_number"].endswith(number[-4:])
    assert number[1:] not in detail.text and KEY not in detail.text
    # no job enqueued: the call is pending until the signed webhook arrives
    assert count(db, "voice_calls") == 1


def test_start_without_consent_is_rejected(
    verified: TestClient, db: Session, provider_calls: list[httpx.Request]
) -> None:
    r = command(verified, "start_callback", {"questions": QUESTIONS})
    assert r.status_code == 422 and "consent_missing" in r.text
    assert provider_calls == [] and count(db, "voice_calls") == 0


def test_missing_settings_is_a_typed_error(
    verified: TestClient, provider_calls: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ELEVENLABS_WEBHOOK_SECRET")
    voice.reset_provider()
    r = command(verified, "start_callback", {"questions": QUESTIONS, "consent_recorded": True})
    assert r.status_code == 503 and "ELEVENLABS_WEBHOOK_SECRET" in r.text
    assert provider_calls == []


def test_bad_or_missing_signature_is_401_and_writes_nothing(
    verified: TestClient, db: Session, provider_calls: list[httpx.Request]
) -> None:
    start(verified)
    assert post_signed(verified, transcript_doc(), secret="wrong").status_code == 401
    assert verified.post(URL, content=json.dumps(transcript_doc())).status_code == 401
    assert count(db, "voice_webhook_events") == 0
    assert count(db, "voice_transcript_versions") == 0


def test_verified_transcript_records_through_gateway_once(
    verified: TestClient,
    db: Session,
    provider_calls: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cid = start(verified)
    live_agent(monkeypatch, CONFIRMED)
    r = post_signed(verified, transcript_doc())
    assert r.status_code == 200 and r.json()["result"] == "applied"
    assert step(verified) == "working"  # state changes only via record_callback
    drain(db)
    assert step(verified) == "packet"
    replay = post_signed(verified, transcript_doc())
    assert replay.status_code == 200 and replay.json()["result"] == "duplicate"
    assert count(db, "voice_transcript_versions") == 1
    v = verified.get(f"/api/cases/{CASE}/callbacks/{cid}").json()
    assert v["status"] == "confirmed"
    assert v["voice"]["structured_answers"] == [
        {"question_id": "q1", "answer": "I placed the Northstar", "line_index": 4}
    ]
    seqs = {line["seq"]: line["text"] for line in v["transcript"]}
    assert seqs[4] == YES  # citation chips find their line by seq
    assert v["voice"]["confidence"] == 1.0 and v["voice"]["call_status"] == "completed"


def test_injected_instruction_and_unapproved_answer_are_rejected(
    verified: TestClient, db: Session, provider_calls: list[httpx.Request]
) -> None:
    cid = start(verified)
    doc = transcript_doc(
        results={
            "approve_credit": {"data_collection_id": "approve_credit", "value": "yes"},
            "q1": {"value": "I placed the Northstar", "action": "close_case"},
        }
    )
    assert post_signed(verified, doc).json()["result"] == "applied"
    v = verified.get(f"/api/cases/{CASE}/callbacks/{cid}").json()["voice"]
    assert v["structured_answers"] == [] and v["confidence"] == 0.0
    assert len(v["rejected"]) == 2
    assert step(verified) == "working"


def test_busy_goes_to_callfail_and_unknown_call_is_orphan(
    verified: TestClient, db: Session, provider_calls: list[httpx.Request]
) -> None:
    start(verified)
    orphan = post_signed(verified, transcript_doc(conv="conv_unknown"))
    assert orphan.json()["result"] == "orphan"
    fail = {
        "type": "call_initiation_failure",
        "data": {
            "conversation_id": "conv_abc",
            "failure_reason": "busy",
            "metadata": {"type": "twilio", "body": {"CallSid": "CA123"}},
        },
    }
    assert post_signed(verified, fail).json()["result"] == "applied"
    assert step(verified) == "callfail"
    actions = {a["command"] for a in verified.get(f"/api/cases/{CASE}").json()["available_actions"]}
    assert "start_callback" in actions
    assert post_signed(verified, fail).json()["result"] == "duplicate"
