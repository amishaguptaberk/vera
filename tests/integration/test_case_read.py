from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def test_reset_then_read_canonical_case_and_reset_is_repeatable(
    client: TestClient, db_url: str
) -> None:
    def counts() -> dict[str, int]:
        return client.get("/api/demo/counts").json()  # type: ignore[no-any-return]

    resp = client.post("/api/demo/reset")
    assert resp.status_code == 200

    body = client.get("/api/cases/CHG-1042").json()
    assert body["case_id"] == "CHG-1042"
    assert body["state"] == "reported"
    assert body["step"] == "intake"
    assert body["state_label"] == "New report"
    assert body["transaction"]["amount_cents"] == 284000
    assert body["transaction"]["currency"] == "USD"
    assert body["transaction"]["merchant"] == "Bayline Industrial Supply"
    assert body["transaction"]["card_last4"] == "4418"
    assert body["owner"]["name"] == "Sam Rivera"
    assert body["cardholder"]["name"] == "Priya Shah"
    assert body["pins"]["workflow_version"] == 3
    assert body["pins"]["policy_version"] == 1

    seed = counts()
    assert seed["cases"] == 6
    assert seed["reports"] == 1
    assert seed["audit_events"] == 2
    assert seed["users"] == 3
    assert seed["idempotency_keys"] == 0

    # Dirty the database: append-only rows added and a case edited.
    dup = {"report_id": "REP-1043", "transaction_id": "TXN-1042", "statement": "second"}
    assert client.post("/api/reports", json=dup).status_code == 200
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("update cases set state='closed' where id='CHG-1042'"))
    engine.dispose()
    assert counts()["audit_events"] == seed["audit_events"] + 1
    assert counts()["idempotency_keys"] == seed["idempotency_keys"] + 1
    assert client.get("/api/cases/CHG-1042").json()["state"] == "closed"

    assert client.post("/api/demo/reset").status_code == 200
    assert counts() == seed
    assert client.get("/api/cases/CHG-1042").json()["state"] == "reported"
    assert client.post("/api/demo/reset").status_code == 200
    assert counts() == seed


def test_queue_rows_and_non_openable_display_cases(client: TestClient) -> None:
    rows = {r["case_id"]: r for r in client.get("/api/cases").json()}
    assert set(rows) == {"CHG-1029", "CHG-1039", "CHG-1042", "CHG-1051", "CHG-1036", "CHG-1033"}
    assert rows["CHG-1029"]["state_label"] == "Response overdue"
    assert rows["CHG-1036"]["credit_cents"] == 396000
    assert rows["CHG-1051"]["due"]["label"] == "Nov 10, 5:00 PM"
    assert rows["CHG-1042"]["live"] is True
    assert rows["CHG-1029"]["live"] is False

    resp = client.get("/api/cases/CHG-1029")
    assert resp.status_code == 404
    assert resp.json()["code"] == "case_not_openable"
    assert client.get("/api/cases/CHG-9999").status_code == 404


def test_summary_is_computed_from_rows(client: TestClient, db_url: str) -> None:
    def pair(metric: dict[str, int]) -> tuple[int, int]:
        return metric["amount_cents"], metric["count"]

    summary = client.get("/api/cases/summary").json()
    # gross: 284000 + 118000 + 162000 + 120000 + 396000 + 42000; credit not deducted
    assert pair(summary["gross_exposure"]) == (1122000, 6)
    assert pair(summary["net_exposure"]) == (1122000, 6)
    assert pair(summary["due_today"]) == (566000, 3)
    assert pair(summary["overdue"]) == (118000, 1)
    assert pair(summary["temporary_credit"]) == (396000, 1)
    assert pair(summary["confirmed_recoveries"]) == (0, 0)

    # Not a constant: closing a case in the database changes the metric.
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("update cases set state='closed' where id='CHG-1033'"))
    engine.dispose()
    after = client.get("/api/cases/summary").json()
    assert pair(after["gross_exposure"]) == (1080000, 5)


def test_duplicate_report_links_to_existing_case(client: TestClient) -> None:
    def counts() -> dict[str, int]:
        return client.get("/api/demo/counts").json()  # type: ignore[no-any-return]

    base = counts()
    same = {"report_id": "REP-1042", "transaction_id": "TXN-1042", "statement": "again"}
    r1 = client.post("/api/reports", json=same)
    assert r1.status_code == 200
    assert r1.json() == {"case_id": "CHG-1042", "report_id": "REP-1042", "created": False}
    assert counts() == base

    other = {"report_id": "REP-1043", "transaction_id": "TXN-1042", "statement": "second report"}
    r2 = client.post("/api/reports", json=other)
    assert r2.json() == {"case_id": "CHG-1042", "report_id": "REP-1042", "created": False}
    after = counts()
    assert after["cases"] == base["cases"]
    assert after["reports"] == base["reports"] + 1  # the linked report is stored on the case
    assert after["audit_events"] == base["audit_events"] + 1
    assert after["state_transitions"] == base["state_transitions"] + 1
    assert after["idempotency_keys"] == base["idempotency_keys"] + 1
    assert client.post("/api/reports", json=other).status_code == 200
    assert counts() == after  # a retried duplicate adds no second event


def test_report_is_a_claim_and_history_is_append_only(client: TestClient, db_url: str) -> None:
    engine = create_engine(db_url)

    def fails(sql: str) -> bool:
        try:
            with engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as exc:
            return "append-only" in str(exc)
        return False

    with engine.connect() as conn:
        claim = conn.execute(
            text("select statement, report_id from claims where report_id='REP-1042'")
        ).one()
    assert claim.statement == "I do not recognize this charge."
    for table in ("claims", "reports", "audit_events", "state_transitions"):
        assert fails(f"update {table} set id=id")
        assert fails(f"delete from {table}")
    engine.dispose()


def test_report_for_display_transaction_is_typed_409(client: TestClient) -> None:
    for report_id, txn in (("REP-2000", "TXN-1029"), ("REP-1042", "TXN-1051")):
        body = {"report_id": report_id, "transaction_id": txn, "statement": "x"}
        resp = client.post("/api/reports", json=body)
        assert resp.status_code == 409
        assert resp.json()["code"] == "case_not_openable"


def test_timestamps_are_utc(client: TestClient) -> None:
    body = client.get("/api/cases/CHG-1042").json()
    assert body["due"]["at"].endswith(("Z", "+00:00"))
    row = {r["case_id"]: r for r in client.get("/api/cases").json()}["CHG-1051"]
    assert row["due"]["at"].endswith(("Z", "+00:00"))
