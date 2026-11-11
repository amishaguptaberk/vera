"""ORM for credit, dispute and card controls (VER-010; migration 0014)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True))


class ProvisionalCredit(Base):
    __tablename__ = "provisional_credits"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), unique=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("card_transactions.id"), unique=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    execution_key: Mapped[str] = mapped_column(String, unique=True)
    reference: Mapped[str | None] = mapped_column(String)
    requested_by: Mapped[str] = mapped_column(String)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class DisputePacket(Base):
    __tablename__ = "dispute_packets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), unique=True)
    status: Mapped[str] = mapped_column(String)
    submission_reference: Mapped[str | None] = mapped_column(String)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class ControlPlan(Base):
    __tablename__ = "control_plans"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), unique=True)
    status: Mapped[str] = mapped_column(String)
    controls: Mapped[list[str]] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(String)
    proposed_by: Mapped[str | None] = mapped_column(String)
    decided_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class CardControl(Base):
    __tablename__ = "card_controls"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("control_plans.id"))
    control: Mapped[str] = mapped_column(String)
    reference: Mapped[str] = mapped_column(String)
    applied_by: Mapped[str] = mapped_column(String)
    applied_at: Mapped[datetime] = _ts()
