"""The financial-action invariant, attacked end to end on Postgres.

A provisional credit, a dispute submission or a card-control application may run only while the
approval it relies on is bound to the case's CURRENT evidence snapshot, policy version, workflow
version and transaction, the action and its amount match what was approved, the actor holds the
role, and the policy is eligible. Every test drives the real gateway (HTTP or execute_command) on
the synthetic CHG-1042 seed through the shared journeys in evals/fragments; nothing below fakes a
state transition. SQL is used only to set up conditions no product command can create (a case
re-pinned to another policy or workflow version) and to read what was persisted.

For each refused attempt the tests assert: the refusal code, no credit/dispute/control effect
persisted, no successful adapter execution, no state transition or version change, and the audit
record that explains the refusal (the invalidating event). A refused command itself writes
nothing, by design of the gateway.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from evals import harness
from evals.harness import World, play

CASE = "CHG-1042"


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    with harness.world() as w:
        yield w


def reach(w: World, fragment: str, *extra: dict[str, Any]) -> None:
    """Fresh seed, then the golden journey up to `fragment` (evals/fragments/gNN_*.json)."""
    w.reset()
    play(w, "approval-invariant", [{"fragment": fragment}, *extra])


def q(w: World, sql: str, **params: Any) -> list[Any]:
    return [tuple(r) for r in w.q(sql, **params)]


def money_effects(w: World) -> dict[str, Any]:
    """Everything that would show a financial effect or a transition."""
    return {
        "credits_issued": q(w, "select count(*) from provisional_credits where status='issued'"),
        "adapter_ok": q(
            w,
            "select adapter, operation, count(*) from adapter_executions where status='succeeded'"
            " and adapter in ('credit','dispute','card_controls') group by 1,2 order by 1,2",
        ),
        "dispute": q(w, "select status from dispute_packets"),
        "controls": q(w, "select status from control_plans"),
        "case": q(w, "select state, step, case_version from cases where id=:c", c=CASE),
        "transitions": q(w, "select count(*) from state_transitions where case_id=:c", c=CASE),
        "events": q(w, "select count(*) from audit_events"),
        "idempotency": q(w, "select count(*) from idempotency_keys"),
    }


def post(
    w: World,
    role: str,
    command: str,
    payload: dict[str, Any] | None = None,
    key: str | None = None,
    version: int | None = None,
) -> Any:
    """POST a command as the UI would, or with a caller-chosen key/version (API bypass)."""
    w.switch(role)
    view = w.view()
    action = harness._find_action(view, command)
    body = {
        "idempotency_key": key or (action["idempotency_key"] if action else "bypass:" + command),
        "expected_case_version": view["case_version"] if version is None else version,
        "payload": {**(action or {}).get("payload_defaults", {}), **(payload or {})},
    }
    return w.client.post(f"/api/cases/{CASE}/commands/{command}", json=body)


def offered(w: World, role: str, command: str) -> bool:
    w.switch(role)
    return harness._find_action(w.view(), command) is not None


def events(w: World, *types: str) -> list[str]:
    rows = w.q(
        "select type from audit_events where case_id=:c and type = any(:t) order by id",
        c=CASE,
        t=list(types),
    )
    return [r[0] for r in rows]


def refused(w: World, resp: Any, code: str, before: dict[str, Any]) -> None:
    assert resp.status_code in (403, 409, 422), resp.text
    assert resp.json()["code"] == code, resp.text
    assert money_effects(w) == before, "a refused attempt changed persisted state"


def material_change(w: World, record: str = "DLV-882", fields: dict[str, Any] | None = None) -> Any:
    r = w.client.post("/api/demo/material-change", json={"record_id": record, "fields": fields})
    assert r.status_code == 200, r.text
    return r.json()


# ---- 1. happy path -------------------------------------------------------------------------


def test_1_valid_approval_issues_the_credit_exactly_once(world: World) -> None:
    reach(world, "g09_approve")
    world.switch("analyst")
    view = world.view()
    action = harness._find_action(view, "issue_provisional_credit")
    assert action is not None
    body = {
        "idempotency_key": action["idempotency_key"],
        "expected_case_version": view["case_version"],
        "payload": {},
    }
    url = f"/api/cases/{CASE}/commands/issue_provisional_credit"
    first = world.client.post(url, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["result"]["credit_status"] == "issued"
    again = world.client.post(url, json=body)  # the same request replays; no second credit
    assert again.status_code == 200 and again.json()["status"] == "replayed", again.text
    assert money_effects(world)["credits_issued"] == [(1,)]
    assert money_effects(world)["adapter_ok"] == [("credit", "issue", 1)]
    consumed = q(world, "select status, consumed_execution_id is not null from approvals")
    assert consumed == [("approved", True)]
    assert events(world, "credit.issued") == ["credit.issued"]


# ---- 2. stale evidence ---------------------------------------------------------------------


def test_2_evidence_change_after_approval_blocks_the_credit(world: World) -> None:
    reach(world, "g09_approve")
    material_change(world)
    assert q(world, "select status from approvals") == [("stale",)]
    assert events(world, "approval.stale") == ["approval.stale"]
    assert not offered(world, "analyst", "issue_provisional_credit")
    before = money_effects(world)
    refused(world, post(world, "analyst", "issue_provisional_credit"), "invalid_step", before)
    # the reviewer cannot rubber-stamp the old approval either
    refused(world, post(world, "reviewer", "approve_decision"), "approval_stale", before)


# ---- 3. policy version ---------------------------------------------------------------------


def test_3_case_repinned_to_another_policy_version_blocks_the_credit(world: World) -> None:
    """No product command re-pins a live case (new versions apply to new cases); this simulates
    an operator re-pin and proves the gate refuses an approval made under the old version."""
    reach(world, "g09_approve")
    with world.factory() as s:
        s.execute(text("update cases set policy_version=2 where id=:c"), {"c": CASE})
        s.commit()
    before = money_effects(world)
    refused(world, post(world, "analyst", "issue_provisional_credit"), "policy_blocked", before)


# ---- 4. workflow version -------------------------------------------------------------------


def test_4_case_repinned_to_another_workflow_version_blocks_the_credit(world: World) -> None:
    reach(world, "g09_approve")
    with world.factory() as s:
        s.execute(text("update cases set workflow_version=4 where id=:c"), {"c": CASE})
        s.commit()
    w = world
    w.switch("analyst")
    blocked = {b["command"]: b["blocked_reason"] for b in w.view()["blocked_actions"]}
    assert "issue_provisional_credit" not in {a["command"] for a in w.view()["available_actions"]}
    assert "out of date" in blocked.get("issue_provisional_credit", "out of date")
    before = money_effects(world)
    refused(world, post(world, "analyst", "issue_provisional_credit"), "approval_stale", before)


# ---- 5. unauthorized actor -----------------------------------------------------------------


@pytest.mark.parametrize("role", ["reviewer", "card_admin", "cardholder", "ops_admin"])
def test_5_only_the_analyst_can_execute_an_approved_credit(world: World, role: str) -> None:
    reach(world, "g09_approve")
    before = money_effects(world)
    refused(world, post(world, role, "issue_provisional_credit"), "role_forbidden", before)


# ---- 6. direct API bypass ------------------------------------------------------------------


def test_6_posting_a_hidden_action_directly_is_refused(world: World) -> None:
    reach(world, "g09_approve")
    world.switch("analyst")
    ui_key = harness._find_action(world.view(), "issue_provisional_credit")["idempotency_key"]
    material_change(world)
    assert not offered(world, "analyst", "issue_provisional_credit")
    before = money_effects(world)
    # with the key the UI showed before the change, and with a guessed current key
    for key in (ui_key, f"credit:{CASE}:{before['case'][0][2]}"):
        refused(
            world,
            post(world, "analyst", "issue_provisional_credit", key=key),
            "invalid_step",
            before,
        )


# ---- 7. replay -----------------------------------------------------------------------------


def test_7_replaying_the_approval_after_invalidation_moves_no_money(world: World) -> None:
    reach(world, "g08_request_approval")
    w = world
    w.switch("reviewer")
    approve = harness._find_action(w.view(), "approve_decision")
    assert approve is not None
    body = {
        "idempotency_key": approve["idempotency_key"],
        "expected_case_version": w.view()["case_version"],
        "payload": {},
    }
    assert (
        w.client.post(f"/api/cases/{CASE}/commands/approve_decision", json=body).status_code == 200
    )
    material_change(world)
    before = money_effects(world)
    replay = w.client.post(f"/api/cases/{CASE}/commands/approve_decision", json=body)
    # the key replays its recorded answer and changes nothing; the approval stays stale
    assert replay.status_code == 200 and replay.json()["status"] == "replayed"
    assert q(world, "select status from approvals") == [("stale",)]
    after = money_effects(world)
    assert {k: v for k, v in after.items() if k != "idempotency"} == {
        k: v for k, v in before.items() if k != "idempotency"
    }
    refused(world, post(world, "analyst", "issue_provisional_credit"), "invalid_step", after)


def test_7b_failed_credit_retry_after_invalidation_never_reaches_the_adapter(world: World) -> None:
    reach(world, "g09_approve")
    world.client.post(
        "/api/demo/adapter-fault",
        json={"adapter": "credit", "operation": "issue", "mode": "fail", "times": 1},
    )
    first = post(world, "analyst", "issue_provisional_credit")
    assert first.json()["result"]["credit_status"] == "failed"
    material_change(world)
    before = money_effects(world)
    refused(world, post(world, "analyst", "issue_provisional_credit"), "invalid_step", before)
    assert q(world, "select status, attempts from adapter_executions where adapter='credit'") == [
        ("failed", 1)
    ]


# ---- 8. concurrency ------------------------------------------------------------------------


def _hold_case_lock_then(w: World, work: Any) -> Any:
    """Start `work` in another thread while this thread holds CHG-1042's row lock, wait until
    that thread is blocked on the lock, then run the material change through the gateway in the
    lock-holding session (which commits and releases). Returns the thread's HTTP response."""
    from vera_api import gateway
    from vera_api.auth import Actor
    from vera_domain.enums import Role

    out: dict[str, Any] = {}
    with w.factory() as s:
        s.execute(text("select 1 from cases where id=:c for update"), {"c": CASE})
        t = threading.Thread(target=lambda: out.setdefault("resp", work()))
        t.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:  # the other request is now waiting on our lock
            waiting = s.execute(
                text(
                    "select count(*) from pg_locks where not granted and locktype in "
                    "('transactionid','tuple','relation')"
                )
            ).scalar()
            if waiting:
                break
            time.sleep(0.05)
        version = s.execute(
            text("select case_version from cases where id=:c"), {"c": CASE}
        ).scalar()
        system = Actor("svc-source-system", "Source system", Role.SYSTEM, frozenset({Role.SYSTEM}))
        gateway.execute_command(
            s,
            now=datetime(2026, 11, 10, 17, 30, tzinfo=UTC),
            case_id=CASE,
            command="append_evidence_version",
            key=f"evver:{CASE}:DLV-882:{version}",
            expected_version=int(version or 0),
            payload={
                "record_id": "DLV-882",
                "fields": {"received_quantity": 1},
                "source": "delivery system (race)",
            },
            actor=system,
            request_id="race",
        )
        t.join(30)
    return out["resp"]


