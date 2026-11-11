from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    active_version: Mapped[int] = mapped_column(Integer)


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    workflow_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB)
    graph_hash: Mapped[str] = mapped_column(String)
    published_by: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowDraft(Base):
    __tablename__ = "workflow_drafts"
    workflow_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_version: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowCheckRun(Base):
    __tablename__ = "workflow_check_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String)
    draft_version: Mapped[int] = mapped_column(Integer)
    graph_hash: Mapped[str] = mapped_column(String)
    passed: Mapped[bool] = mapped_column(Boolean)
    results: Mapped[list[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SpecialistDefinition(Base):
    __tablename__ = "specialist_definitions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PolicyDraft(Base):
    __tablename__ = "policy_drafts"
    policy_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[list[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AutomationCommandKey(Base):
    __tablename__ = "automation_command_keys"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    command: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    request_id: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    event_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)


class AutomationEvent(Base):
    __tablename__ = "automation_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[str] = mapped_column(String)
    actor_role: Mapped[str] = mapped_column(String)
    record_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
