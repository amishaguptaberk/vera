"""Run, step and job tables (migration 0004)."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


def _ts(nullable: bool = False) -> Mapped[Any]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    workflow_version: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="running")
    mode: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()
    # Creation order (migration 0019): runs created at the same instant still have a latest.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), primary_key=True)
    step_key: Mapped[str] = mapped_column(String, primary_key=True)
    specialist: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    execution_mode: Mapped[str | None] = mapped_column(String)
    model_id: Mapped[str | None] = mapped_column(String)
    prompt_version: Mapped[str | None] = mapped_column(String)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tool_calls: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime | None] = _ts(True)
    finished_at: Mapped[datetime | None] = _ts(True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="queued")
    run_after: Mapped[datetime] = _ts()
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_by: Mapped[str | None] = mapped_column(String)
    locked_at: Mapped[datetime | None] = _ts(True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