def test_8_invalidation_racing_the_credit_never_commits_against_a_stale_approval(
    world: World,
) -> None:
    reach(world, "g09_approve")
    world.switch("analyst")
    view = world.view()
    action = harness._find_action(view, "issue_provisional_credit")
    assert action is not None
    body = {
        "idempotency_key": action["idempotency_key"],
        "expected_case_version": view["case_version"],
        "payload": {},
    }
    resp = _hold_case_lock_then(
        world,
        lambda: world.client.post(
            f"/api/cases/{CASE}/commands/issue_provisional_credit", json=body
        ),
    )
    # the credit waited for the lock, then saw the new evidence: no credit, no adapter call
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] in ("stale_case_version", "invalid_step")
    assert money_effects(world)["credits_issued"] == [(0,)]
    assert money_effects(world)["adapter_ok"] == []
    assert q(world, "select status from approvals") == [("stale",)]


def test_8b_credit_committed_first_consumes_the_approval_and_stays_valid(world: World) -> None:
    """The other order: the credit commits under the approval, then the evidence changes. The
    approval was consumed by that execution and is never re-marked stale afterwards."""
    reach(world, "g10_credit")
    material_change(world)
    assert q(world, "select status, consumed_at is not null from approvals") == [("approved", True)]
    assert money_effects(world)["credits_issued"] == [(1,)]


