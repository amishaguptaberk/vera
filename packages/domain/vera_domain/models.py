from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from vera_domain.enums import CaseState, CaseStep, Role, StateKind
from vera_domain.facts import Hold


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


class ActionView(BaseModel):
    command: str
    label: str
    role: Role
    style: Literal["primary", "secondary", "dark", "ghost"]
    enabled: bool
    blocked_reason: str | None = None
    expected_state: CaseState
    expected_step: CaseStep
    safe_note: str | None = None
    confirm: str | None = None
    idempotency_key: str  # always fully resolved: the client echoes it as given
    payload_defaults: dict[str, Any] = {}  # server-allocated payload fields; merge under the input
    key_template: str | None = None  # informational only: never something the client fills in


class BlockedAction(BaseModel):
    command: str
    label: str
    reason: str
    blocked_reason: str  # same text as `reason`; both names are accepted by clients


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
    available_actions: list[ActionView]
    blocked_actions: list[BlockedAction] = []
    recovery_actions: list[str] = []
    hold: Hold | None = None


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
