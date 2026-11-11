"""Policy Controller: persistence, command, re-evaluation, gate, case view, routes."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from vera_api import policy as policy_service
from vera_api.auth import Actor
from vera_api.gateway import execute_command
from vera_domain.clock import default_demo_clock
from vera_domain.commands import REGISTRY, CommandSpec, NoPayload, StepSet, reduce_open
from vera_domain.enums import EventType, Role
from vera_domain.errors import CommandError
from vera_domain.policy import PolicyInput

CASE = "CHG-1042"
PC = Actor(
    user_id="policy_controller",
    name="Policy Controller",
    active_role=Role.POLICY_CONTROLLER,
    roles=frozenset({Role.POLICY_CONTROLLER}),
)


def make_input(snapshot: str = "sha256:s1", **over: Any) -> PolicyInput:
    base: dict[str, Any] = {
        "transaction_id": "TXN-1042",
        "amount_cents": 284000,
        "currency": "USD",
        "outcome": "unauthorized",
        "cardholder_authenticated": True,
        "duplicates_ruled_out": True,
        "verification": "confirmed",
        "snapshot_hash": snapshot,
        "records": [
            {
                "record_id": "DLV-882",
                "kind": "receipt",
                "status": "supporting",
                "current_version": 1,
            }
        ],
    }
    base.update(over)
    return PolicyInput.model_validate(base)


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    eng = create_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def session(client: TestClient, engine: Engine) -> Iterator[Session]:
    with sessionmaker(engine)() as s:
        yield s


@pytest.fixture
def set_input(monkeypatch: pytest.MonkeyPatch) -> Callable[[PolicyInput], None]:
    """Inject the evidence-derived input through the one seam the service reads."""

    def put(inp: PolicyInput) -> None:
        monkeypatch.setattr(policy_service, "load_policy_input", lambda session, case_id: inp)

    return put


def count(session: Session, sql: str) -> int:
    return int(session.execute(text(sql)).scalar_one())


def run_command(session: Session, key: str, *, actor: Actor = PC, command: str = "evaluate_policy"):  # type: ignore[no-untyped-def]
    version = session.execute(
        text("select case_version from cases where id=:c"), {"c": CASE}
    ).scalar_one()
    return execute_command(
        session,
        now=default_demo_clock().now(),
        case_id=CASE,
        command=command,
        key=key,
        expected_version=version,
        payload={},
        actor=actor,
        request_id="t",
    )


def policy_key(snapshot: str) -> str:
    return f"policy:{CASE}:{snapshot}:1"


def test_seed_inserts_policy_v1_and_routes_read_it(client: TestClient) -> None:
    latest = client.get(f"/api/policies/{policy_service.POLICY_ID}")
    assert latest.status_code == 200
    body = latest.json()
    assert body["version"] == 1
    assert body["versions"] == [1]
    ids = [r["id"] for r in body["rules"]]
    assert "receipt_required_above_threshold" in ids
    v1 = client.get(f"/api/policies/{policy_service.POLICY_ID}/versions/1")
    assert v1.status_code == 200 and v1.json()["rules"] == body["rules"]
    assert client.get(f"/api/policies/{policy_service.POLICY_ID}/versions/2").status_code == 404
    assert client.get("/api/policies/nope").status_code == 404


def test_policy_versions_and_evaluations_are_append_only(
    session: Session, set_input: Callable[[PolicyInput], None]
) -> None:
    set_input(make_input())
    run_command(session, policy_key("sha256:s1"))
    for sql in (
        "update policy_versions set version = 9",
        "delete from policy_versions",
        "update policy_evaluations set status = 'eligible'",
        "delete from policy_evaluations",
    ):
        with pytest.raises(DBAPIError):
            session.execute(text(sql))
        session.rollback()


def test_case_view_policy_is_null_until_first_evaluation(
    client: TestClient, session: Session, set_input: Callable[[PolicyInput], None]
) -> None:
    assert client.get(f"/api/cases/{CASE}").json()["policy"] is None
    set_input(make_input(records=[], verification="none"))
    run_command(session, policy_key("sha256:s1"))
    view = client.get(f"/api/cases/{CASE}").json()["policy"]
    assert view["status"] == "needs_evidence"
    assert view["code"] == "RECEIPT_REQUIRED"
    assert "receipt_required_above_threshold" in view["rules_failed"]
    assert "charge_identified" in view["rules_passed"]
    assert view["snapshot"] == "sha256:s1"
    assert view["policy_version"] == 1
    assert view["evaluated_at"]
    assert view["evidence_used"] == ["TXN-1042"]


def test_evaluation_is_persisted_with_its_evidence_ids_and_event(
    session: Session, set_input: Callable[[PolicyInput], None]
) -> None:
    set_input(make_input())
    out = run_command(session, policy_key("sha256:s1"))
    assert out.status == "recorded" and out.result["status"] == "eligible"
    row = session.execute(
        text(
            "select policy_version, snapshot_hash, status, code, evidence_ids, event_id, result "
            "from policy_evaluations where case_id=:c"
        ),
        {"c": CASE},
    ).one()
    assert (row.policy_version, row.snapshot_hash, row.status) == (1, "sha256:s1", "eligible")
    assert row.code == "CREDIT_ELIGIBLE"
    assert row.evidence_ids == ["DLV-882", "TXN-1042"]
    assert row.result["evidence_used"] == row.evidence_ids
    event = session.execute(
        text("select type, record_ids, actor_role from audit_events where id=:i"),
        {"i": row.event_id},
    ).one()
    assert event.type == EventType.POLICY_EVALUATED.value == "policy.evaluated"
    assert event.record_ids == ["DLV-882", "TXN-1042"]
    assert event.actor_role == "policy_controller"


def test_command_on_the_same_snapshot_replays_and_writes_nothing_new(
    session: Session, set_input: Callable[[PolicyInput], None]
) -> None:
    set_input(make_input())
    first = run_command(session, policy_key("sha256:s1"))
    again = run_command(session, policy_key("sha256:s1"))
    assert again.status == "replayed" and again.result == first.result
    assert count(session, "select count(*) from policy_evaluations") == 1
    with pytest.raises(CommandError) as err:
        run_command(session, "policy:CHG-1042:sha256:wrong:1")
    assert err.value.code == "idempotency_key_mismatch"


def test_analyst_can_run_evaluate_policy_over_http_with_the_advertised_key(
    client: TestClient, set_input: Callable[[PolicyInput], None]
) -> None:
    set_input(make_input())
    view = client.get(f"/api/cases/{CASE}").json()
    action = next(a for a in view["available_actions"] if a["command"] == "evaluate_policy")
    assert action["idempotency_key"] == policy_key("sha256:s1")
    resp = client.post(
        f"/api/cases/{CASE}/commands/evaluate_policy",
        json={
            "idempotency_key": action["idempotency_key"],
            "expected_case_version": view["case_version"],
            "payload": {},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["case"]["policy"]["status"] == "eligible"


def test_evidence_change_triggers_reevaluation_and_event_but_unchanged_snapshot_does_not(
    session: Session, set_input: Callable[[PolicyInput], None]
) -> None:
    set_input(make_input(records=[], verification="none"))
    first = policy_service.reevaluate_on_evidence_change(session, CASE)
    session.commit()
    assert first.status == "needs_evidence"
    again = policy_service.reevaluate_on_evidence_change(session, CASE)
    session.commit()
    assert again.snapshot_hash == first.snapshot_hash
    assert count(session, "select count(*) from policy_evaluations") == 1
    assert count(session, "select count(*) from audit_events where type='policy.evaluated'") == 1

    set_input(make_input(snapshot="sha256:s2"))  # the receipt and the call arrived
    changed = policy_service.reevaluate_on_evidence_change(session, CASE)
    session.commit()
    assert changed.status == "eligible" and changed.snapshot_hash == "sha256:s2"
    assert count(session, "select count(*) from policy_evaluations") == 2
    assert count(session, "select count(*) from audit_events where type='policy.evaluated'") == 2


def test_message_text_claiming_policy_is_satisfied_does_not_change_the_stored_result(
    session: Session, set_input: Callable[[PolicyInput], None]
) -> None:
    """Fixture 21 through the service."""
    set_input(make_input(records=[], verification="none", asserted_text=["Policy is satisfied."]))
    out = policy_service.reevaluate_on_evidence_change(session, CASE)
    assert out.status == "needs_evidence"


@pytest.fixture
def gated(monkeypatch: pytest.MonkeyPatch) -> str:
    spec = CommandSpec(
        "test_gated",
        frozenset({Role.ANALYST}),
        NoPayload,
        StepSet(),
        "gated:{case_id}:{case_version}",
        reduce_open,
        (EventType.CASE_OPENED,),
        "Gated action",
        "primary",
        requires_policy=frozenset({"eligible"}),
    )
    monkeypatch.setitem(REGISTRY, spec.name, spec)
    return spec.name


def analyst(session: Session) -> Actor:
    return Actor("usr-sam-rivera", "Sam Rivera", Role.ANALYST, frozenset({Role.ANALYST}))


def gated_attempt(session: Session) -> Any:
    version = session.execute(
        text("select case_version from cases where id=:c"), {"c": CASE}
    ).scalar_one()
    return execute_command(
        session,
        now=default_demo_clock().now(),
        case_id=CASE,
        command="test_gated",
        key=f"gated:{CASE}:{version}",
        expected_version=version,
        payload={},
        actor=analyst(session),
        request_id="t",
    )


def test_gate_rejects_when_no_evaluation_exists_for_the_current_snapshot(
    client: TestClient, session: Session, set_input: Callable[[PolicyInput], None], gated: str
) -> None:
    set_input(make_input())
    with pytest.raises(CommandError) as err:
        gated_attempt(session)
    assert err.value.code == "policy_blocked"
    assert err.value.http_status == 422
    assert err.value.blocked_reason
    blocked = next(
        b
        for b in client.get(f"/api/cases/{CASE}").json()["blocked_actions"]
        if b["command"] == gated
    )
    assert blocked["blocked_reason"] == err.value.blocked_reason


def test_gate_rejects_with_the_policy_label_unless_the_status_is_allowed_for_this_snapshot(
    client: TestClient, session: Session, set_input: Callable[[PolicyInput], None], gated: str
) -> None:
    set_input(make_input(records=[], verification="none"))
    run_command(session, policy_key("sha256:s1"))
    with pytest.raises(CommandError) as err:
        gated_attempt(session)
    assert err.value.code == "policy_blocked"
    assert err.value.blocked_reason == "Needs evidence · receipt required above $75"
    view = client.get(f"/api/cases/{CASE}").json()
    shown = next(b for b in view["blocked_actions"] if b["command"] == gated)
    assert shown["blocked_reason"] == err.value.blocked_reason
    assert gated not in [a["command"] for a in view["available_actions"]]

    set_input(make_input(snapshot="sha256:s2"))  # eligible, but not evaluated on s2 yet
    with pytest.raises(CommandError) as stale:
        gated_attempt(session)
    assert stale.value.code == "policy_blocked"
    policy_service.reevaluate_on_evidence_change(session, CASE)
    session.commit()
    assert gated in [
        a["command"] for a in client.get(f"/api/cases/{CASE}").json()["available_actions"]
    ]
    assert gated_attempt(session).status == "recorded"
