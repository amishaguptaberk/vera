"""Policy Controller on real evidence: seed, material-change re-evaluation, conflicts (VER-004)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api.auth import Actor
from vera_api.evidence import get_evidence_summary
from vera_api.gateway import execute_command
from vera_domain.clock import default_demo_clock
from vera_domain.enums import Role
from vera_domain.evidence import SERVICE_REGISTRY

CASE = "CHG-1042"
QTY_CONFLICT = {
    "finding_id": "FND-Q",
    "kind": "conflict",
    "statement": "The purchase order approves one unit but the delivery record shows two.",
    "conflict_field": "quantity",
    "links": [
        {"record_id": "PO-219", "version": 1, "field": "approved_quantity"},
        {"record_id": "DLV-882", "version": 1, "field": "received_quantity"},
    ],
}


@pytest.fixture
def db(client: TestClient, db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


def record_finding(db: Session, payload: dict[str, Any]) -> None:
    version = db.execute(text("select case_version from cases where id=:c"), {"c": CASE}).scalar()
    db.rollback()
    execute_command(
        db,
        now=default_demo_clock().now(),
        case_id=CASE,
        command="record_finding",
        key=SERVICE_REGISTRY["record_finding"].key_template.format(**payload),
        expected_version=version,
        payload=payload,
        actor=Actor("svc-specialist", "svc", Role.SPECIALIST, frozenset({Role.SPECIALIST})),
        request_id="t",
    )


def evaluate(client: TestClient) -> dict[str, Any]:
    """The analyst runs evaluate_policy with the key the case view advertises."""
    view = client.get(f"/api/cases/{CASE}").json()
    action = next(a for a in view["available_actions"] if a["command"] == "evaluate_policy")
    resp = client.post(
        f"/api/cases/{CASE}/commands/evaluate_policy",
        json={
            "idempotency_key": action["idempotency_key"],
            "expected_case_version": view["case_version"],
            "payload": {},
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["case"]["policy"]  # type: ignore[no-any-return]


def count(db: Session, sql: str) -> int:
    db.rollback()
    return int(db.execute(text(sql)).scalar_one())


def test_seeded_case_evaluates_on_real_evidence(client: TestClient, db: Session) -> None:
    policy = evaluate(client)
    assert policy["status"] == "needs_evidence"
    assert "receipt_required_above_threshold" in policy["rules_failed"]
    assert "purchase_records_agree" in policy["rules_passed"]  # no finding is pre-written
    assert {"CHG-1042", "PO-219", "DLV-882"} <= set(policy["evidence_used"])
    assert policy["snapshot"] == get_evidence_summary(db, CASE).snapshot_hash


def test_material_change_reevaluates_policy_in_the_same_transaction(
    client: TestClient, db: Session
) -> None:
    first = evaluate(client)
    resp = client.post("/api/demo/material-change", json={})
    assert resp.status_code == 200, resp.text
    new_hash = resp.json()["after"]["snapshot_hash"]
    assert new_hash != first["snapshot"]
    db.rollback()
    rows = db.execute(
        text("select snapshot_hash from policy_evaluations where case_id=:c order by id"),
        {"c": CASE},
    ).all()
    assert [r[0] for r in rows] == [first["snapshot"], new_hash]
    types = [
        r[0]
        for r in db.execute(
            text("select type from audit_events where case_id=:c order by id"), {"c": CASE}
        )
    ]
    tail = types[types.index("evidence.version_added") :]
    assert tail == ["evidence.version_added", "policy.evaluated"]
    assert client.get(f"/api/cases/{CASE}").json()["policy"]["snapshot"] == new_hash


def test_open_conflict_finding_blocks_policy(client: TestClient, db: Session) -> None:
    record_finding(db, QTY_CONFLICT)
    policy = evaluate(client)
    assert policy["status"] == "blocked"
    assert policy["code"] == "EVIDENCE_CONFLICT"


def test_material_change_without_a_prior_evaluation_creates_none(
    client: TestClient, db: Session
) -> None:
    assert client.post("/api/demo/material-change", json={}).status_code == 200
    assert count(db, "select count(*) from policy_evaluations") == 0
    assert count(db, "select count(*) from audit_events where type='policy.evaluated'") == 0
