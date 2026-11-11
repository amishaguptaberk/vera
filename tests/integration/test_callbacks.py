"""VER-007: analyst-approved verification callback through HTTP commands and the gateway."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from command_payloads import register_test_payloads
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import callbacks, gateway
from vera_api.models import Case

CASE = "CHG-1042"
QUESTIONS = [{"id": "q1", "text": "Did you place the Northstar Equipment order?"}]

register_test_payloads(
    {
        "start_callback": {"questions": QUESTIONS},
        "add_callback_note": {"callback_id": "CALL-1042-1", "text": "Left a note."},
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


def call(client: TestClient, db: Session, outcome: str) -> dict[str, Any]:
    assert client.post("/api/demo/callback-outcome", json={"outcome": outcome}).status_code == 200
    r = command(client, "start_callback", {"questions": QUESTIONS})
    assert r.status_code == 200, r.text
    cid = r.json()["result"]["callback_id"]
    assert step(client) == "working"
    out = client.post("/api/demo/callback-run", json={"case_id": CASE, "callback_id": cid})
    assert out.status_code == 200, out.text
    return {"id": cid, **out.json()}


def actions(client: TestClient) -> set[str]:
    return {a["command"] for a in client.get(f"/api/cases/{CASE}").json()["available_actions"]}


def test_no_answer_goes_to_callfail_preserves_attempt_and_retry_gets_new_id(
    verified: TestClient, db: Session
) -> None:
    first = call(verified, db, "no_answer")
    assert step(verified) == "callfail"
    assert "start_callback" in actions(verified)
    second = call(verified, db, "confirmed")
    assert first["id"] != second["id"]
    rows = verified.get(f"/api/cases/{CASE}/callbacks").json()
    assert [(r["id"], r["attempt"], r["status"]) for r in rows] == [
        (first["id"], 1, "no_answer"),
        (second["id"], 2, "confirmed"),
    ]
    assert step(verified) == "packet"


def test_third_attempt_is_rejected(verified: TestClient, db: Session) -> None:
    call(verified, db, "voicemail")
    call(verified, db, "contradicted")
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
    r = command(verified, "start_callback", {"questions": QUESTIONS})
    cid = r.json()["result"]["callback_id"]
    case = db.get(Case, CASE)
    assert case is not None
    with pytest.raises(Exception) as err:
        gateway.execute_command(
            db,
            now=case.updated_at if hasattr(case, "updated_at") else case.opened_at,  # type: ignore[arg-type]
            case_id=CASE,
            command="record_callback",
            key=f"callback-result:{CASE}:{cid}",
            expected_version=case.case_version,
            payload={"callback_id": cid, "outcome": "confirmed", "transcript": []},
            actor=callbacks.SERVICE,
            request_id="t",
        )
    assert getattr(err.value, "blocked_reason", None) == "Transcript unavailable"
    db.rollback()
    assert step(verified) == "working"


def test_note_saying_policy_satisfied_does_not_change_status_or_policy(
    verified: TestClient, db: Session
) -> None:
    first = call(verified, db, "no_answer")
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
