from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


class FinalMessage(Base):
    __tablename__ = "final_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    body: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # drafted | sent
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_id: Mapped[int | None] = mapped_column(BigInteger)


class CaseClosure(Base):
    __tablename__ = "case_closures"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), unique=True)
    reason: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String)
    monitoring: Mapped[bool] = mapped_column(Boolean)
    checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    closed_by: Mapped[str] = mapped_column(String)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
