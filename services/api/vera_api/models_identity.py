from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from vera_api.db import Base


class IdentityVerification(Base):
    """One verification request. Stores only a salted HMAC of the code, never the code."""

    __tablename__ = "identity_verifications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    cardholder_id: Mapped[str] = mapped_column(ForeignKey("cardholders.id"))
    channel: Mapped[str] = mapped_column(String)  # otp | push
    status: Mapped[str] = mapped_column(String)
    code_salt: Mapped[str | None] = mapped_column(String)
    code_hash: Mapped[str | None] = mapped_column(String)
    delivery_ref: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    sends: Mapped[int] = mapped_column(Integer, default=1)
    requested_by: Mapped[str] = mapped_column(String)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    verification_id: Mapped[str] = mapped_column(ForeignKey("identity_verifications.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VerificationOutbox(Base):
    """Simulated delivery to the cardholder (synthetic only); read only by that cardholder."""

    __tablename__ = "verification_outbox"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    verification_id: Mapped[str] = mapped_column(ForeignKey("identity_verifications.id"))
    channel: Mapped[str] = mapped_column(String)
    code: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
