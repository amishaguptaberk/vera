"""Credit, dispute and card controls through the HTTP seam and command gateway (VER-010).

Approval (VER-009) is not in this tree: the approved state is reached with a TEST-ONLY approval
provider and fact provider, as in test_seams.py. The gateway's stage 8 does the enforcing.
"""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from command_payloads import register_test_payloads
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from test_policy import make_input
from test_seams import bound
from vera_api import adapters, gateway, money, worker
from vera_api import policy as policy_service
from vera_api.models import Case
from vera_domain.commands import REGISTRY, SERVICE_COMMANDS
from vera_domain.enums import Role
from vera_domain.specialists import ExecutionMode

register_test_payloads(
    {
        "issue_provisional_credit": {},
        "lookup_execution_result": {"idempotency_key": "credit:TXN-1042"},
        "prepare_dispute_packet": {},
        "open_dispute_packet": {},
        "review_dispute_packet": {},
        "submit_dispute": {},
        "propose_card_controls": {"controls": ["lock", "replace"]},
        "skip_card_controls": {"reason": "Card already replaced"},
        "approve_card_controls": {},
        "decline_card_controls": {"reason": "Not needed"},
        "apply_card_controls": {},
    }
)

CASE = "CHG-1042"
AMOUNT = 284000  # TXN-1042 posted amount (seed)
CKEY = "credit:TXN-1042"
# Credit issued, neither track started. Corrected facts.py (on main): the dispute step comes
# first (dsp_prepare); this tree's facts.py still says ctl_prep. Both are accepted until merged.
AFTER_ISSUE = (("dispute_prepared", "dsp_prepare"), ("credit_issued", "ctl_prep"))


