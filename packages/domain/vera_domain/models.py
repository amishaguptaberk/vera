from datetime import datetime

from pydantic import BaseModel

from vera_domain.enums import CaseState, CaseStep, StateKind


class Person(BaseModel):
    id: str
    name: str


class Due(BaseModel):
    at: datetime
    label: str
    overdue: bool


class Pins(BaseModel):
    workflow_version: int
    policy_version: int
    evidence_snapshot: str


class TransactionView(BaseModel):
    id: str
    merchant: str
    amount_cents: int
    currency: str
    card_last4: str
    posted_at: datetime


class ContactOnFile(BaseModel):
    phone_masked: str
    email: str
    verified_at: datetime | None


class CardholderView(BaseModel):
    id: str
    name: str
    contact_on_file: ContactOnFile


class ChargeImpact(BaseModel):
    posted_cents: int
    credit_cents: int
    exposure_cents: int
    note: str


class CaseView(BaseModel):
    case_id: str
    case_version: int
    state: CaseState
    step: CaseStep
    state_label: str
    state_kind: StateKind
    next_action: str
    owner: Person
    waiting_on: Person | None
    due: Due | None
    pins: Pins
    transaction: TransactionView
    cardholder: CardholderView
    charge_impact: ChargeImpact
    available_actions: list[object]


class QueueRow(BaseModel):
    case_id: str
    merchant: str
    amount_cents: int
    currency: str
    state: CaseState
    step: CaseStep
    state_label: str
    owner: Person
    due: Due | None
    credit_cents: int
    live: bool


class SummaryMetric(BaseModel):
    amount_cents: int
    cases: int


class Summary(BaseModel):
    open_exposure: SummaryMetric
    due_today: SummaryMetric
    overdue: SummaryMetric
    temporary_credit: SummaryMetric
