from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from vera_domain.enums import CaseState, CaseStep, Role, StateKind
from vera_domain.exposure import Basis
from vera_domain.facts import Hold
from vera_domain.labels import WaitKind
from vera_domain.progress import ProgressStep


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
    exposure_cents: int  # gross: the posted amount
    temporary_credit_cents: int
    confirmed_recovery_cents: int
    net_exposure_cents: int
    bases: dict[str, Basis]
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
    recovery_actions: list[ActionView] = []  # e.g. retry_specialist_step after a failed step
    hold: Hold | None = None
    policy: "PolicyView | None" = None
    steps: list[ProgressStep] = []  # display only


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
    next_action: str | None = None
    waiting_on: str | None = None  # person or party the case waits on, display name
    blocker: str | None = None  # "What's blocking it" column
    wait_kind: WaitKind | None = None  # queue filter chips
    due_today: bool = False  # due later today (demo clock, demo timezone), not overdue


class SummaryMetric(BaseModel):
    amount_cents: int
    currency: str
    count: int
    basis: Basis
    definition: str


class Summary(BaseModel):
    gross_exposure: SummaryMetric
    net_exposure: SummaryMetric
    confirmed_recoveries: SummaryMetric
    temporary_credit: SummaryMetric
    due_today: SummaryMetric
    overdue: SummaryMetric


class PolicyView(BaseModel):
    status: Literal["eligible", "needs_evidence", "blocked", "ineligible"]
    code: str
    label: str
    rules_passed: list[str]
    rules_failed: list[str]
    evidence_used: list[str]
    snapshot: str
    policy_version: int
    evaluated_at: datetime


class FilterCounts(BaseModel):
    """Counts for the queue filter chips (prototype `FL`), computed with the demo clock."""

    all: int
    due_today: int
    overdue: int
    mine: int  # "Waiting on me": the session user, nobody else waited on, open
    cardholder: int
    reviewer: int


class ActivityEvent(BaseModel):
    id: int
    type: str
    at: datetime
    actor_name: str
    actor_role: str
    summary: str
    record_ids: list[str]


class ActivityFeed(BaseModel):
    events: list[ActivityEvent]


class AssignableUser(BaseModel):
    id: str
    name: str
    roles: list[Role]


class AssignableUsers(BaseModel):
    users: list[AssignableUser]


CaseView.model_rebuild()