@pytest.fixture
def db(client: TestClient, db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


class Calls:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
        self.n = 0
        inner = adapters.ADAPTERS[name]
        outer = self

        class Counting:
            def call(self, operation: str, request: dict[str, Any]) -> Any:
                outer.n += 1
                return inner.call(operation, request)

        monkeypatch.setitem(adapters.ADAPTERS, name, Counting())


def switch(client: TestClient, role: Role) -> None:
    assert client.post("/api/session/role", json={"role": role.value}).status_code == 200


def view(client: TestClient, case_id: str = CASE) -> dict[str, Any]:
    return client.get(f"/api/cases/{case_id}").json()  # type: ignore[no-any-return]


def send(
    client: TestClient,
    command: str,
    payload: dict[str, Any] | None = None,
    *,
    key: str | None = None,
    version: int | None = None,
) -> Any:
    seen = view(client)
    v = seen["case_version"] if version is None else version
    spec = REGISTRY[command]
    if key is None and command not in money.domain.HUMAN:  # earlier stages: the advertised key
        key = next(
            a["idempotency_key"] for a in seen["available_actions"] if a["command"] == command
        )
    return client.post(
        f"/api/cases/{CASE}/commands/{command}",
        json={
            "idempotency_key": key or spec.key_template.format(case_id=CASE, case_version=v),
            "expected_case_version": v,
            "payload": payload or {},
        },
    )


def ok(client: TestClient, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = send(client, command, payload)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def step(client: TestClient) -> tuple[str, str]:
    v = view(client)
    return v["state"], v["step"]


def offered(client: TestClient) -> set[str]:
    return {a["command"] for a in view(client)["available_actions"]}


def count(db: Session, sql: str) -> int:
    db.rollback()
    return int(db.execute(text(sql)).scalar_one())


@pytest.fixture
def approved(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """TEST-ONLY stand-in for VER-009: decision credit, packet ready, approval approved + bound.
    Mutate the returned dict to change the approval the provider reports."""
    state: dict[str, Any] = {"approval": {}, "present": True}

    def facts(session: Session, case: Case) -> dict[str, Any]:
        if case.id != CASE:
            return {}
        return {"packet_status": "ready", "decision": "credit", "approval_status": "approved"}

    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [*gateway.FACT_PROVIDERS, facts])
    monkeypatch.setattr(
        gateway,
        "APPROVAL_PROVIDER",
        lambda s, c: bound(c, **state["approval"]) if state["present"] else None,
    )
    monkeypatch.setattr(policy_service, "load_policy_input", lambda s, cid: make_input())
    switch(client, Role.ANALYST)
    ok(client, "open_case")
    ok(client, "evaluate_policy")
    assert step(client) == ("credit_approved", "issue")
    return state


def issue(client: TestClient) -> dict[str, Any]:
    return ok(client, "issue_provisional_credit")


# --- credit ---


def test_two_simultaneous_issue_commands_produce_one_credit_and_one_adapter_effect(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, "credit")
    v = view(client)["case_version"]
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def fire() -> None:
        barrier.wait()
        codes.append(send(client, "issue_provisional_credit", version=v).status_code)

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200, 200]  # one recorded, one replayed
    assert calls.n == 1
    assert count(db, "select count(*) from provisional_credits") == 1
    assert count(db, "select count(*) from adapter_executions where adapter='credit'") == 1
    assert count(db, "select attempts from adapter_executions where adapter='credit'") == 1
    assert count(db, "select count(*) from audit_events where type='credit.issued'") == 1
    # a later attempt under a new key is rejected by the step gate and issues nothing
    late = send(client, "issue_provisional_credit")
    assert late.status_code == 409 and late.json()["code"] == "invalid_step"
    assert calls.n == 1


def test_issue_uses_the_posted_amount_and_updates_exposure_as_pending(
    client: TestClient, db: Session, approved: dict[str, Any]
) -> None:
    before = client.get("/api/cases/summary").json()
    bad = send(client, "issue_provisional_credit", {"amount_cents": 1})
    assert bad.status_code == 422 and bad.json()["code"] == "schema_invalid"
    out = issue(client)
    assert out["result"]["credit_status"] == "issued"
    assert out["result"]["amount_cents"] == AMOUNT and out["result"]["credit_id"] == "CREDIT-1042"
    assert out["result"]["simulated"] is True
    assert step(client) in AFTER_ISSUE
    after = client.get("/api/cases/summary").json()
    rise = after["temporary_credit"]["amount_cents"] - before["temporary_credit"]["amount_cents"]
    assert rise == AMOUNT and after["temporary_credit"]["basis"] == "pending"
    assert after["net_exposure"] == before["net_exposure"]
    impact = view(client)["charge_impact"]
    assert impact["temporary_credit_cents"] == AMOUNT
    assert impact["net_exposure_cents"] == AMOUNT  # a pending credit is never deducted
    assert count(db, "select credit_cents from cases where id='CHG-1042'") == AMOUNT


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ({"present": False}, 422, "approval_required"),
        ({"approval": {"status": "stale"}}, 409, "approval_stale"),
        ({"approval": {"snapshot_hash": "sha256:other"}}, 409, "approval_stale"),
        ({"approval": {"policy_version": 99}}, 409, "approval_stale"),
    ],
)
def test_issue_without_a_current_bound_approval_is_blocked_and_writes_nothing(
    client: TestClient,
    db: Session,
    approved: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
    status: int,
    code: str,
) -> None:
    calls = Calls(monkeypatch, "credit")
    approved.update(change)
    resp = send(client, "issue_provisional_credit")
    assert (resp.status_code, resp.json()["code"]) == (status, code)
    assert "issue_provisional_credit" not in offered(client)
    assert calls.n == 0
    assert count(db, "select count(*) from provisional_credits") == 0
    assert count(db, "select count(*) from adapter_executions") == 0
    assert count(db, "select credit_cents from cases where id='CHG-1042'") == 0


def test_issue_requires_an_eligible_policy_result(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        policy_service, "load_policy_input", lambda s, cid: make_input("sha256:unevaluated")
    )
    resp = send(client, "issue_provisional_credit")
    assert (resp.status_code, resp.json()["code"]) == (422, "policy_blocked")
    assert count(db, "select count(*) from provisional_credits") == 0