# ---- 9. recovery ---------------------------------------------------------------------------


def test_9_reevaluation_and_fresh_approval_authorize_the_credit_once(world: World) -> None:
    reach(world, "g09_approve")
    material_change(world)
    for role, cmd, payload in (("analyst", "create_decision_packet", None),):
        assert post(world, role, cmd, payload).status_code == 200
    world.drain()
    for role, cmd, payload in (
        ("analyst", "record_decision", {"decision": "credit", "rationale": "Re-reviewed."}),
        ("analyst", "request_reviewer_approval", None),
        ("reviewer", "approve_decision", None),
        ("analyst", "issue_provisional_credit", None),
    ):
        r = post(world, role, cmd, payload)
        assert r.status_code == 200, (cmd, r.text)
    rows = q(world, "select id, status, consumed_at is not null from approvals order by id")
    assert rows == [("APR-CHG-1042-1", "stale", False), ("APR-CHG-1042-2", "approved", True)]
    snap = q(world, "select evidence_snapshot from cases where id=:c", c=CASE)[0][0]
    assert q(world, "select snapshot_hash from approvals where id='APR-CHG-1042-2'")[0][0] == snap
    assert money_effects(world)["credits_issued"] == [(1,)]
    assert money_effects(world)["adapter_ok"] == [("credit", "issue", 1)]


