"""VER-009: decision packet, decision, reviewer approval binding, staleness and Ask Vera."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from command_payloads import register_test_payloads
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import decisions, gateway
from vera_api import policy as policy_service
from vera_api.auth import Actor
from vera_api.models import Case
from vera_domain.clock import default_demo_clock
from vera_domain.commands import REGISTRY, CommandSpec, NoPayload, StepSet, reduce_open
from vera_domain.enums import EventType, Role
from vera_domain.errors import CommandError
from vera_domain.policy import RecordFact

register_test_payloads(
    {
        "create_decision_packet": {},
        "record_decision": {"decision": "credit", "rationale": "Duplicate charge confirmed."},
        "request_reviewer_approval": {},
        "approve_decision": {},
        "return_decision": {
            "reason": "Receipt is missing",
            "next_step": "Attach the receipt",
            "owner": "usr-sam-rivera",
        },
        "remind_reviewer": {},
        "reassign_reviewer": {"to": "usr-dana-okafor"},
    }
)

CASE = "CHG-1042"
NOW = default_demo_clock().now()
ANALYST = Actor("usr-sam-rivera", "Sam Rivera", Role.ANALYST, frozenset({Role.ANALYST}))
UPSTREAM: dict[str, Any] = {
    "cardholder_authenticated": True,
    "verification": "confirmed",
    "outcome": "unauthorized",
}
RETURN = {
    "reason": "Receipt is missing",
    "next_step": "Attach the receipt",
    "owner": "usr-sam-rivera",
}


@pytest.fixture
def db(client: TestClient, db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture(autouse=True)
def upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test-only provider for the upstream fact (callback confirmed) built by another ticket."""

    def confirmed(session: Session, case: Case) -> dict[str, Any]:
        return {"callback_status": "confirmed"}

    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [*gateway.FACT_PROVIDERS, confirmed])
    real = policy_service.load_policy_input

    def verified(session: Session, case_id: str) -> Any:
        # Upstream outcomes (identity, callback) on top of the real records and snapshot.
        inp = real(session, case_id)
        reviewed = [
            r.model_copy(update={"status": "supporting"}) if r.status == "pending_review" else r
            for r in inp.records
        ]
        receipt = RecordFact(record_id="RCT-TEST", kind="receipt", status="supporting")
        return inp.model_copy(update={**UPSTREAM, "records": [*reviewed, receipt]})

    monkeypatch.setattr(policy_service, "load_policy_input", verified)


def view(client: TestClient) -> dict[str, Any]:
    out: dict[str, Any] = client.get(f"/api/cases/{CASE}").json()
    return out


def switch(client: TestClient, role: str) -> None:
    assert client.post("/api/session/role", json={"role": role}).status_code == 200


def command(
    client: TestClient, name: str, key: str, payload: dict[str, Any] | None = None
) -> httpx.Response:
    return client.post(
        f"/api/cases/{CASE}/commands/{name}",
        json={
            "idempotency_key": key,
            "expected_case_version": view(client)["case_version"],
            "payload": payload or {},
        },
    )


