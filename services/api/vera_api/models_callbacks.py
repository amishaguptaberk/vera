"""Callback tables (migration 0012)."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


def _ts() -> Mapped[Any]:
    return mapped_column(DateTime(timezone=True))


class Callback(Base):
    __tablename__ = "callbacks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    target_record_id: Mapped[str] = mapped_column(String)
    target_field: Mapped[str] = mapped_column(String)
    target_version: Mapped[int] = mapped_column(Integer)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    approved_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class CallbackLine(Base):
    __tablename__ = "callback_transcript_lines"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    callback_id: Mapped[str] = mapped_column(ForeignKey("callbacks.id"))
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class CallbackNote(Base):
    __tablename__ = "callback_notes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    callback_id: Mapped[str] = mapped_column(ForeignKey("callbacks.id"))
    author: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
