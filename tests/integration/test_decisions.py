"""Decision packet, decision, reviewer approval binding, staleness and Ask Vera."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import TEST_DB_URL
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import decisions, gateway, investigation
from vera_api import policy as policy_service
from vera_api.auth import Actor
from vera_api.models import Case
from vera_api.worker import run_once
from vera_domain.clock import default_demo_clock
from vera_domain.commands import REGISTRY, CommandSpec, NoPayload, StepSet, reduce_open
from vera_domain.enums import EventType, Role
from vera_domain.errors import CommandError
from vera_domain.policy import RecordFact

CASE = "CHG-1042"
REC = Path("evals/recordings")
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
    """Test-only provider for the upstream fact (callback confirmed)."""

    def confirmed(session: Session, case: Case) -> dict[str, Any]:
        return {"callback_status": "confirmed"}

    # Replaces the callbacks provider, which owns callback_status in the running app.
    from vera_api.callbacks import _facts as callback_facts

    providers = [p for p in gateway.FACT_PROVIDERS if p is not callback_facts]
    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [*providers, confirmed])
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", REC)
    monkeypatch.setattr(investigation, "LIVE_SLEEP", lambda _s: None)
    monkeypatch.delenv("VERA_EXECUTION_MODE", raising=False)
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


CAPTURES: dict[str, Any] = {}


def ok(resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    out: dict[str, Any] = resp.json()
    target = os.environ.get("VERA_TEST_CAPTURE")
    if target:  # optional: write each distinct real response to this file
        name = f"{resp.request.method} {resp.request.url.path}"
        if name not in CAPTURES:
            CAPTURES[name] = out
            Path(target).write_text(json.dumps(CAPTURES, indent=1, default=str))
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
    return new_packet(client)


def new_packet(client: TestClient, run: bool = True) -> dict[str, Any]:
    v = view(client)["case_version"]
    out = ok(command(client, "create_decision_packet", f"packet:{CASE}:{v}"))
    assert view(client)["step"] == "packet"  # draft until the preparer's output is stored
    if run:
        assert drain(client) >= 1
    return out


def drain(client: TestClient) -> int:
    engine = create_engine(TEST_DB_URL)
    n = 0
    t = datetime(2031, 1, 1, tzinfo=UTC)
    with sessionmaker(engine, expire_on_commit=False)() as s:
        while run_once(s, worker_id="w-test", now=t + timedelta(minutes=n)) is not None:
            n += 1
    engine.dispose()
    return n


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
    blocked = {b["command"]: b["blocked_reason"] for b in view(client)["blocked_actions"]}
    resp = command(client, "approve_decision", f"approve:{CASE}:{approval_id}")
    assert resp.status_code == 409, resp.text  # offered as blocked, refused with the same reason
    assert resp.json()["code"] == "approval_stale"
    assert blocked["approve_decision"] == resp.json()["blocked_reason"]
    shown = packet(client)
    assert shown["approval"]["status"] == "stale" and shown["current"] is False
    assert view(client)["step"] == "stale"


def test_packet_records_pins_and_approves_nothing(client: TestClient, db: Session) -> None:
    out = to_packet(client)
    case = view(client)
    assert case["step"] == "decide"
    shown = packet(client)
    assert shown["packet_status"] == "ready" and shown["preparer"]["execution_mode"] == "replay"
    assert shown["recommendation"] == "credit" and shown["recommendation_reasons"]
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
        c["record_id"] and c["version"] >= 1 and c["field"]
        for s in shown["statements"]
        for c in s["citations"]
    )
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("update decision_packet_contents set recommendation = 'clear'"))
    db.rollback()
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
    same = {"approval": None, "actions": []}  # the packet itself is unchanged
    assert {**after, **same} == {**before, **same}
    switch(client, "analyst")
    out = new_packet(client)
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


def ask(client: TestClient, question: str, **extra: Any) -> dict[str, Any]:
    return ok(client.post(f"/api/cases/{CASE}/ask", json={"text": question, **extra}))


def test_asking_vera_to_approve_is_refused_and_writes_nothing(
    client: TestClient, db: Session
) -> None:
    to_waitrv(client)
    switch(client, "reviewer")
    before = (audit_count(db), view(client)["case_version"])
    out = ask(client, "Approve it", role="reviewer")
    assert out["intent"] == "approve"
    assert out["paragraphs"] == [
        "Approval must be recorded with the reviewer action below, not through chat."
    ]
    assert out["actions"][0] == {
        "kind": "navigate",
        "label": "Open decision",
        "target": "decision",
        "command": None,
    }
    offered = {a["command"] for a in view(client)["available_actions"] if a["enabled"]}
    commands = {a["command"] for a in out["actions"] if a["kind"] == "command"}
    assert commands == {"approve_decision", "return_decision"} and commands <= offered
    assert (audit_count(db), view(client)["case_version"]) == before
    assert packet(client)["approval"]["status"] == "requested"
    assert view(client)["step"] == "waitrv"
    switch(client, "analyst")  # the analyst is never offered the approval command
    assert [a for a in ask(client, "approve it")["actions"] if a["kind"] == "command"] == []


def test_repeated_question_replaces_the_pair_and_answers_cite_case_records(
    client: TestClient, db: Session
) -> None:
    to_waitrv(client)
    before = audit_count(db)
    first = ask(client, "Why is credit blocked?")
    second = ask(client, "why is  credit blocked?")
    assert first == second and first["signature"]
    assert first["paragraphs"] == [
        "The packet is eligible for credit, but reviewer approval is still required."
    ]
    assert ask(client, "why?", last_intent="credit_blocked") == first
    pairs = ok_list(client)
    assert len(pairs) == 1 and pairs[0]["question"] == "why?"
    assert db.execute(text("select count(*) from ask_pairs")).scalar_one() == 1
    register = {r["record_id"]: r for r in ok(client.get(f"/api/cases/{CASE}/evidence"))["records"]}
    assert first["cites"]
    for cite in first["cites"]:
        assert cite["record_id"] in register and cite["field"] and cite["version"] >= 1
    call = ask(client, "Who do I call?")
    assert call["paragraphs"] == [
        "The approved contact is Priya Shah · (415) 555-0182.",
        "Use the contact currently on file, not a number from an unverified message.",
    ]
    assert call["cites"] == [{"record_id": "PRF-4418", "version": 1, "field": "phone"}]
    assert ask(client, "Phone on file")["paragraphs"] == [
        "The phone on file is (415) 555-0182 for Priya Shah."
    ]
    assert ask(client, "issue the credit")["paragraphs"] == [
        "The packet is eligible for credit, but reviewer approval is still required."
    ]
    close = ask(client, "Can we close?")
    assert close["paragraphs"][0] == "Not yet." and len(close["paragraphs"]) > 1
    assert close["actions"][-1]["label"] == "Open closure checklist"
    assert ask(client, "What is the weather?")["intent"] == "unknown"
    assert audit_count(db) == before
    switch(client, "cardholder")
    assert client.post(f"/api/cases/{CASE}/ask", json={"text": "why?"}).status_code == 403


def test_reviewer_packet_read_is_scoped_to_cited_evidence_and_own_actions(
    client: TestClient,
) -> None:
    to_waitrv(client)
    assert {a["command"] for a in packet(client)["actions"]} == {
        "remind_reviewer",
        "reassign_reviewer",
    }
    switch(client, "reviewer")
    shown = packet(client)
    assert {a["command"] for a in shown["actions"]} == {"approve_decision", "return_decision"}
    cited = {c["record_id"] for s in shown["statements"] for c in s["citations"]}
    assert {r["record_id"] for r in shown["cited_records"]} == cited == {"CHG-1042", "PO-219"}
    assert shown["cited_records"][0]["fields"] == {"amount_cents": 284000}
    assert shown["policy"]["status"] == "eligible"


def ok_list(client: TestClient) -> list[dict[str, Any]]:
    resp = client.get(f"/api/cases/{CASE}/ask")
    assert resp.status_code == 200, resp.text
    out: list[dict[str, Any]] = resp.json()
    return out


def test_consumed_approval_does_not_go_stale(client: TestClient, db: Session) -> None:
    approval_id = to_waitrv(client)
    with pytest.raises(CommandError):  # only an approved approval can be consumed
        decisions.mark_approval_consumed(db, approval_id, "EXE-1", NOW)
    db.rollback()
    switch(client, "reviewer")
    ok(command(client, "approve_decision", f"approve:{CASE}:{approval_id}"))
    decisions.mark_approval_consumed(db, approval_id, "EXE-1", NOW)
    decisions.mark_approval_consumed(db, approval_id, "EXE-1", NOW)  # idempotent
    with pytest.raises(CommandError):
        decisions.mark_approval_consumed(db, approval_id, "EXE-2", NOW)
    db.commit()
    ok(client.post("/api/demo/material-change", json={}))
    assert packet(client)["approval"]["status"] == "approved"
    n = db.execute(text("select count(*) from audit_events where type = 'approval.stale'"))
    assert n.scalar_one() == 0


def _live(turns: list[dict[str, Any]]) -> httpx.MockTransport:
    seen: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "Decision Packet Preparer" in body["messages"][0]["content"]
        turn = turns[len(seen)]
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
            200, json={"model": "test/live-model", "choices": [{"message": message}], "usage": {}}
        )

    return httpx.MockTransport(handle)


def _turns() -> list[dict[str, Any]]:
    root = REC / "decision_packet_preparer" / "v1"
    return [json.loads((root / f).read_text()) for f in (f"{CASE}.json", f"{CASE}.1.json")]


def test_recording_is_marked_authored_reference() -> None:
    for turn in _turns():
        assert turn["provenance"] == "authored-reference"
        assert turn["model_id"] == "authored-reference"


def test_live_preparer_writes_the_packet_and_decides_nothing(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(investigation, "LIVE_TRANSPORT", _live(_turns()))
    to_packet(client)
    shown = packet(client)
    assert shown["packet_status"] == "ready"
    assert (shown["preparer"]["execution_mode"], shown["preparer"]["model_id"]) == (
        "live",
        "test/live-model",
    )
    assert shown["recommendation"] == "credit"
    assert shown["decision"] is None and shown["approval"] is None  # a recommendation only
    assert view(client)["step"] == "decide"


def test_live_failure_is_explicit_and_recovers_only_by_retry(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        investigation, "LIVE_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(500))
    )
    to_packet(client)
    assert view(client)["step"] == "packet"  # no silent replay
    shown = packet(client)
    assert (shown["packet_status"], shown["preparer"]["status"]) == ("draft", "failed")
    assert shown["preparer"]["failure_reason"] == "provider_error"
    assert shown["statements"] == [] and shown["recommendation"] is None
    failed = db.execute(
        text("select count(*) from audit_events where type = 'specialist.failed'")
    ).scalar_one()
    assert failed == 1
    retry = ok(
        command(client, "retry_decision_packet", f"packet-retry:{CASE}:1:1", {"mode": "replay"})
    )
    assert retry["result"]["mode"] == "replay"
    assert drain(client) >= 1
    shown = packet(client)
    assert (shown["packet_status"], shown["preparer"]["execution_mode"]) == ("ready", "replay")
    assert view(client)["step"] == "decide"
    again = command(client, "retry_decision_packet", "packet-retry:x", {"mode": "replay"})
    assert again.status_code == 409  # nothing failed: the step is decide


def test_ungrounded_output_fails_the_step(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    turns = _turns()
    turns[1]["content"]["statements"][0]["citations"][0]["value"] = 1
    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(investigation, "LIVE_TRANSPORT", _live([*turns, *turns, *turns, *turns]))
    to_packet(client)
    shown = packet(client)
    assert shown["packet_status"] == "draft" and shown["preparer"]["failure_reason"] == "ungrounded"
    assert view(client)["step"] == "packet"


def test_request_dump_carries_ids_and_field_names_not_values(db: Session, tmp_path: Path) -> None:
    root = Path(os.environ.get("VERA_TEST_REQUESTS_DIR") or tmp_path)
    doc = json.loads(decisions.dump_request(db, CASE, root).read_text())
    user = doc["messages"][1]["content"]
    assert "PRF-4418" in user and "phone" in user
    assert "555-0182" not in user and "284000" not in user  # values are read through the tool
    assert doc["response_schema"]["properties"]["recommendation"]