# ---- gaps found by the audit ---------------------------------------------------------------


def _service(w: World, command: str, payload: dict[str, Any], key: str) -> None:
    from vera_api import gateway
    from vera_api.auth import Actor
    from vera_domain.enums import Role

    with w.factory() as s:
        version = s.execute(
            text("select case_version from cases where id=:c"), {"c": CASE}
        ).scalar()
        s.rollback()
        gateway.execute_command(
            s,
            now=datetime(2026, 11, 10, 17, 30, tzinfo=UTC),
            case_id=CASE,
            command=command,
            key=key,
            expected_version=int(version or 0),
            payload=payload,
            actor=Actor("svc-specialist", "svc", Role.SPECIALIST, frozenset({Role.SPECIALIST})),
            request_id="late-specialist",
        )


def test_gap_a_late_conflict_finding_after_approval_invalidates_it(world: World) -> None:
    """A specialist job that lands after approval records a new open conflict. The snapshot must
    reflect it, the approval must go stale, and the credit must be refused."""
    reach(world, "g09_approve")
    _service(
        world,
        "record_finding",
        {
            "finding_id": "FND-late-1",
            "kind": "conflict",
            "conflict_field": "amount",
            "statement": "A late check found the charged amount disagrees with the order.",
            "links": [
                {"record_id": "CHG-1042", "version": 1, "field": "amount_cents"},
                {"record_id": "PO-219", "version": 1, "field": "approved_amount_cents"},
            ],
        },
        "finding:FND-late-1",
    )
    assert q(world, "select status from approvals") == [("stale",)]
    assert "approval.stale" in events(world, "approval.stale")
    before = money_effects(world)
    refused(world, post(world, "analyst", "issue_provisional_credit"), "invalid_step", before)


