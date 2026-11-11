from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


class AdapterExecution(Base):
    __tablename__ = "adapter_executions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    adapter: Mapped[str] = mapped_column(String)
    operation: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String)  # pending | succeeded | failed | uncertain
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_id: Mapped[int | None] = mapped_column(BigInteger)


class AdapterFault(Base):
    __tablename__ = "adapter_faults"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    adapter: Mapped[str] = mapped_column(String)
    operation: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)  # fail | uncertain | timeout
    remaining: Mapped[int] = mapped_column(Integer)
