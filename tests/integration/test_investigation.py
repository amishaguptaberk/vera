"""VER-003B: model-backed investigation through HTTP commands and the worker (REPLAY and LIVE)."""

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
from vera_api import investigation
from vera_api.worker import run_once
from vera_domain.enums import Role

CASE = "CHG-1042"
REC = Path("evals/recordings")
SPECS = ("charge_investigator", "related_transaction_investigator", "receipt_document_reviewer")


@pytest.fixture
def factory(client: TestClient, db_url: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(db_url)
    f = sessionmaker(engine, expire_on_commit=False)
    with f() as s:
        s.execute(text("truncate table jobs, workflow_runs cascade"))
        s.execute(text("delete from checkpoint_writes"))
        s.execute(text("delete from checkpoint_blobs"))
        s.execute(text("delete from checkpoints"))
        s.commit()
    yield f
    engine.dispose()


@pytest.fixture(autouse=True)
def _seams(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", REC)
    monkeypatch.setattr(investigation, "LIVE_SLEEP", lambda _s: None)
    monkeypatch.delenv("VERA_EXECUTION_MODE", raising=False)
    yield


def version(client: TestClient) -> int:
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


def open_and_start(client: TestClient) -> httpx.Response:
    uid = client.get("/api/session").json()["user"]["id"]
    assert command(client, "open_case", f"open:{CASE}:{uid}").status_code == 200
    return command(client, "start_investigation", f"inv:{CASE}")


def drain(factory: sessionmaker[Session], limit: int = 10) -> int:
    t = datetime(2031, 1, 1, tzinfo=UTC)
    n = 0
    with factory() as s:
        while run_once(s, worker_id="w-test", now=t + timedelta(minutes=n)) is not None:
            n += 1
            assert n <= limit
    return n


def q(factory: sessionmaker[Session], sql: str) -> list[Any]:
    with factory() as s:
        return list(s.execute(text(sql)).all())


def copy_recordings(dst: Path) -> Path:
    shutil.copytree(REC, dst)
    return dst


# ---- TEST FIRST: REPLAY end to end --------------------------------------------------------------


def test_replay_investigation_posts_grounded_findings_and_advances_step(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    resp = open_and_start(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "recorded"
    assert (body["case"]["state"], body["case"]["step"]) == ("investigating", "working")
    assert body["result"]["mode"] == "replay"
    assert (body["result"]["workflow_version"], body["result"]["policy_version"]) == (3, 1)

    drain(factory)

    reg = client.get(f"/api/cases/{CASE}/evidence").json()
    findings = reg["findings"]
    for f in findings:
        assert f["links"], f
        for link in f["links"]:
            assert link["record_id"] and link["version"] >= 1 and link["field"]
    links = {
        (f["finding_id"], (lk["record_id"], lk["field"])) for f in findings for lk in f["links"]
    }
    cited = {pair for _, pair in links}
    # amount: the charge amount against the PO's approved amount
    assert {("CHG-1042", "amount_cents"), ("PO-219", "approved_amount_cents")} <= cited
    # quantity: PO-219.approved_quantity (1) vs DLV-882.received_quantity (2), as one conflict
    qty = [
        f
        for f in findings
        if {(lk["record_id"], lk["field"]) for lk in f["links"]}
        >= {("PO-219", "approved_quantity"), ("DLV-882", "received_quantity")}
    ]
    assert len(qty) == 1 and qty[0]["kind"] == "conflict"
    conflict_values = {
        (v["record_id"], v["value"]) for c in reg["open_conflicts"] for v in c["values"]
    }
    assert {("PO-219", 1), ("DLV-882", 2)} <= conflict_values
    # missing receipt cites the charge amount (no receipt record exists to cite)
    assert reg["missing"] == ["receipt"]
    assert any(
        "receipt" in f["statement"].lower()
        and {(lk["record_id"], lk["field"]) for lk in f["links"]} == {("CHG-1042", "amount_cents")}
        for f in findings
    )
    # related charge: CHG-1051 by full transaction identity (id, merchant, amount)
    related = [f for f in findings if f["kind"] == "related_charge"]
    assert len(related) == 1
    rel = related[0]
    assert "CHG-1051" in rel["statement"] and "Northstar Equipment" in rel["statement"]
    assert "$1,200.00" in rel["statement"]
    rel_fields = {(lk["record_id"], lk["field"]) for lk in rel["links"]}
    assert {("CHG-1051", "merchant"), ("CHG-1051", "amount_cents")} <= rel_fields
    assert all(lk["field"] != "card_last4" for f in findings for lk in f["links"])
    assert not any(re.search(r"\b4418\b", f["statement"]) for f in findings)

    runs = client.get(f"/api/cases/{CASE}/runs").json()
    assert len(runs) == 1 and runs[0]["status"] == "succeeded" and runs[0]["mode"] == "replay"
    steps = {s["step_key"]: s for s in runs[0]["steps"]}
    assert set(steps) == set(SPECS)
    for s in steps.values():
        assert s["status"] == "succeeded"
        assert s["execution_mode"] == "replay"
        assert s["model_id"] == "authored-reference"
        assert s["prompt_version"] == "v1"
        assert s["replayed"] is False

    # pc1 evaluated policy as the Policy Controller, after the last specialist
    pol = q(factory, "select actor_role from audit_events where type='policy.evaluated'")
    assert pol == [("policy_controller",)]
    types = [r[0] for r in q(factory, "select type from audit_events order by id")]
    last_spec = max(i for i, t in enumerate(types) if t == "run.step_succeeded")
    assert types.index("policy.evaluated") > last_spec
    assert types[-1] == "investigation.completed"
    assert types.index("investigation.started") < types.index("run.step_started")

    case = client.get(f"/api/cases/{CASE}").json()
    assert (case["state"], case["step"]) == ("investigating", "draft")


def test_no_specialist_code_prompt_or_recording_joins_on_card_digits() -> None:
    """US-C03: related charges are never linked by last four digits."""
    from vera_domain.investigation import TransactionIdentity, build_messages, specialist_input

    assert "last4" not in TransactionIdentity.model_fields
    inputs = specialist_input(
        "related_transaction_investigator",
        CASE,
        TransactionIdentity(
            transaction_id=CASE,
            merchant="Northstar Equipment",
            amount_cents=284000,
            currency="USD",
            cardholder_id="chd-priya-shah",
            posted_at="2026-11-09T10:00:00",
        ),
        {"CHG-1051": ("related_charge", ["merchant", "amount_cents"])},
        7500,
    )
    msgs = json.dumps(build_messages("related_transaction_investigator", inputs))
    assert "4418" not in msgs
    for path in REC.glob("related_transaction_investigator/v1/*.json"):
        assert "card_last4" not in path.read_text()


def test_start_twice_replays_with_one_run_and_one_job(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    assert open_and_start(client).json()["status"] == "recorded"
    again = command(client, "start_investigation", f"inv:{CASE}")
    assert again.status_code == 200 and again.json()["status"] == "replayed"
    assert q(factory, "select count(*) from workflow_runs") == [(1,)]
    assert q(factory, "select count(*) from jobs") == [(1,)]
    row = q(factory, "select workflow_version, policy_version from workflow_runs")
    assert row == [(3, 1)]


# ---- ungrounded -> failed -> retry resumes without re-running the sibling ----------------------


def _write(root: Path, spec: str, n: int, doc: dict[str, Any]) -> None:
    path = root / spec / "v1" / (f"{CASE}.json" if n == 0 else f"{CASE}.{n}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))


def test_ungrounded_output_fails_step_then_retry_resumes(
    client: TestClient, factory: sessionmaker[Session], tmp_path: Path, monkeypatch: Any
) -> None:
    bad = copy_recordings(tmp_path / "bad")
    final = json.loads((REC / "charge_investigator/v1/CHG-1042.1.json").read_text())
    wrong = json.loads(json.dumps(final))
    wrong["content"]["findings"][0]["citations"][0]["value"] = 248000  # not the source value
    for n in (1, 2, 3):  # first answer + two validation retries, all ungrounded
        _write(bad, "charge_investigator", n, wrong)
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", bad)
    calls: list[str] = []
    real = investigation.client_for

    def counting(mode: Any, case_id: str) -> Any:
        inner = real(mode, case_id)

        class C:
            def complete(self, **kw: Any) -> Any:
                calls.append(kw["specialist"])
                return inner.complete(**kw)

        return C()

    monkeypatch.setattr(investigation, "client_for", counting)
    open_and_start(client)
    before_case = client.get(f"/api/cases/{CASE}").json()
    drain(factory)

    runs = client.get(f"/api/cases/{CASE}/runs").json()
    steps = {s["step_key"]: s for s in runs[0]["steps"]}
    assert runs[0]["status"] == "failed"
    assert steps["charge_investigator"]["status"] == "failed"
    assert steps["charge_investigator"]["failure_reason"] == "ungrounded"
    assert steps["charge_investigator"]["attempts"] == 3
    assert steps["related_transaction_investigator"]["status"] == "succeeded"
    assert "receipt_document_reviewer" not in steps
    ids = [r[0] for r in q(factory, "select id from findings")]
    assert not any("charge_investigator" in i for i in ids)
    assert q(factory, "select count(*) from audit_events where type='specialist.failed'") == [(1,)]
    case = client.get(f"/api/cases/{CASE}").json()
    assert (case["state"], case["step"]) == (before_case["state"], before_case["step"])
    rec = {a["command"]: a for a in case["recovery_actions"]}
    assert set(rec) == {"retry_specialist_step", "hold_case"}
    retry = rec["retry_specialist_step"]
    assert retry["payload_defaults"] == {"step_key": "charge_investigator", "mode": "replay"}
    assert "{" not in retry["idempotency_key"]
    assert "retry_specialist_step" not in {a["command"] for a in case["available_actions"]}

    # retry with the good recordings
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", REC)
    calls.clear()
    resp = command(
        client, "retry_specialist_step", retry["idempotency_key"], retry["payload_defaults"]
    )
    assert resp.status_code == 200, resp.text
    drain(factory)
    assert "related_transaction_investigator" not in calls  # sibling not re-run
    assert calls.count("charge_investigator") == 2  # tool turn + answer
    runs = client.get(f"/api/cases/{CASE}/runs").json()
    assert runs[0]["status"] == "succeeded"
    assert {s["status"] for s in runs[0]["steps"]} == {"succeeded"}
    started = q(
        factory,
        "select detail->>'step_key', count(*) from audit_events where type='run.step_started'"
        " group by 1 order by 1",
    )
    assert dict(started)["related_transaction_investigator"] == 1
    case = client.get(f"/api/cases/{CASE}").json()
    assert case["step"] == "draft" and case["recovery_actions"] == []


# ---- scope, missing recording ------------------------------------------------------------------


def test_tool_call_outside_scope_is_a_recorded_scope_violation(
    client: TestClient, factory: sessionmaker[Session], tmp_path: Path, monkeypatch: Any
) -> None:
    root = copy_recordings(tmp_path / "scope")
    turn = json.loads((root / "charge_investigator/v1/CHG-1042.json").read_text())
    turn["tool_calls"].append(
        {"id": "x", "name": "read_field", "arguments": {"record_id": "PRF-4418", "field": "phone"}}
    )
    _write(root, "charge_investigator", 0, turn)
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", root)
    open_and_start(client)
    drain(factory)
    runs = client.get(f"/api/cases/{CASE}/runs").json()
    step = next(s for s in runs[0]["steps"] if s["step_key"] == "charge_investigator")
    assert step["status"] == "failed" and step["failure_reason"] == "scope_violation"
    tool_calls = q(
        factory,
        "select tool_calls from workflow_steps where step_key='charge_investigator'",
    )[0][0]
    assert tool_calls[-1]["outcome"] == "scope_violation"
    assert tool_calls[-1]["record_id"] == "PRF-4418"


def test_missing_recording_in_replay_is_an_explicit_error(
    client: TestClient, factory: sessionmaker[Session], tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", tmp_path / "empty")
    open_and_start(client)
    drain(factory)
    runs = client.get(f"/api/cases/{CASE}/runs").json()
    assert runs[0]["status"] == "failed"
    reasons = {s["failure_reason"] for s in runs[0]["steps"]}
    assert reasons == {"missing_recording"}
    assert q(factory, "select count(*) from findings") == [(0,)]


# ---- crash / resume (fixture 38) ---------------------------------------------------------------


def test_worker_crash_between_nodes_resumes_without_duplicates(
    client: TestClient, factory: sessionmaker[Session], monkeypatch: Any
) -> None:
    crashed: list[str] = []

    def hook(key: str) -> None:
        if key == "receipt_document_reviewer" and not crashed:
            crashed.append(key)
            raise RuntimeError("worker killed")

    monkeypatch.setattr(investigation, "NODE_HOOK", hook)
    open_and_start(client)
    assert drain(factory) == 2  # crash -> requeue -> resume
    assert crashed
    runs = client.get(f"/api/cases/{CASE}/runs").json()
    assert runs[0]["status"] == "succeeded"
    assert q(factory, "select count(*) from findings") == [(6,)]
    dup = q(
        factory,
        "select type, detail->>'step_key', count(*) from audit_events"
        " where type like 'run.step%' group by 1, 2 having count(*) > 1",
    )
    assert dup == []
    assert q(factory, "select count(*) from audit_events where type='finding.recorded'") == [(6,)]


# ---- LIVE --------------------------------------------------------------------------------------


def _stub(turns: dict[str, list[dict[str, Any]]], model: str) -> httpx.MockTransport:
    """Plays recorded turns per specialist, chosen by the system prompt, in OpenAI wire form."""
    seen: dict[str, int] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        name = next(n for n in SPECS if n.split("_")[0].capitalize() in system.split(".")[0])
        n = seen.get(name, 0)
        seen[name] = n + 1
        turn = turns[name][n]
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
            200, json={"model": model, "choices": [{"message": message}], "usage": {}}
        )

    return httpx.MockTransport(handle)


def _turns() -> dict[str, list[dict[str, Any]]]:
    return {
        n: [
            json.loads((REC / n / "v1" / f).read_text()) for f in (f"{CASE}.json", f"{CASE}.1.json")
        ]
        for n in SPECS
    }


def test_live_failure_is_not_replaced_until_explicit_replay_retry(
    client: TestClient, factory: sessionmaker[Session], tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", tmp_path / "empty")
    monkeypatch.setattr(
        investigation, "LIVE_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(500))
    )
    assert open_and_start(client).json()["result"]["mode"] == "live"
    drain(factory)
    runs = client.get(f"/api/cases/{CASE}/runs").json()
    assert runs[0]["status"] == "failed" and runs[0]["mode"] == "live"
    for s in runs[0]["steps"]:
        assert s["status"] == "failed" and s["failure_reason"] == "provider_error"
        assert s["execution_mode"] == "live" and s["replayed"] is False
    assert not (tmp_path / "empty").exists()
    assert q(factory, "select count(*) from findings") == [(0,)]

    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", REC)
    case = client.get(f"/api/cases/{CASE}").json()
    for action in [a for a in case["recovery_actions"] if a["command"] == "retry_specialist_step"]:
        payload = {**action["payload_defaults"], "mode": "replay"}
        resp = command(client, "retry_specialist_step", action["idempotency_key"], payload)
        assert resp.status_code == 200, resp.text
        drain(factory)
        if client.get(f"/api/cases/{CASE}/runs").json()[0]["status"] == "failed":
            continue
    runs = client.get(f"/api/cases/{CASE}/runs").json()
    replayed = [s for s in runs[0]["steps"] if s["replayed"]]
    assert replayed and all(s["execution_mode"] == "replay" for s in replayed)
    assert all(s["model_id"] == "authored-reference" for s in replayed)
    n = q(factory, "select count(*) from audit_events where type='specialist.replayed'")[0][0]
    assert n == len(replayed)


def test_live_happy_path_writes_findings_with_the_providers_model_id(
    client: TestClient, factory: sessionmaker[Session], tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("VERA_EXECUTION_MODE", "live")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", tmp_path / "empty")
    monkeypatch.setattr(investigation, "LIVE_TRANSPORT", _stub(_turns(), "stub/live-model"))
    open_and_start(client)
    drain(factory)
    runs = client.get(f"/api/cases/{CASE}/runs").json()
    assert runs[0]["status"] == "succeeded"
    for s in runs[0]["steps"]:
        assert s["execution_mode"] == "live" and s["model_id"] == "stub/live-model"
        assert s["replayed"] is False
    assert q(factory, "select count(*) from findings") == [(6,)]


# ---- RBAC and the state/step guard -------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.CARDHOLDER, Role.REVIEWER])
def test_other_roles_cannot_start_or_retry(
    client: TestClient, factory: sessionmaker[Session], role: Role
) -> None:
    uid = client.get("/api/session").json()["user"]["id"]
    command(client, "open_case", f"open:{CASE}:{uid}")
    resp = client.post("/api/session/role", json={"role": role.value})
    if resp.status_code != 200:
        pytest.skip(f"demo user does not hold {role}")
    for name, key, payload in (
        ("start_investigation", f"inv:{CASE}", {}),
        (
            "retry_specialist_step",
            "retry:x:charge_investigator:1",
            {"step_key": "charge_investigator", "mode": "replay"},
        ),
    ):
        r = command(client, name, key, payload)
        assert r.status_code == 403, r.text
    assert q(factory, "select count(*) from workflow_runs") == [(0,)]


def test_humans_cannot_run_the_worker_only_command(client: TestClient) -> None:
    r = client.post(
        f"/api/cases/{CASE}/commands/complete_investigation",
        json={
            "idempotency_key": "invdone:x",
            "expected_case_version": 1,
            "payload": {"run_id": "x"},
        },
    )
    assert r.status_code == 403


def test_worker_changes_state_and_step_only_through_the_gateway_reduction(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    open_and_start(client)
    drain(factory)
    rows = q(
        factory,
        "select prior_step, next_step, actor_role from state_transitions order by id",
    )
    case = q(factory, f"select state, step from cases where id='{CASE}'")[0]
    assert rows[-1][1] == case[1] == "draft"
    assert rows[-1][2] == "system"
    assert ("working", "draft", "system") in rows
