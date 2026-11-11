from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="supporting")
    created_at: Mapped[datetime] = _ts()


class EvidenceVersion(Base):
    """Append-only. `material_version` only advances when the material content changes."""

    __tablename__ = "evidence_versions"
    __table_args__ = (UniqueConstraint("record_id", "version"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"))
    version: Mapped[int] = mapped_column(Integer)
    material_version: Mapped[int] = mapped_column(Integer)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["record_id", "version"], ["evidence_versions.record_id", "evidence_versions.version"]
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    file_name: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String)
    uploader: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    kind: Mapped[str] = mapped_column(String)
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)
    resolved_by: Mapped[str | None] = mapped_column(String)
    conflict_field: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FindingLink(Base):
    """Append-only. Cites an exact record version and field."""

    __tablename__ = "finding_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["record_id", "version"], ["evidence_versions.record_id", "evidence_versions.version"]
        ),
        UniqueConstraint("finding_id", "record_id", "version", "field"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    record_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String)


class EvidenceCheck(Base):
    __tablename__ = "evidence_checks"
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String)
    kinds: Mapped[list[Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, default="current")
    stale_reason: Mapped[str | None] = mapped_column(String)
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