def test_failed_before_effect_issues_nothing_and_retry_issues_once(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, "credit")
    fault = {"adapter": "credit", "operation": "issue", "mode": "timeout", "times": 1}
    assert client.post("/api/demo/adapter-fault", json=fault).status_code == 200
    out = issue(client)
    assert out["result"]["credit_status"] == "failed" and out["result"]["credit_id"] is None
    assert calls.n == 0 and step(client) == ("credit_approved", "issue")
    assert count(db, "select credit_cents from cases where id='CHG-1042'") == 0
    assert count(db, "select count(*) from audit_events where type='credit.issued'") == 0
    assert issue(client)["result"]["credit_status"] == "issued"
    assert calls.n == 1
    assert count(db, "select count(*) from provisional_credits where status='issued'") == 1
    assert count(db, "select attempts from adapter_executions where adapter='credit'") == 2


def test_uncertain_result_goes_to_credit_check_and_lookup_resolves_to_one_credit(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, "credit")
    fault = {"adapter": "credit", "operation": "issue", "mode": "uncertain", "times": 1}
    assert client.post("/api/demo/adapter-fault", json=fault).status_code == 200
    out = issue(client)
    assert out["result"]["credit_status"] == "uncertain" and out["result"]["credit_id"] is None
    assert step(client) == ("credit_approved", "credit_check")
    # nothing assumes success
    assert count(db, "select credit_cents from cases where id='CHG-1042'") == 0
    assert count(db, "select count(*) from audit_events where type='credit.issued'") == 0
    mine = offered(client) & set(money.domain.HUMAN)
    assert mine == {"lookup_execution_result"}
    again = send(client, "issue_provisional_credit")
    assert again.status_code == 409 and calls.n == 1
    wrong = send(client, "lookup_execution_result", {"idempotency_key": "credit:TXN-9999"})
    assert wrong.status_code == 404
    found = ok(client, "lookup_execution_result", {"idempotency_key": CKEY})["result"]
    assert found["found"] is True and found["credit_status"] == "issued"
    assert found["credit_id"] == "CREDIT-1042"
    assert calls.n == 1  # resolved by lookup, never re-sent
    assert step(client) in AFTER_ISSUE
    assert count(db, "select count(*) from provisional_credits") == 1
    assert count(db, "select credit_cents from cases where id='CHG-1042'") == AMOUNT
    assert count(db, "select count(*) from audit_events where type='credit.confirmed'") == 1


def test_reconciler_job_resolves_an_uncertain_credit_by_lookup_without_reissuing(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, "credit")
    adapters.inject_fault(db, "credit", "issue", "uncertain", 1)
    db.commit()
    issue(client)
    assert "reconcile_execution_result" in SERVICE_COMMANDS
    worker.enqueue(db, money.RECONCILER_JOB, {"case_id": CASE})
    db.commit()
    assert worker.run_once(db, worker_id="t") is not None
    assert calls.n == 1 and step(client) in AFTER_ISSUE
    assert count(db, "select count(*) from provisional_credits where status='issued'") == 1
    worker.enqueue(db, money.RECONCILER_JOB, {"case_id": CASE})  # second run: nothing to do
    db.commit()
    worker.run_once(db, worker_id="t")
    assert count(db, "select count(*) from audit_events where type='credit.confirmed'") == 1


def test_reviewer_cannot_issue_and_executions_are_staff_only(
    client: TestClient, db: Session, approved: dict[str, Any]
) -> None:
    switch(client, Role.REVIEWER)
    resp = send(client, "issue_provisional_credit")
    assert resp.status_code == 403 and resp.json()["code"] == "role_forbidden"
    assert count(db, "select count(*) from provisional_credits") == 0
    switch(client, Role.ANALYST)
    issue(client)
    body = client.get(f"/api/cases/{CASE}/executions").json()
    assert [
        (e["adapter"], e["operation"], e["status"], e["attempts"]) for e in body["executions"]
    ] == [("credit", "issue", "succeeded", 1)]
    assert body["executions"][0]["idempotency_key"] == CKEY
    switch(client, Role.CARDHOLDER)
    assert client.get(f"/api/cases/{CASE}/executions").status_code == 403
    assert client.get(f"/api/cases/{CASE}/remediation").status_code == 403