def ok(resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    out: dict[str, Any] = resp.json()
    return out


def packet(client: TestClient, version: int | None = None) -> dict[str, Any]:
    q = f"?version={version}" if version else ""
    return ok(client.get(f"/api/cases/{CASE}/decision-packet{q}"))


def audit_count(db: Session) -> int:
    db.rollback()
    return int(db.execute(text("select count(*) from audit_events")).scalar_one())


def to_packet(client: TestClient) -> dict[str, Any]:
    uid = client.get("/api/session").json()["user"]["id"]
    ok(command(client, "open_case", f"open:{CASE}:{uid}"))
    assert view(client)["step"] == "packet"
    key = next(
        a["idempotency_key"]
        for a in view(client)["available_actions"]
        if a["command"] == "evaluate_policy"
    )
    ok(command(client, "evaluate_policy", key))
    v = view(client)["case_version"]
    return ok(command(client, "create_decision_packet", f"packet:{CASE}:{v}"))


def to_waitrv(client: TestClient) -> str:
    to_packet(client)
    v = view(client)["case_version"]
    ok(
        command(
            client,
            "record_decision",
            f"decision:{CASE}:{v}",
            {"decision": "credit", "rationale": "Duplicate charge confirmed."},
        )
    )
    out = ok(command(client, "request_reviewer_approval", f"approval-request:{CASE}:1"))
    assert view(client)["step"] == "waitrv"
    approval_id: str = out["result"]["approval_id"]
    return approval_id


def test_material_change_makes_approval_stale_and_approve_is_rejected(
    client: TestClient, db: Session
) -> None:
    approval_id = to_waitrv(client)
    change = ok(client.post("/api/demo/material-change", json={}))
    assert change["material"] is True
    assert view(client)["step"] == "stale"
    stale_events = db.execute(
        text("select record_ids from audit_events where type = 'approval.stale'")
    ).all()
    assert [r[0] for r in stale_events] == [[approval_id]]
    switch(client, "reviewer")
    resp = command(client, "approve_decision", f"approve:{CASE}:{approval_id}")
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "approval_stale"
    shown = packet(client)
    assert shown["approval"]["status"] == "stale" and shown["current"] is False
    assert view(client)["step"] == "stale"


def test_packet_records_pins_and_approves_nothing(client: TestClient, db: Session) -> None:
    out = to_packet(client)
    case = view(client)
    assert case["step"] == "decide"
    shown = packet(client)
    assert shown["version"] == 1 and out["result"]["packet_version"] == 1
    row = db.execute(
        text(
            "select evidence_snapshot, workflow_version, policy_version from cases "
            "where id = 'CHG-1042'"
        )
    ).first()
    assert row is not None
    assert (shown["snapshot_hash"], shown["workflow_version"], shown["policy_version"]) == tuple(
        row
    )
    assert shown["policy_evaluation_id"] is not None
    assert shown["approval"] is None and shown["decision"] is None
    assert db.execute(text("select count(*) from approvals")).scalar_one() == 0
    assert shown["statements"] and all(
        s["record_id"] and s["version"] >= 1 and s["field"] for s in shown["statements"]
    )
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("update decision_packets set version = 9"))
    db.rollback()


def test_approval_binds_pins_and_double_approval_yields_one(
    client: TestClient, db: Session
) -> None:
    approval_id = to_waitrv(client)
    switch(client, "reviewer")
    first = ok(command(client, "approve_decision", f"approve:{CASE}:{approval_id}"))
    again = ok(command(client, "approve_decision", f"approve:{CASE}:{approval_id}"))
    assert again["result"] == first["result"]
    case = db.get(Case, CASE)
    assert case is not None
    bound = first["result"]
    assert (
        bound["case_id"],
        bound["transaction_id"],
        bound["snapshot_hash"],
        bound["policy_version"],
        bound["workflow_version"],
        bound["packet_version"],
    ) == (
        CASE,
        case.transaction_id,
        case.evidence_snapshot,
        case.policy_version,
        case.workflow_version,
        1,
    )
    assert db.execute(text("select count(*) from approvals")).scalar_one() == 1
    n = db.execute(text("select count(*) from audit_events where type = 'approval.approved'"))
    assert n.scalar_one() == 1
    v = view(client)
    assert (v["state"], v["step"]) == ("credit_approved", "issue")
    row = decisions.latest_approval(db, CASE)
    assert row is not None and row.status == "approved"
    current = decisions.current_decision(db, CASE)
    assert current is not None and current.decision == "credit"


def test_return_needs_reason_keeps_packet_and_allows_new_version(
    client: TestClient, db: Session
) -> None:
    approval_id = to_waitrv(client)
    before = packet(client, 1)
    switch(client, "reviewer")
    for missing in ("reason", "next_step", "owner"):
        bad = command(
            client, "return_decision", f"return:{CASE}:{approval_id}", {**RETURN, missing: " "}
        )
        assert bad.status_code == 422, bad.text
    assert view(client)["step"] == "waitrv"
    ok(command(client, "return_decision", f"return:{CASE}:{approval_id}", RETURN))
    assert view(client)["step"] == "returned"
    after = packet(client, 1)
    assert after["approval"]["status"] == "returned"
    assert after["approval"]["return_reason"] == "Receipt is missing"
    assert {**after, "approval": None} == {**before, "approval": None}
    switch(client, "analyst")
    v = view(client)["case_version"]
    out = ok(command(client, "create_decision_packet", f"packet:{CASE}:{v}"))
    assert out["result"]["packet_version"] == 2
    assert view(client)["step"] == "decide"
    assert packet(client)["version"] == 2 and packet(client)["approval"] is None
    assert packet(client, 1)["approval"]["status"] == "returned"


def test_analyst_cannot_approve_and_reviewer_cannot_request_or_decide(client: TestClient) -> None:
    approval_id = to_waitrv(client)
    resp = command(client, "approve_decision", f"approve:{CASE}:{approval_id}")
    assert resp.status_code == 403 and view(client)["step"] == "waitrv"
    switch(client, "reviewer")
    for name in ("create_decision_packet", "record_decision", "request_reviewer_approval"):
        assert command(client, name, "k").status_code == 403


