from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    cardholder_id: Mapped[str | None] = mapped_column(ForeignKey("cardholders.id"))
    created_at: Mapped[datetime] = _ts()


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String, primary_key=True)


class Cardholder(Base):
    __tablename__ = "cardholders"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    profile_id: Mapped[str] = mapped_column(String)
    phone: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    contact_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = _ts()


class CardTransaction(Base):
    __tablename__ = "card_transactions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    cardholder_id: Mapped[str] = mapped_column(ForeignKey("cardholders.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    card_last4: Mapped[str] = mapped_column(String(4))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("card_transactions.id"), unique=True)
    state: Mapped[str] = mapped_column(String)
    step: Mapped[str] = mapped_column(String)
    case_version: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    waiting_on_id: Mapped[str | None] = mapped_column(String)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow_version: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer)
    evidence_snapshot: Mapped[str] = mapped_column(String)
    credit_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    live: Mapped[bool] = mapped_column(Boolean, default=True)
    display_label: Mapped[str | None] = mapped_column(String)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts()


class CaseAssignment(Base):
    __tablename__ = "case_assignments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    cardholder_id: Mapped[str] = mapped_column(ForeignKey("cardholders.id"))
    statement: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    statement: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class StateTransition(Base):
    __tablename__ = "state_transitions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    prior_state: Mapped[str | None] = mapped_column(String)
    prior_step: Mapped[str | None] = mapped_column(String)
    next_state: Mapped[str] = mapped_column(String)
    next_step: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    actor_role: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    case_version: Mapped[int] = mapped_column(Integer)
    workflow_version: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer)
    evidence_snapshot: Mapped[str] = mapped_column(String)
    event_id: Mapped[int | None] = mapped_column(BigInteger)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    case_version: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[str] = mapped_column(String)
    actor_role: Mapped[str] = mapped_column(String)
    record_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    command: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    status: Mapped[str] = mapped_column(String)
    request_id: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    event_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)


ALL_TABLES = (
    "users",
    "user_roles",
    "cardholders",
    "merchants",
    "card_transactions",
    "cases",
    "case_assignments",
    "reports",
    "claims",
    "state_transitions",
    "audit_events",
    "idempotency_keys",
)