# --- dispute and controls ---


def test_dispute_progresses_while_plan_unsent_and_sending_the_plan_does_not_reset_it(
    client: TestClient, db: Session, approved: dict[str, Any]
) -> None:
    issue(client)
    assert step(client) in AFTER_ISSUE
    assert ok(client, "prepare_dispute_packet")["result"]["dispute_status"] == "prepared"
    assert ok(client, "open_dispute_packet")["result"]["dispute_status"] == "opened"
    early = send(client, "submit_dispute")
    assert early.status_code == 409 and early.json()["code"] == "invalid_step"
    ok(client, "propose_card_controls", {"controls": ["replace", "lock"]})
    rem = client.get(f"/api/cases/{CASE}/remediation").json()
    assert rem["dispute"]["status"] == "opened"  # not reset by sending the plan
    assert rem["controls"]["status"] == "proposed" and rem["controls"]["controls"] == [
        "lock",
        "replace",
    ]
    assert step(client) == ("dispute_prepared", "dsp_review")
    ok(client, "review_dispute_packet")
    ok(client, "submit_dispute")
    assert step(client) == ("credit_issued", "waitctl")  # dispute done, waiting on card admin
    none = send(client, "propose_card_controls", {"controls": []})
    assert none.status_code == 422


def test_failed_dispute_submission_retries_to_one_submission(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, "dispute")
    issue(client)
    ok(client, "skip_card_controls", {"reason": "Card already replaced"})
    assert step(client) == ("dispute_prepared", "dsp_prepare")
    for command, status, at in (
        ("prepare_dispute_packet", "prepared", "dsp_open"),
        ("open_dispute_packet", "opened", "dsp_review"),
        ("review_dispute_packet", "reviewed", "dsp_submit"),
    ):
        assert ok(client, command)["result"]["dispute_status"] == status
        assert step(client) == ("dispute_prepared", at)
    adapters.inject_fault(db, "dispute", "submit", "fail", 1)
    db.commit()
    assert ok(client, "submit_dispute")["result"]["dispute_status"] == "failed"
    assert step(client) == ("dispute_prepared", "dsp_failed") and calls.n == 0
    done = ok(client, "submit_dispute")["result"]
    assert done["dispute_status"] == "submitted" and done["submission_id"] == "DSPSUB-1042"
    assert calls.n == 1
    assert step(client) == ("remediation_pending", "finalprep")  # controls skipped, dispute done
    assert count(db, "select count(*) from audit_events where type='dispute.submitted'") == 1
    types = [
        r[0]
        for r in db.execute(
            text("select type from audit_events where type like 'dispute.%' order by id")
        )
    ]
    assert types == [
        "dispute.prepared",
        "dispute.opened",
        "dispute.reviewed",
        "dispute.submission_requested",
        "dispute.submission_requested",
        "dispute.submitted",
    ]
    assert money.dispute_summary(db, CASE).status == "submitted"


def test_uncertain_dispute_submission_is_resolved_by_lookup_without_resending(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, "dispute")
    issue(client)
    ok(client, "skip_card_controls", {"reason": "Card already replaced"})
    for command in ("prepare_dispute_packet", "open_dispute_packet", "review_dispute_packet"):
        ok(client, command)
    adapters.inject_fault(db, "dispute", "submit", "uncertain", 1)
    db.commit()
    assert ok(client, "submit_dispute")["result"]["execution_status"] == "uncertain"
    assert step(client) == ("dispute_prepared", "dsp_failed")
    assert "lookup_execution_result" in offered(client)
    key = db.execute(
        text("select idempotency_key from adapter_executions where adapter='dispute'")
    ).scalar_one()
    found = ok(client, "lookup_execution_result", {"idempotency_key": key})["result"]
    assert found["dispute_status"] == "submitted" and found["submission_id"] == "DSPSUB-1042"
    assert calls.n == 1
    assert step(client) == ("remediation_pending", "finalprep")
    assert money.dispute_summary(db, CASE).status == "submitted"