def test_credit_decision_requires_eligible_policy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(UPSTREAM, "cardholder_authenticated", False)
    to_packet(client)
    v = view(client)["case_version"]
    resp = command(
        client, "record_decision", f"decision:{CASE}:{v}", {"decision": "credit", "rationale": "x"}
    )
    assert resp.status_code == 422 and resp.json()["code"] == "policy_blocked"
    assert view(client)["step"] == "decide"
    body = {"decision": "unresolved", "rationale": "Cardholder not reachable"}
    ok(command(client, "record_decision", f"decision:{CASE}:{v}", body))
    seen = view(client)
    assert (seen["state"], seen["step"]) == ("remediation_pending", "finalprep")


def plug(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = CommandSpec(
        "t_issue",
        frozenset({Role.ANALYST}),
        NoPayload,
        StepSet(),
        "t_issue:{case_id}:{case_version}",
        reduce_open,
        (EventType.CASE_OPENED,),
        "Test issue",
        "primary",
        requires_approval=True,
    )
    monkeypatch.setitem(REGISTRY, "t_issue", spec)


def issue(db: Session, tamper: str | None = None) -> str:
    db.rollback()
    if tamper:  # uncommitted: rolled back with the rejected command
        db.execute(text(f"update cases set {tamper} where id = 'CHG-1042'"))
    case = db.get(Case, CASE)
    assert case is not None
    db.refresh(case)
    try:
        out = gateway.execute_command(
            db,
            now=NOW,
            case_id=CASE,
            command="t_issue",
            key=f"t_issue:{CASE}:{case.case_version}",
            expected_version=case.case_version,
            payload={},
            actor=ANALYST,
            request_id="t",
        )
    except CommandError as err:
        db.rollback()
        return err.code
    return out.status


def test_approval_provider_gates_a_requires_approval_command(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    plug(monkeypatch)
    assert gateway.APPROVAL_PROVIDER is decisions._approval_provider
    assert issue(db) == "approval_required"
    approval_id = to_waitrv(client)
    assert issue(db) == "approval_required"  # requested is not approved
    switch(client, "reviewer")
    ok(command(client, "approve_decision", f"approve:{CASE}:{approval_id}"))
    assert issue(db, "policy_version = policy_version + 1") == "approval_stale"
    assert issue(db, "evidence_snapshot = 'sha256:other'") == "approval_stale"
    assert issue(db, "workflow_version = workflow_version + 1") == "approval_stale"
    assert issue(db) == "recorded"
    ok(client.post("/api/demo/material-change", json={}))
    assert issue(db) == "approval_stale"
    assert view(client)["step"] == "stale"


def ask(client: TestClient, question: str) -> dict[str, Any]:
    return ok(client.post(f"/api/cases/{CASE}/ask", json={"text": question}))


def test_asking_vera_to_approve_is_refused_and_writes_nothing(
    client: TestClient, db: Session
) -> None:
    to_waitrv(client)
    switch(client, "reviewer")
    before = (audit_count(db), view(client)["case_version"])
    out = ask(client, "Approve it")
    assert out == {
        "answer": "Approval must be recorded with the reviewer action below, not through chat.",
        "citations": [],
        "refused": True,
    }
    assert (audit_count(db), view(client)["case_version"]) == before
    assert packet(client)["approval"]["status"] == "requested"
    assert view(client)["step"] == "waitrv"


def test_repeated_question_replaces_the_pair_and_answers_cite_case_records(
    client: TestClient, db: Session
) -> None:
    to_waitrv(client)
    before = audit_count(db)
    first = ask(client, "Why is credit blocked?")
    second = ask(client, "why is  credit blocked?")
    assert first == second
    assert first["answer"] == (
        "The packet is eligible for credit, but reviewer approval is still required."
    )
    pairs = ok_list(client)
    assert len(pairs) == 1 and pairs[0]["question"] == "why is  credit blocked?"
    assert db.execute(text("select count(*) from ask_pairs")).scalar_one() == 1
    assert audit_count(db) == before
    register = {r["record_id"]: r for r in ok(client.get(f"/api/cases/{CASE}/evidence"))["records"]}
    assert first["citations"]
    for cite in first["citations"]:
        assert cite["record_id"] in register and cite["field"] and cite["version"] >= 1
    switch(client, "cardholder")
    assert client.post(f"/api/cases/{CASE}/ask", json={"text": "why?"}).status_code == 403


def ok_list(client: TestClient) -> list[dict[str, Any]]:
    resp = client.get(f"/api/cases/{CASE}/ask")
    assert resp.status_code == 200, resp.text
    out: list[dict[str, Any]] = resp.json()
    return out