def test_gap_b_review_status_change_after_approval_invalidates_it(world: World) -> None:
    """A late review puts the accepted receipt back to pending review after the approval: the
    approval goes stale (with its audit event) instead of staying 'approved' on old evidence."""
    reach(world, "g09_approve")
    receipt = q(world, "select id from evidence_records where kind='receipt'")[0][0]
    _service(
        world,
        "set_record_status",
        {
            "record_id": receipt,
            "status": "pending_review",
            "reason": "Late review: receipt total unreadable",
        },
        f"recstatus:{CASE}:{receipt}:pending_review",
    )
    assert q(world, "select status from approvals") == [("stale",)]
    assert events(world, "approval.stale") == ["approval.stale"]
    before = money_effects(world)
    refused(world, post(world, "analyst", "issue_provisional_credit"), "invalid_step", before)


def test_gap_c_dispute_cannot_be_submitted_on_a_packet_reviewed_before_the_evidence_changed(
    world: World,
) -> None:
    reach(world, "g10_credit")
    for cmd in ("prepare_dispute_packet",):
        assert post(world, "analyst", cmd).status_code == 200
    world.drain()
    for cmd in ("open_dispute_packet", "review_dispute_packet"):
        assert post(world, "analyst", cmd).status_code == 200
    material_change(world)
    before = money_effects(world)
    refused(world, post(world, "analyst", "submit_dispute"), "dispute_review_stale", before)
    # reviewing the packet again on the current evidence re-authorizes the submission
    assert post(world, "analyst", "review_dispute_packet").status_code == 200
    assert post(world, "analyst", "submit_dispute").status_code == 200
    assert money_effects(world)["adapter_ok"] == [("credit", "issue", 1), ("dispute", "submit", 1)]


def test_gap_d_card_controls_cannot_apply_on_an_approval_given_before_the_evidence_changed(
    world: World,
) -> None:
    reach(world, "g10_credit")
    assert (
        post(world, "analyst", "propose_card_controls", {"controls": ["lock"]}).status_code == 200
    )
    assert post(world, "card_admin", "approve_card_controls").status_code == 200
    material_change(world)
    before = money_effects(world)
    refused(
        world, post(world, "card_admin", "apply_card_controls"), "controls_approval_stale", before
    )
    assert post(world, "card_admin", "approve_card_controls").status_code == 200
    assert post(world, "card_admin", "apply_card_controls").status_code == 200


def test_gap_e_the_credit_effect_refuses_on_its_own_even_if_the_gates_were_skipped(
    world: World,
) -> None:
    """write_command (stage 9) re-runs only the closed/step gates. The credit effect must not
    rely on its caller having run stages 7-8: with a mismatched binding it refuses by itself."""
    from vera_api import gateway
    from vera_domain.commands import REGISTRY
    from vera_domain.errors import CommandError

    reach(world, "g09_approve")
    with world.factory() as s:
        s.execute(text("update cases set workflow_version=4 where id=:c"), {"c": CASE})
        s.commit()
    before = money_effects(world)
    spec = REGISTRY["issue_provisional_credit"]
    with world.factory() as s:
        case = gateway._lock_case(s, CASE)
        with pytest.raises(CommandError) as err:
            gateway.write_command(
                s,
                case,
                spec,
                spec.payload_model.model_validate({}),
                key="internal-caller",
                req_hash="x",
                actor_id="usr-sam-rivera",
                actor_name="Sam Rivera",
                actor_role=spec.roles.__iter__().__next__(),
                request_id="internal",
                now=datetime(2026, 11, 10, 17, 30, tzinfo=UTC),
            )
        s.rollback()
    assert err.value.code == "approval_stale"
    assert money_effects(world) == before