def test_uncertain_controls_apply_is_resolved_by_lookup_without_reapplying(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, "card_controls")
    issue(client)
    ok(client, "propose_card_controls", {"controls": ["lock"]})
    switch(client, Role.CARD_ADMIN)
    ok(client, "approve_card_controls")
    adapters.inject_fault(db, "card_controls", "apply", "uncertain", 1)
    db.commit()
    assert ok(client, "apply_card_controls")["result"]["execution_status"] == "uncertain"
    assert count(db, "select count(*) from card_controls") == 0
    switch(client, Role.ANALYST)
    key = db.execute(
        text("select idempotency_key from adapter_executions where adapter='card_controls'")
    ).scalar_one()
    found = ok(client, "lookup_execution_result", {"idempotency_key": key})["result"]
    assert found["controls_status"] == "applied" and found["applied"] == ["lock"]
    assert calls.n == 1
    assert count(db, "select count(*) from card_controls") == 1
    assert money.controls_summary(db, CASE).status == "applied"


def test_card_admin_approves_and_applies_once_and_other_roles_get_403(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = Calls(monkeypatch, "card_controls")
    issue(client)
    ok(client, "propose_card_controls", {"controls": ["lock"]})
    for role in (Role.ANALYST, Role.REVIEWER):
        switch(client, role)
        for command in ("approve_card_controls", "apply_card_controls"):
            resp = send(client, command)
            assert resp.status_code == 403 and resp.json()["code"] == "role_forbidden"
    switch(client, Role.CARD_ADMIN)
    early = send(client, "apply_card_controls")  # apply before approve
    assert early.status_code == 409 and calls.n == 0
    ok(client, "approve_card_controls")
    v = view(client)["case_version"]
    first = send(client, "apply_card_controls", version=v)
    again = send(client, "apply_card_controls", version=v)
    assert first.status_code == 200 and again.status_code == 200
    assert first.json()["result"]["applied"] == ["lock"]
    assert again.json()["status"] == "replayed" and again.json()["result"] == first.json()["result"]
    assert calls.n == 1
    assert count(db, "select count(*) from card_controls") == 1
    assert send(client, "apply_card_controls").status_code == 409  # new key: already applied
    assert money.controls_summary(db, CASE).applied == ["lock"]
    rows = db.execute(
        text(
            "select type, actor_id, actor_role from audit_events "
            "where type in ('controls.approved', 'controls.applied') order by id"
        )
    ).all()
    assert [tuple(r) for r in rows] == [
        ("controls.approved", "usr-dana-okafor", "card_admin"),
        ("controls.applied", "usr-dana-okafor", "card_admin"),
    ]
    # both tracks: controls applied, dispute not started -> analyst's dispute step
    assert step(client) == ("dispute_prepared", "dsp_prepare")


def test_work_on_chg_1042_creates_nothing_on_chg_1051(
    client: TestClient, db: Session, approved: dict[str, Any]
) -> None:
    sql = "select case_version from cases where id='CHG-1051'"
    before = count(db, sql)
    issue(client)
    ok(client, "propose_card_controls", {"controls": ["lock"]})
    ok(client, "prepare_dispute_packet")
    for table in ("provisional_credits", "dispute_packets", "control_plans", "adapter_executions"):
        assert count(db, f"select count(*) from {table} where case_id='CHG-1051'") == 0
    assert count(db, sql) == before
    mine = "type like 'credit.%' or type like 'controls.%' or type like 'dispute.%'"
    events = f"select count(*) from audit_events where case_id='CHG-1051' and ({mine})"
    assert count(db, events) == 0
    assert count(db, "select credit_cents from cases where id='CHG-1051'") == 0
    assert money.credit_summary(db, "CHG-1051").status == "none"


def test_planner_recommendation_is_a_service_command_and_the_analyst_decides(
    client: TestClient, db: Session, approved: dict[str, Any]
) -> None:
    from vera_api.auth import Actor
    from vera_domain.clock import default_demo_clock

    issue(client)
    assert "recommend_card_controls" not in REGISTRY
    planner = Actor(
        "prevention_planner", "Prevention Planner", Role.SPECIALIST, frozenset({Role.SPECIALIST})
    )
    v = view(client)["case_version"]
    gateway.execute_command(
        db,
        now=default_demo_clock().now(),
        case_id=CASE,
        command="recommend_card_controls",
        key=f"ctl-rec:{CASE}:{v}",
        expected_version=v,
        payload={"controls": ["lock", "monitor"], "reason": "Card number exposed"},
        actor=planner,
        request_id="t",
    )
    assert step(client) == ("credit_issued", "controls")  # plan prepared, not sent
    assert money.controls_summary(db, CASE).status == "recommended"
    assert {"propose_card_controls", "skip_card_controls", "prepare_dispute_packet"} <= offered(
        client
    )
    ok(client, "prepare_dispute_packet")  # dispute moves while the plan is unsent
    assert money.controls_summary(db, CASE).status == "recommended"
    ok(client, "skip_card_controls", {"reason": "Card already replaced"})
    assert money.controls_summary(db, CASE).status == "skipped"
    assert step(client) == ("dispute_prepared", "dsp_open")


# --- prevention planner specialist ---

PLAN_REC = Path("evals/recordings/prevention_planner/v1")


def _plan_run(db: Session, mode: ExecutionMode) -> str:
    from vera_api.runner import create_run

    db.execute(text("delete from jobs where kind <> 'prevention_planner'"))
    run_id = create_run(db, case_id=CASE, mode=mode, now=datetime(2031, 1, 1, tzinfo=UTC))
    db.commit()
    return run_id


def _drain(db: Session) -> None:
    n = 0
    while worker.run_once(db, worker_id="t") is not None:
        n += 1
        assert n < 10


def _planner_stub() -> httpx.MockTransport:
    turns = [json.loads((PLAN_REC / f).read_text()) for f in (f"{CASE}.json", f"{CASE}.1.json")]
    seen = [0]

    def handle(request: httpx.Request) -> httpx.Response:
        turn = turns[min(seen[0], 1)]
        seen[0] += 1
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
            200, json={"model": "stub/live-model", "choices": [{"message": message}]}
        )

    return httpx.MockTransport(handle)


