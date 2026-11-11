"""Evidence provenance, snapshots, conflicts and the material-change pipeline."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from vera_api.auth import Actor
from vera_api.evidence import (
    STALE_APPROVAL_HOOKS,
    get_evidence_summary,
    read_evidence_field,
)
from vera_api.gateway import execute_command
from vera_domain.clock import default_demo_clock
from vera_domain.enums import Role
from vera_domain.errors import CommandError
from vera_domain.evidence import SERVICE_REGISTRY

CASE = "CHG-1042"


def actor(role: Role) -> Actor:
    return Actor(user_id=f"svc-{role.value}", name="svc", active_role=role, roles=frozenset({role}))


@pytest.fixture
def db(client: TestClient, db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


def run(db: Session, command: str, payload: dict[str, Any], role: Role = Role.SPECIALIST) -> Any:
    version = db.execute(text("select case_version from cases where id=:c"), {"c": CASE}).scalar()
    db.rollback()
    key = SERVICE_REGISTRY[command].key_template.format(
        case_id=CASE, case_version=version, user_id=f"svc-{role.value}", **payload
    )
    return execute_command(
        db,
        now=default_demo_clock().now(),
        case_id=CASE,
        command=command,
        key=key,
        expected_version=version,
        payload=payload,
        actor=actor(role),
        request_id="t",
    )


def snapshot(client: TestClient) -> str:
    return client.get(f"/api/cases/{CASE}/evidence").json()["snapshot_hash"]  # type: ignore[no-any-return]


DLV_V2 = {"record_id": "DLV-882", "fields": {"received_quantity": 1}}

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


def test_fresh_seed_has_source_records_only_and_no_findings(
    client: TestClient, db: Session
) -> None:
    assert db.execute(text("select count(*) from findings")).scalar() == 0
    assert db.execute(text("select count(*) from finding_links")).scalar() == 0
    body = client.get(f"/api/cases/{CASE}/evidence").json()
    by_id = {r["record_id"]: r for r in body["records"]}
    assert by_id["CHG-1051"]["status"] == "pending_review"
    assert by_id["CHG-1048"]["status"] == "pending_review"
    assert by_id["CHG-1051"]["fields"]["amount_cents"] == 120000
    assert by_id["CHG-1048"]["fields"]["amount_cents"] == 62000
    assert by_id["DLV-882"]["status"] == "supporting"
    assert "delivered_to" not in by_id["DLV-882"]["fields"]
    assert by_id["CHG-1042"]["fields"]["posted_at"].startswith("2026-11-08")
    assert body["open_conflicts"] == [] and body["findings"] == []
    assert len(body["checks"]) == 5


def test_register_shows_seeded_records_missing_and_conflicting_as_distinct(
    client: TestClient, db: Session
) -> None:
    run(db, "record_finding", QTY_CONFLICT)
    body = client.get(f"/api/cases/{CASE}/evidence").json()
    by_id = {r["record_id"]: r for r in body["records"]}
    assert set(by_id) == {"CHG-1042", "PO-219", "DLV-882", "REP-1042", "PRF-4418",
                          "CHG-1051", "CHG-1048"}  # fmt: skip
    assert by_id["CHG-1042"]["fields"]["amount_cents"] == 284000
    assert by_id["PO-219"]["fields"]["approved_amount_cents"] == 240000
    assert by_id["DLV-882"]["fields"]["received_quantity"] == 2
    assert by_id["DLV-882"]["status"] == "conflicting"  # PO says 1 unit, delivery says 2
    assert by_id["CHG-1042"]["status"] == "supporting"
    assert by_id["REP-1042"]["status"] == "pending_review"
    assert body["missing"] == ["receipt"]
    assert "receipt" not in by_id  # missing is a kind with no record, not a record status
    assert body["open_conflicts"][0]["field"] == "quantity"
    assert {v["value"] for v in body["open_conflicts"][0]["values"]} == {1, 2}
    pin = client.get(f"/api/cases/{CASE}").json()["pins"]["evidence_snapshot"]
    assert pin == "sha256:" + body["snapshot_hash"]


def test_material_change_marks_conflicts_on_the_superseded_version_stale(
    client: TestClient, db: Session
) -> None:
    run(db, "record_finding", QTY_CONFLICT)
    assert client.post("/api/demo/material-change", json={}).status_code == 200
    body = client.get(f"/api/cases/{CASE}/evidence").json()
    assert body["open_conflicts"] == []
    dlv = next(r for r in body["records"] if r["record_id"] == "DLV-882")
    assert dlv["status"] == "supporting" and dlv["current_version"] == 2
    finding = next(f for f in body["findings"] if f["finding_id"] == "FND-Q")
    assert finding["status"] == "stale"
    db.rollback()
    row = db.execute(
        text("select record_ids from audit_events where type='finding.stale' and case_id=:c"),
        {"c": CASE},
    ).one()
    assert row[0][0] == "FND-Q"


def test_new_findings_and_links_cannot_cite_a_superseded_version(
    client: TestClient, db: Session
) -> None:
    run(db, "record_finding", {**QTY_CONFLICT, "finding_id": "FND-OLD"})
    run(db, "append_evidence_version", {**DLV_V2, "source": "delivery system"}, Role.SYSTEM)
    with pytest.raises(CommandError) as err:
        run(db, "record_finding", {**QTY_CONFLICT, "finding_id": "FND-NEW"})
    assert (err.value.http_status, err.value.code) == (422, "schema_invalid")
    with pytest.raises(CommandError) as err:
        run(
            db,
            "link_evidence",
            {
                "finding_id": "FND-OLD",
                "record_id": "DLV-882",
                "version": 1,
                "field": "received_quantity",
            },  # fmt: skip
        )
    assert (err.value.http_status, err.value.code) == (422, "schema_invalid")


def test_demo_material_change_needs_fields_for_records_other_than_dlv_882(
    client: TestClient,
) -> None:
    resp = client.post("/api/demo/material-change", json={"record_id": "PO-219"})
    assert resp.status_code == 422
    assert client.get(f"/api/cases/{CASE}").json()["case_version"] == 1


def test_material_change_appends_version_supersedes_old_and_stales_only_matching_check(
    client: TestClient, db: Session
) -> None:
    before = snapshot(client)
    out = run(db, "append_evidence_version", {**DLV_V2, "source": "delivery system"}, Role.SYSTEM)
    assert out.result["version"] == 2 and out.result["material"] is True
    assert snapshot(client) != before
    detail = client.get(f"/api/cases/{CASE}/evidence/DLV-882").json()
    assert [(v["version"], v["status"]) for v in detail["versions"]] == [
        (2, "current"),
        (1, "superseded"),
    ]
    assert detail["versions"][1]["fields"]["received_quantity"] == 2  # old version retained
    checks = {
        c["key"]: c["status"] for c in client.get(f"/api/cases/{CASE}/evidence").json()["checks"]
    }
    assert checks["purchase_records"] == "stale"
    assert {k for k, v in checks.items() if v != "stale"} == {
        "receipt_required", "identity", "related_charges", "claim_review",
    }  # fmt: skip
    types = [
        r[0]
        for r in db.execute(
            text("select type from audit_events where case_id=:c order by id"), {"c": CASE}
        )
    ]
    assert types[-1] == "evidence.version_added"
    assert read_evidence_field(db, CASE, "DLV-882", "received_quantity") == (1, 2)


def test_non_material_change_keeps_hash_and_stales_nothing(client: TestClient, db: Session) -> None:
    before = snapshot(client)
    out = run(
        db,
        "append_evidence_version",
        {
            "record_id": "DLV-882",
            "fields": {"received_quantity": 2, "note": "left at dock"},
            "source": "delivery system",
        },
        Role.SYSTEM,
    )
    assert out.result["version"] == 2 and out.result["material"] is False
    assert snapshot(client) == before
    checks = client.get(f"/api/cases/{CASE}/evidence").json()["checks"]
    assert all(c["status"] == "current" for c in checks)


def test_stale_approvals_are_reported_through_the_hook(client: TestClient, db: Session) -> None:
    STALE_APPROVAL_HOOKS.append(lambda session, case, new_hash: ["APR-1042"])
    try:
        run(db, "append_evidence_version", {**DLV_V2, "source": "delivery system"}, Role.SYSTEM)
    finally:
        STALE_APPROVAL_HOOKS.pop()
    row = db.execute(
        text("select record_ids from audit_events where type='approval.stale' and case_id=:c"),
        {"c": CASE},
    ).one()
    assert row[0] == ["APR-1042"]


def test_finding_without_an_existing_source_link_is_rejected(db: Session) -> None:
    base = {"finding_id": "FND-1", "kind": "note", "statement": "No source."}
    for bad in (
        {**base, "links": []},
        {**base, "links": [{"record_id": "NOPE-1", "version": 1, "field": "x"}]},
        {**base, "links": [{"record_id": "DLV-882", "version": 9, "field": "received_quantity"}]},
        {**base, "links": [{"record_id": "DLV-882", "version": 1, "field": "no_such_field"}]},
    ):
        with pytest.raises(CommandError) as err:
            run(db, "record_finding", bad)
        assert err.value.http_status == 422
    assert db.execute(text("select count(*) from findings where id='FND-1'")).scalar() == 0


def test_conflict_finding_is_structured_and_idempotent(client: TestClient, db: Session) -> None:
    payload = {
        "finding_id": "FND-2",
        "kind": "conflict",
        "statement": "Receipt total differs from the purchase order.",
        "conflict_field": "amount",
        "links": [
            {"record_id": "CHG-1042", "version": 1, "field": "amount_cents"},
            {"record_id": "PO-219", "version": 1, "field": "approved_amount_cents"},
        ],
    }
    first = run(db, "record_finding", payload)
    assert first.status == "recorded"
    conflicts = client.get(f"/api/cases/{CASE}/evidence").json()["open_conflicts"]
    mine = next(c for c in conflicts if c["finding_id"] == "FND-2")
    assert mine["record_ids"] == ["CHG-1042", "PO-219"]
    assert [v["value"] for v in mine["values"]] == [284000, 240000]
    again = execute_command(
        db,
        now=default_demo_clock().now(),
        case_id=CASE,
        command="record_finding",
        key="finding:FND-2",
        expected_version=1,
        payload=payload,
        actor=actor(Role.SPECIALIST),
        request_id="t",
    )
    assert again.status == "replayed"
    assert db.execute(text("select count(*) from findings where id='FND-2'")).scalar() == 1


def test_resolved_conflict_is_no_longer_open(client: TestClient, db: Session) -> None:
    run(
        db,
        "record_finding",
        {
            "finding_id": "FND-3",
            "kind": "conflict",
            "statement": "Quantity confirmed by call.",
            "conflict_field": "quantity",
            "status": "resolved",
            "resolved_by": "CALL-1042",
            "links": [
                {"record_id": "PO-219", "version": 1, "field": "approved_quantity"},
                {"record_id": "DLV-882", "version": 1, "field": "received_quantity"},
            ],
        },
    )
    ids = [
        c["finding_id"] for c in client.get(f"/api/cases/{CASE}/evidence").json()["open_conflicts"]
    ]
    assert "FND-3" not in ids


def test_link_evidence_and_record_claim(db: Session) -> None:
    run(db, "record_finding", QTY_CONFLICT)
    run(
        db,
        "link_evidence",
        {
            "finding_id": "FND-Q",
            "record_id": "CHG-1051",
            "version": 1,
            "field": "amount_cents",
        },
    )
    n = db.execute(text("select count(*) from finding_links where finding_id='FND-Q'")).scalar()
    assert n == 3
    run(
        db, "record_claim", {"claim_id": "CLM-1", "report_id": "REP-1042", "statement": "Not mine."}
    )
    assert db.execute(text("select report_id from claims where id='CLM-1'")).scalar() == "REP-1042"


def test_evidence_versions_cannot_be_updated_or_deleted(client: TestClient, db: Session) -> None:
    run(db, "record_finding", QTY_CONFLICT)  # the seed has no finding links to update
    for sql in (
        "update evidence_versions set source='x'",
        "delete from evidence_versions",
        "update finding_links set field='x'",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(sql))
        db.rollback()


def test_specialist_cannot_mutate_a_source_record_and_humans_cannot_run_service_commands(
    client: TestClient, db: Session
) -> None:
    with pytest.raises(CommandError) as err:
        run(db, "append_evidence_version", {**DLV_V2, "source": "me"}, Role.SPECIALIST)
    assert err.value.code == "role_forbidden"
    assert (
        db.execute(
            text("select count(*) from evidence_versions where record_id='DLV-882'")
        ).scalar()
        == 1
    )
    for command in SERVICE_REGISTRY:
        resp = client.post(
            f"/api/cases/{CASE}/commands/{command}",
            json={"idempotency_key": "k", "expected_case_version": 1, "payload": {}},
        )
        assert resp.status_code == 403 and resp.json()["code"] == "role_forbidden"
    actions = client.get(f"/api/cases/{CASE}/available-actions").json()
    blocked = client.get(f"/api/cases/{CASE}").json()["blocked_actions"]
    names = {a["command"] for a in actions} | {b["command"] for b in blocked}
    assert not names & set(SERVICE_REGISTRY)
    assert client.put(f"/api/cases/{CASE}/evidence/DLV-882", json={}).status_code in (404, 405)


def test_cardholder_cannot_read_the_register(client: TestClient) -> None:
    client.post("/api/session/role", json={"role": "cardholder"})
    assert client.get(f"/api/cases/{CASE}/evidence").status_code == 403


def test_demo_material_change_returns_register_and_hash_before_and_after(
    client: TestClient,
) -> None:
    resp = client.post("/api/demo/material-change", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["before"]["snapshot_hash"] != body["after"]["snapshot_hash"]
    assert body["after"]["snapshot_hash"] == snapshot(client)
    assert body["stale_checks"] == ["purchase_records"]
    dlv = next(r for r in body["after"]["records"] if r["record_id"] == "DLV-882")
    assert dlv["current_version"] == 2
    assert client.get(f"/api/cases/{CASE}").json()["case_version"] == 2


def test_get_evidence_summary_matches_route(client: TestClient, db: Session) -> None:
    summary = get_evidence_summary(db, CASE)
    assert summary.model_dump(mode="json") == {
        k: v
        for k, v in client.get(f"/api/cases/{CASE}/evidence").json().items()
        if k in summary.model_dump()
    }
