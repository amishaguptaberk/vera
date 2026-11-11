"""Dashboard exposure: pure computation from plain case rows to metrics.

Gross is primary; net deducts only confirmed (finalized) recoveries. Every metric carries one
basis and its amounts are never summed across bases; estimated amounts are not inputs here.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class Basis(StrEnum):
    VERIFIED = "verified"
    PENDING = "pending"
    ESTIMATED = "estimated"


class CreditStatus(StrEnum):
    ISSUED = "issued"
    FINALIZED = "finalized"


@dataclass(frozen=True)
class ExposureRow:
    amount_cents: int  # posted charge amount (verified)
    currency: str
    closed: bool
    due_at: datetime | None
    credit_cents: int = 0
    credit_status: CreditStatus | None = None


@dataclass(frozen=True)
class Metric:
    amount_cents: int
    currency: str
    count: int
    basis: Basis
    definition: str


DEFINITIONS = {
    "gross_exposure": "Sum of posted charge amounts for cases that are not closed.",
    "net_exposure": "Gross exposure minus confirmed recoveries only; "
    "temporary credit and estimates are not deducted.",
    "confirmed_recoveries": "Finalized credits on cases that are not closed.",
    "temporary_credit": "Provisional credit issued and not yet finalized or reversed; "
    "never deducted from net exposure.",
    "due_today": "Gross posted amounts of open cases due later today.",
    "overdue": "Gross posted amounts of open cases past their due time.",
}


class MixedCurrencyError(ValueError):
    """Amounts in different currencies would have to be summed into one figure."""


@dataclass(frozen=True)
class CaseImpact:
    """One case's money: gross posted amount, credit split by status, net of confirmed only."""

    posted_cents: int
    exposure_cents: int
    temporary_credit_cents: int
    confirmed_recovery_cents: int
    net_exposure_cents: int
    bases: dict[str, Basis]
    note: str


def case_impact(row: ExposureRow) -> CaseImpact:
    temporary = row.credit_cents if row.credit_status == CreditStatus.ISSUED else 0
    confirmed = row.credit_cents if row.credit_status == CreditStatus.FINALIZED else 0
    if row.credit_cents == 0 or row.credit_status is None:
        note = "No credit issued."
    elif row.credit_status == CreditStatus.ISSUED:
        note = "Temporary credit issued — pending, not deducted."
    else:
        note = "Credit finalized."
    return CaseImpact(
        posted_cents=row.amount_cents,
        exposure_cents=row.amount_cents,
        temporary_credit_cents=temporary,
        confirmed_recovery_cents=confirmed,
        net_exposure_cents=row.amount_cents - confirmed,
        bases={
            "posted_cents": Basis.VERIFIED,
            "exposure_cents": Basis.VERIFIED,
            "temporary_credit_cents": Basis.PENDING,
            "confirmed_recovery_cents": Basis.VERIFIED,
            "net_exposure_cents": Basis.VERIFIED,
        },
        note=note,
    )


def _currency(rows: list[ExposureRow]) -> str:
    currencies = {r.currency for r in rows}
    if len(currencies) > 1:
        raise MixedCurrencyError(f"exposure cannot sum mixed currencies: {sorted(currencies)}")
    return currencies.pop() if currencies else "USD"


def compute_exposure(rows: list[ExposureRow], now: datetime, tz: str) -> dict[str, Metric]:
    open_rows = [r for r in rows if not r.closed]
    currency = _currency(open_rows)
    today = now.astimezone(ZoneInfo(tz)).date()

    def metric(key: str, picked: list[ExposureRow], cents: int, basis: Basis) -> Metric:
        return Metric(cents, currency, len(picked), basis, DEFINITIONS[key])

    def posted(key: str, picked: list[ExposureRow]) -> Metric:
        return metric(key, picked, sum(r.amount_cents for r in picked), Basis.VERIFIED)

    def credit(key: str, status: CreditStatus, basis: Basis) -> Metric:
        picked = [r for r in open_rows if r.credit_cents > 0 and r.credit_status == status]
        return metric(key, picked, sum(r.credit_cents for r in picked), basis)

    gross = posted("gross_exposure", open_rows)
    confirmed = credit("confirmed_recoveries", CreditStatus.FINALIZED, Basis.VERIFIED)
    temporary = credit("temporary_credit", CreditStatus.ISSUED, Basis.PENDING)
    net_basis = (
        Basis.VERIFIED
        if gross.basis == confirmed.basis == Basis.VERIFIED
        else Basis.ESTIMATED  # unreachable today; never claim verified for a mixed figure
    )
    net = metric("net_exposure", open_rows, gross.amount_cents - confirmed.amount_cents, net_basis)
    overdue = [r for r in open_rows if r.due_at is not None and r.due_at < now]
    due_today = [
        r
        for r in open_rows
        if r.due_at is not None
        and r.due_at >= now
        and r.due_at.astimezone(ZoneInfo(tz)).date() == today
    ]
    return {
        "gross_exposure": gross,
        "net_exposure": net,
        "confirmed_recoveries": confirmed,
        "temporary_credit": temporary,
        "due_today": posted("due_today", due_today),
        "overdue": posted("overdue", overdue),
    }
