"""ORM for the cardholder follow-up tables (migration 0010)."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


class Communication(Base):
    __tablename__ = "communications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    kind: Mapped[str] = mapped_column(String, default="cardholder_request")
    status: Mapped[str] = mapped_column(String)
    channel: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    questions: Mapped[list[Any]] = mapped_column(JSONB)
    attachments: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    delivery: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reminders: Mapped[int] = mapped_column(Integer, default=0)
    response_review: Mapped[str] = mapped_column(String, default="none")
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_by: Mapped[str | None] = mapped_column(String)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overdue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommunicationDraft(Base):
    __tablename__ = "communication_drafts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    communication_id: Mapped[str] = mapped_column(ForeignKey("communications.id"))
    version: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommunicationResponse(Base):
    __tablename__ = "communication_responses"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    communication_id: Mapped[str] = mapped_column(ForeignKey("communications.id"))
    text: Mapped[str] = mapped_column(Text)
    evidence_record_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_records.id"))
    submitted_by: Mapped[str] = mapped_column(String)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
