"""Dashboard exposure is gross and net, through GET /api/cases/summary."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

METRICS = (
    "gross_exposure",
    "net_exposure",
    "confirmed_recoveries",
    "temporary_credit",
    "due_today",
    "overdue",
)


def _finalize_chg_1036(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "update cases set credit_status='finalized', credit_finalized_at=now() "
                "where id='CHG-1036'"
            )
        )
    engine.dispose()


def test_seed_gross_and_net_then_finalizing_credit_reduces_net(
    client: TestClient, db_url: str
) -> None:
    before = client.get("/api/cases/summary").json()
    assert before["gross_exposure"]["amount_cents"] == 1122000
    assert before["gross_exposure"]["count"] == 6
    assert before["gross_exposure"]["basis"] == "verified"
    assert before["temporary_credit"]["amount_cents"] == 396000
    assert before["temporary_credit"]["count"] == 1
    assert before["temporary_credit"]["basis"] == "pending"
    assert before["confirmed_recoveries"]["amount_cents"] == 0
    assert before["confirmed_recoveries"]["basis"] == "verified"
    assert before["net_exposure"]["amount_cents"] == 1122000
    assert before["net_exposure"]["basis"] == "verified"

    _finalize_chg_1036(db_url)

    after = client.get("/api/cases/summary").json()
    assert after["temporary_credit"]["amount_cents"] == 0
    assert after["temporary_credit"]["count"] == 0
    assert after["confirmed_recoveries"]["amount_cents"] == 396000
    assert after["confirmed_recoveries"]["count"] == 1
    assert after["confirmed_recoveries"]["basis"] == "verified"
    assert after["gross_exposure"]["amount_cents"] == 1122000
    assert after["net_exposure"]["amount_cents"] == 726000
    assert after["net_exposure"]["basis"] == "verified"


def test_every_metric_has_basis_definition_and_currency(client: TestClient) -> None:
    summary = client.get("/api/cases/summary").json()
    assert set(summary) == set(METRICS)
    for key in METRICS:
        metric = summary[key]
        assert set(metric) == {"amount_cents", "currency", "count", "basis", "definition"}
        assert metric["basis"] in {"verified", "pending", "estimated"}
        assert metric["currency"] == "USD"
        assert metric["definition"] and "\n" not in metric["definition"]
    assert "confirmed recoveries" in summary["net_exposure"]["definition"].lower()
    assert "gross" in summary["net_exposure"]["definition"].lower()


def test_due_today_and_overdue_are_gross(client: TestClient) -> None:
    summary = client.get("/api/cases/summary").json()
    assert (summary["due_today"]["amount_cents"], summary["due_today"]["count"]) == (566000, 3)
    assert (summary["overdue"]["amount_cents"], summary["overdue"]["count"]) == (118000, 1)
    assert summary["due_today"]["basis"] == "verified"
    assert summary["overdue"]["basis"] == "verified"


def test_closed_case_leaves_gross(client: TestClient, db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("update cases set state='closed' where id='CHG-1033'"))
    engine.dispose()
    summary = client.get("/api/cases/summary").json()
    # 1122000 - 42000 (CHG-1033 closed)
    assert summary["gross_exposure"]["amount_cents"] == 1080000
    assert summary["gross_exposure"]["count"] == 5
    assert summary["net_exposure"]["amount_cents"] == 1080000


def _sql(db_url: str, sql: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(sql))
    engine.dispose()


def test_case_charge_impact_never_deducts_pending_credit(client: TestClient, db_url: str) -> None:
    seed = client.get("/api/cases/CHG-1042").json()["charge_impact"]
    assert seed["exposure_cents"] == 284000
    assert seed["temporary_credit_cents"] == 0
    assert seed["confirmed_recovery_cents"] == 0
    assert seed["net_exposure_cents"] == 284000
    assert seed["note"] == "No credit issued."

    _sql(db_url, "update cases set credit_cents=10000, credit_status='issued' where id='CHG-1042'")
    issued = client.get("/api/cases/CHG-1042").json()["charge_impact"]
    assert issued["posted_cents"] == 284000
    assert issued["exposure_cents"] == 284000
    assert issued["temporary_credit_cents"] == 10000
    assert issued["confirmed_recovery_cents"] == 0
    assert issued["net_exposure_cents"] == 284000
    assert issued["bases"] == {
        "posted_cents": "verified",
        "exposure_cents": "verified",
        "temporary_credit_cents": "pending",
        "confirmed_recovery_cents": "verified",
        "net_exposure_cents": "verified",
    }
    assert issued["note"] == "Temporary credit issued — pending, not deducted."

    _sql(
        db_url,
        "update cases set credit_status='finalized', credit_finalized_at=now() where id='CHG-1042'",
    )
    final = client.get("/api/cases/CHG-1042").json()["charge_impact"]
    assert final["exposure_cents"] == 284000
    assert final["temporary_credit_cents"] == 0
    assert final["confirmed_recovery_cents"] == 10000
    assert final["net_exposure_cents"] == 274000
    assert final["note"] == "Credit finalized."


def test_mixed_currency_summary_is_a_typed_409(client: TestClient, db_url: str) -> None:
    _sql(db_url, "update card_transactions set currency='EUR' where id='TXN-1033'")
    resp = client.get("/api/cases/summary")
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "mixed_currency"
    assert body["message"]