def _assert_recommended(client: TestClient, db: Session) -> None:
    plan = money.controls_summary(db, CASE)
    assert plan.status == "recommended" and plan.controls == ["block", "lock"]
    assert step(client)[1] == "controls"  # humans decide: propose or skip
    assert "propose_card_controls" in offered(client)
    actor = db.execute(
        text("select actor_id from audit_events where type='controls.recommended'")
    ).scalar_one()
    assert actor == "specialist:prevention_planner"


def test_prevention_planner_replay_recommends_grounded_controls_after_credit(
    client: TestClient, db: Session, approved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from vera_api import investigation

    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", Path("evals/recordings"))
    _plan_run(db, ExecutionMode.REPLAY)
    issue(client)
    assert count(db, "select count(*) from jobs where kind='prevention_planner'") == 1
    _drain(db)
    _assert_recommended(client, db)
    row = db.execute(
        text("select model_id, status from workflow_steps where step_key='prevention_planner'")
    ).one()
    assert tuple(row) == ("reference-recording", "succeeded")


def test_prevention_planner_live_over_mock_transport(
    client: TestClient,
    db: Session,
    approved: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from vera_api import investigation

    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(investigation, "RECORDINGS_ROOT", tmp_path / "empty")
    monkeypatch.setattr(investigation, "LIVE_TRANSPORT", _planner_stub())
    _plan_run(db, ExecutionMode.LIVE)
    issue(client)
    _drain(db)
    _assert_recommended(client, db)
    row = db.execute(
        text("select model_id from workflow_steps where step_key='prevention_planner'")
    ).scalar_one()
    assert row == "stub/live-model"
