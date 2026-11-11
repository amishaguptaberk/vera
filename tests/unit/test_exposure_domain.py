"""Pure exposure computation (VER-015, plan §19 D-H)."""

from datetime import UTC, datetime

import pytest
from vera_domain.exposure import Basis, CreditStatus, ExposureRow, compute_exposure

NOW = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)  # 08:00 in Los Angeles
TZ = "America/Los_Angeles"


def row(cents: int, **over: object) -> ExposureRow:
    base: dict[str, object] = {
        "amount_cents": cents,
        "currency": "USD",
        "closed": False,
        "due_at": None,
    }
    base.update(over)
    return ExposureRow(**base)  # type: ignore[arg-type]


def test_issued_credit_is_pending_and_not_deducted() -> None:
    rows = [row(100000), row(50000, credit_cents=50000, credit_status=CreditStatus.ISSUED)]
    m = compute_exposure(rows, NOW, TZ)
    assert (m["gross_exposure"].amount_cents, m["gross_exposure"].count) == (150000, 2)
    assert m["net_exposure"].amount_cents == 150000
    assert m["temporary_credit"].amount_cents == 50000
    assert m["temporary_credit"].basis is Basis.PENDING
    assert m["confirmed_recoveries"].amount_cents == 0


def test_finalized_credit_is_verified_and_deducted() -> None:
    rows = [row(100000), row(50000, credit_cents=20000, credit_status=CreditStatus.FINALIZED)]
    m = compute_exposure(rows, NOW, TZ)
    assert m["gross_exposure"].amount_cents == 150000
    assert m["confirmed_recoveries"].amount_cents == 20000
    assert m["confirmed_recoveries"].basis is Basis.VERIFIED
    assert m["net_exposure"].amount_cents == 130000
    assert m["net_exposure"].basis is Basis.VERIFIED
    assert m["temporary_credit"].amount_cents == 0


def test_closed_cases_and_their_credit_are_excluded() -> None:
    rows = [
        row(100000),
        row(70000, closed=True, credit_cents=70000, credit_status=CreditStatus.FINALIZED),
    ]
    m = compute_exposure(rows, NOW, TZ)
    assert m["gross_exposure"].amount_cents == 100000
    assert m["confirmed_recoveries"].amount_cents == 0
    assert m["net_exposure"].amount_cents == 100000


def test_due_today_and_overdue_are_gross() -> None:
    credit = {"credit_cents": 30000, "credit_status": CreditStatus.ISSUED}
    rows = [
        row(10000, due_at=datetime(2026, 11, 10, 15, 0, tzinfo=UTC), **credit),  # overdue
        row(20000, due_at=datetime(2026, 11, 10, 20, 0, tzinfo=UTC), **credit),  # today
        row(40000, due_at=datetime(2026, 11, 11, 9, 0, tzinfo=UTC)),  # 01:00 tomorrow local
    ]
    m = compute_exposure(rows, NOW, TZ)
    assert (m["overdue"].amount_cents, m["overdue"].count) == (10000, 1)
    assert (m["due_today"].amount_cents, m["due_today"].count) == (20000, 1)


def test_every_metric_has_a_single_basis_and_definition() -> None:
    m = compute_exposure([row(1)], NOW, TZ)
    for metric in m.values():
        assert isinstance(metric.basis, Basis)
        assert metric.definition
    assert "confirmed recoveries" in m["net_exposure"].definition


def test_mixed_currencies_are_never_summed() -> None:
    with pytest.raises(ValueError):
        compute_exposure([row(1), row(2, currency="EUR")], NOW, TZ)


def test_case_impact_splits_credit_by_status() -> None:
    from vera_domain.exposure import case_impact

    issued = case_impact(row(284000, credit_cents=10000, credit_status=CreditStatus.ISSUED))
    assert (issued.exposure_cents, issued.temporary_credit_cents) == (284000, 10000)
    assert (issued.confirmed_recovery_cents, issued.net_exposure_cents) == (0, 284000)
    final = case_impact(row(284000, credit_cents=10000, credit_status=CreditStatus.FINALIZED))
    assert (final.temporary_credit_cents, final.confirmed_recovery_cents) == (0, 10000)
    assert final.net_exposure_cents == 274000
    assert final.bases["temporary_credit_cents"] is Basis.PENDING
