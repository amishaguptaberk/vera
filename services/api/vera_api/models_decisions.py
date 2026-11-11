from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


class DecisionPacket(Base):
    __tablename__ = "decision_packets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot_hash: Mapped[str] = mapped_column(String)
    workflow_version: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer)
    policy_evaluation_id: Mapped[int | None] = mapped_column(BigInteger)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    run_id: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DecisionPacketContent(Base):
    """The preparer's validated output, written once per packet version (append-only)."""

    __tablename__ = "decision_packet_contents"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    packet_version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String)
    execution_mode: Mapped[str | None] = mapped_column(String)
    model_id: Mapped[str | None] = mapped_column(String)
    statements: Mapped[list[Any]] = mapped_column(JSONB)
    recommendation: Mapped[str] = mapped_column(String)
    reasons: Mapped[list[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    packet_version: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String)
    rationale: Mapped[str] = mapped_column(String)
    decided_by: Mapped[str] = mapped_column(String)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    transaction_id: Mapped[str] = mapped_column(String)
    packet_version: Mapped[int] = mapped_column(Integer)
    snapshot_hash: Mapped[str] = mapped_column(String)
    policy_version: Mapped[int] = mapped_column(Integer)
    workflow_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    reviewer_id: Mapped[str] = mapped_column(String)
    requested_by: Mapped[str] = mapped_column(String)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    return_reason: Mapped[str | None] = mapped_column(String)
    return_next_step: Mapped[str | None] = mapped_column(String)
    return_owner_id: Mapped[str | None] = mapped_column(String)
    # Set once a credit execution exists for this approval: it can no longer go stale.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_execution_id: Mapped[str | None] = mapped_column(String)


class AskPair(Base):
    __tablename__ = "ask_pairs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    user_id: Mapped[str] = mapped_column(String)
    intent: Mapped[str] = mapped_column(String)
    question: Mapped[str] = mapped_column(String)
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
