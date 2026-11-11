"""VER-011: final communication and closure through the HTTP command seam and real Postgres."""

from collections.abc import Iterator
from typing import Any

import pytest
from command_payloads import TEST_PAYLOADS, register_test_payloads
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import adapters, closure, gateway
from vera_api.auth import Actor
from vera_api.models import Case
from vera_domain.adapters import AdapterResult
from vera_domain.clock import default_demo_clock
from vera_domain.closure import ChecklistItem
from vera_domain.commands import (
    REGISTRY,
    CommandSpec,
    NoPayload,
    StepSet,
    blocked_reason,
    reduce_open,
)
from vera_domain.enums import CaseState, CaseStep, EventType, Role

CASE = "CHG-1042"
NOW = default_demo_clock().now()
ANALYST = Actor("usr-sam-rivera", "Sam Rivera", Role.ANALYST, frozenset({Role.ANALYST}))
CLOSE_BODY = {"reason": "All outcomes recorded and sent", "outcome": "resolved"}

register_test_payloads(
    {
        "draft_final_message": {},
        "update_final_message": {"body": "Hello, no further action is needed from you."},
        "send_final_message": {},
        "close_case": CLOSE_BODY,
    }
)


class Messaging:
    """Test-only `messaging` adapter (product code registers none)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def call(self, operation: str, request: dict[str, Any]) -> AdapterResult:
        self.sent.append(request)
        return AdapterResult(status="succeeded", result={"status": "delivered", "synthetic": True})


@pytest.fixture
def db(client: TestClient, db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


def _met(name: str, record: str) -> Any:
    return lambda s, cid: ChecklistItem(name=name, label=name, status="met", record_ids=[record])


def reach_finalprep(db: Session, monkeypatch: pytest.MonkeyPatch, **facts: Any) -> dict[str, Any]:
    """Test-only fact provider for the decision/credit/dispute/controls facts VER-009/010 own,
    then a test-only command so derive_step recomputes the stored step."""
    recorded = {"decision": "clear", **facts}
    monkeypatch.setattr(
        gateway, "FACT_PROVIDERS", [*gateway.FACT_PROVIDERS, lambda s, c: dict(recorded)]
    )
    spec = CommandSpec(
        "t_advance",
        frozenset({Role.ANALYST}),
        NoPayload,
        StepSet(),
        "t_advance:{case_id}:{case_version}",
        reduce_open,
        (EventType.CASE_OPENED,),
        "Advance",
        "primary",
    )
    monkeypatch.setitem(REGISTRY, "t_advance", spec)
    case = db.get(Case, CASE)
    assert case is not None
    gateway.execute_command(
        db,
        now=NOW,
        case_id=CASE,
        command="t_advance",
        key=f"t_advance:{CASE}:{case.case_version}",
        expected_version=case.case_version,
        payload={},
        actor=ANALYST,
        request_id="t",
    )
    return recorded


def register_parallel_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """What VER-009/010 register at integration, plus the two base items the seed lacks."""
    for name, rec in [
        ("decision", "DEC-1"),
        ("approval", "APR-1"),
        ("credit", "CRD-1"),
        ("dispute", "DSP-1"),
        ("controls", "CTL-1"),
        ("policy_current", "POL-1"),
        ("investigation_run", "RUN-1"),
    ]:
        monkeypatch.setitem(closure.CHECKLIST_SOURCES, name, _met(name, rec))


def view(client: TestClient) -> dict[str, Any]:
    return client.get(f"/api/cases/{CASE}").json()  # type: ignore[no-any-return]


def post(client: TestClient, command: str, key: str, payload: dict[str, Any] | None = None) -> Any:
    return client.post(
        f"/api/cases/{CASE}/commands/{command}",
        json={
            "idempotency_key": key,
            "expected_case_version": view(client)["case_version"],
            "payload": payload or {},
        },
    )


@pytest.fixture
def messaging(monkeypatch: pytest.MonkeyPatch) -> Messaging:
    adapter = Messaging()
    monkeypatch.setitem(adapters.ADAPTERS, "messaging", adapter)
    return adapter


def test_checklist_marks_unregistered_required_sources_unknown_and_reads_real_state(
    client: TestClient,
) -> None:
    body = client.get(f"/api/cases/{CASE}/closure-checklist").json()
    status = {i["name"]: i["status"] for i in body["items"]}
    assert body["ready"] is False
    for name in ("decision", "approval", "credit", "dispute", "controls"):
        assert status[name] == "unknown"
    assert status["policy_current"] == "unmet"  # no evaluation stored on the seed
    assert status["investigation_run"] == "unmet"
    assert status["exposure_columns"] == "met"
    assert status["final_message"] == "unmet"
    client.post("/api/session/role", json={"role": "cardholder"})
    assert client.get(f"/api/cases/{CASE}/closure-checklist").status_code == 403


def test_draft_is_blocked_while_required_sources_are_unknown(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    reach_finalprep(db, monkeypatch)
    assert view(client)["step"] == "finalprep"
    resp = post(client, "draft_final_message", f"final:{CASE}")
    assert resp.status_code == 422 and resp.json()["code"] == "closure_incomplete"
    assert "Decision recorded (unknown) - analyst: Record the decision" in resp.json()["message"]
    items = client.get(f"/api/cases/{CASE}/closure-checklist").json()["items"]
    for item in items:
        if item["status"] != "met":
            assert item["owner"] and item["next_action"], item
        else:
            assert item["owner"] is None
    assert view(client)["step"] == "finalprep"


def test_full_path_draft_edit_send_close_and_closed_gate(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, messaging: Messaging
) -> None:
    reach_finalprep(db, monkeypatch)
    register_parallel_sources(monkeypatch)
    gross_before = client.get("/api/cases/summary").json()["gross_exposure"]
    draft = post(client, "draft_final_message", f"final:{CASE}")
    assert draft.status_code == 200, draft.text
    assert view(client)["step"] == "final"
    msg = client.get(f"/api/cases/{CASE}/final-message").json()
    assert msg["status"] == "drafted"
    assert "No credit has been issued" in msg["body"]
    assert "No dispute is being pursued" in msg["body"]

    # content policy: an analyst edit asserting an unrecorded credit is rejected with the claim
    v = view(client)["case_version"]
    bad = post(
        client,
        "update_final_message",
        f"final-edit:{CASE}:{v}",
        {"body": "Good news. A temporary credit has been issued to your account."},
    )
    assert bad.status_code == 422 and bad.json()["code"] == "content_policy_violation"
    assert "credit_issued" in bad.json()["message"]
    ok = post(
        client,
        "update_final_message",
        f"final-edit:{CASE}:{v}",
        {"body": "Hello Priya. We reviewed the charge. No further action is needed from you."},
    )
    assert ok.status_code == 200, ok.text

    edited = post(client, "send_final_message", f"final-send:{CASE}", {"body": "Other text."})
    assert edited.status_code == 422 and edited.json()["code"] == "final_message_edited"
    stored = client.get(f"/api/cases/{CASE}/final-message").json()["body"]
    sent = post(client, "send_final_message", f"final-send:{CASE}", {"body": stored})
    assert sent.status_code == 200, sent.text
    resend = post(client, "send_final_message", f"final-send:{CASE}", {"body": stored})
    assert resend.json()["status"] == "replayed" and len(messaging.sent) == 1  # sent once
    assert messaging.sent[0]["body"].startswith("Hello Priya")
    assert view(client)["step"] == "close"
    assert client.get(f"/api/cases/{CASE}/final-message").json()["status"] == "sent"

    early = client.get(f"/api/cases/{CASE}/closure-checklist").json()
    assert early["ready"] is True
    closed = post(client, "close_case", f"close:{CASE}", CLOSE_BODY)
    assert closed.status_code == 200, closed.text
    again = post(client, "close_case", f"close:{CASE}", CLOSE_BODY)
    assert again.status_code == 200 and again.json()["status"] == "replayed"  # idempotent
    assert again.json()["result"] == closed.json()["result"]
    v = view(client)
    assert (v["state"], v["step"]) == ("closed", "closed")
    record = client.get(f"/api/cases/{CASE}/closure").json()
    assert record["state"] == "closed" and record["reason"] == CLOSE_BODY["reason"]
    assert record["closed_by"] == "usr-sam-rivera" and record["closed_at"]
    snap = db.execute(text("select evidence_snapshot from cases where id=:c"), {"c": CASE})
    assert record["evidence_snapshot"] == snap.scalar_one()
    assert record["outcome"] == "resolved" and all(
        i["status"] == "met" for i in record["checklist"]
    )

    # stage 5: every registered command is rejected on a closed case
    for name, spec in REGISTRY.items():
        err = blocked_reason(spec, CaseState.CLOSED, CaseStep.CLOSED)
        assert err is not None and err.code == "case_closed", name
    for name in ("draft_final_message", "send_final_message", "close_case", "hold_case"):
        resp = post(client, name, "k", TEST_PAYLOADS[name])
        assert resp.status_code == 409 and resp.json()["code"] == "case_closed", name

    # exposure: a closed case leaves gross exposure
    gross_after = client.get("/api/cases/summary").json()["gross_exposure"]
    assert gross_before["count"] == 6 and gross_after["count"] == 5
    assert gross_before["amount_cents"] == 1122000
    assert gross_after["amount_cents"] == 1122000 - 284000  # CHG-1042 is $2,840.00
    events = db.execute(
        text("select type from audit_events where case_id=:c order by id"), {"c": CASE}
    ).scalars()
    assert [e for e in events if e.startswith(("final_message", "case.closed"))] == [
        "final_message.drafted",
        "final_message.updated",
        "final_message.sent",
        "case.closed",
    ]


def test_draft_states_only_recorded_actions_when_credit_dispute_and_controls_recorded(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, messaging: Messaging
) -> None:
    reach_finalprep(
        db,
        monkeypatch,
        decision="credit",
        credit_status="issued",
        dispute_status="submitted",
        controls_status="applied",
        approval_status="approved",
    )
    register_parallel_sources(monkeypatch)
    assert view(client)["step"] == "finalprep"
    assert post(client, "draft_final_message", f"final:{CASE}").status_code == 200
    body = client.get(f"/api/cases/{CASE}/final-message").json()["body"]
    assert "temporary credit for the charge has been issued" in body
    assert "submitted a dispute" in body
    assert post(client, "send_final_message", f"final-send:{CASE}").status_code == 200
    closed = post(client, "close_case", f"close:{CASE}", CLOSE_BODY)
    assert closed.status_code == 200, closed.text
    v = view(client)
    assert (v["state"], v["step"]) == ("monitoring", "monitoring")  # dispute outcome pending
    resp = post(client, "hold_case", "k", TEST_PAYLOADS["hold_case"])
    assert resp.status_code == 409 and resp.json()["code"] == "case_closed"  # row 32


def test_send_is_blocked_with_a_typed_reason_without_a_messaging_adapter(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    reach_finalprep(db, monkeypatch)
    register_parallel_sources(monkeypatch)
    assert post(client, "draft_final_message", f"final:{CASE}").status_code == 200
    resp = post(client, "send_final_message", f"final-send:{CASE}")
    assert resp.status_code == 409 and resp.json()["code"] == "blocked"
    assert resp.json()["blocked_reason"] == "Messaging is not available"
    assert view(client)["step"] == "final"


def test_close_is_rejected_listing_open_items(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch, messaging: Messaging
) -> None:
    reach_finalprep(db, monkeypatch)
    register_parallel_sources(monkeypatch)
    assert post(client, "draft_final_message", f"final:{CASE}").status_code == 200
    assert post(client, "send_final_message", f"final-send:{CASE}").status_code == 200
    monkeypatch.delitem(closure.CHECKLIST_SOURCES, "approval")
    resp = post(client, "close_case", f"close:{CASE}", CLOSE_BODY)
    assert resp.status_code == 422 and resp.json()["code"] == "closure_incomplete"
    assert (
        "Approval valid for the decision (unknown) - reviewer: Approve the decision packet"
        in resp.json()["message"]
    )
    assert view(client)["step"] == "close"
