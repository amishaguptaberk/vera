"""Identity verification: effects, fact provider, simulated adapter, routes, expirer.

The raw one-time code is generated inside the simulated adapter, handed to the
effect in memory, persisted only as a salted HMAC-SHA256 (per-row salt + server secret) and, for
the synthetic demo, in the cardholder-only `verification_outbox` row. It never reaches adapter
request/result JSON, events, idempotency rows, logs or any staff response.
"""

import hashlib
import hmac
import secrets
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from vera_domain import identity as dom
from vera_domain.adapters import AdapterResult
from vera_domain.clock import Clock
from vera_domain.enums import Role
from vera_domain.errors import CommandError

from vera_api import adapters, auth, gateway, plugins, worker
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.config import Settings
from vera_api.gateway import EffectContext, Outcome
from vera_api.intake import _emit
from vera_api.models import Case, User
from vera_api.models_identity import IdentityVerification, VerificationAttempt, VerificationOutbox


# Route dependencies defined here (not imported from vera_api.evidence): evidence imports the
# gateway, which loads this feature, so importing from evidence here is circular.
def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def _actor(request: Request, session: Annotated[Session, Depends(_session)]) -> Actor:
    settings: Settings = request.app.state.settings
    return auth.load_actor(
        session, settings.secret(), request.cookies.get(auth.COOKIE), settings.synthetic
    )


DbSession = Annotated[Session, Depends(_session)]
ReaderDep = Annotated[Actor, Depends(_actor)]

ADAPTER = "verification"


class SimulatedVerification:
    """Synthetic OTP / push delivery. Returns only a delivery reference; the code stays in memory
    until the calling effect takes it (same transaction, same process)."""

    def __init__(self) -> None:
        self._pending: dict[str, str] = {}
        self._lock = threading.Lock()

    def call(self, operation: str, request: dict[str, Any]) -> AdapterResult:
        ref = f"dlv-{uuid.uuid4().hex[:12]}"
        if operation == "send_otp":
            with self._lock:
                self._pending[ref] = f"{secrets.randbelow(10**6):06d}"
        return AdapterResult(
            status="succeeded",
            result={"delivery_ref": ref, "channel": request["channel"], "synthetic": True},
        )

    def take_code(self, ref: str) -> str | None:
        with self._lock:
            return self._pending.pop(ref, None)


SIMULATED = SimulatedVerification()


def _adapter() -> SimulatedVerification:
    # Registered on first use (not at import) while main's seam test forbids import-time adapters.
    if ADAPTER not in adapters.ADAPTERS:
        adapters.register_adapter(ADAPTER, SIMULATED)
    adapter = adapters.ADAPTERS[ADAPTER]
    if not isinstance(adapter, SimulatedVerification):
        raise CommandError(
            "verification_unavailable", 503, f"Adapter '{ADAPTER}' is registered by another module."
        )
    return adapter


def _synthetic() -> bool:
    """Process environment (VERA_ENV), the same source as the server secret."""
    return Settings().synthetic


def _secret() -> bytes:
    try:
        return Settings().secret().encode()
    except RuntimeError:  # production requires VERA_SESSION_SECRET
        raise CommandError(
            "verification_unavailable", 503, "Server secret is not configured."
        ) from None


def hash_code(salt: str, code: str) -> str:
    return hmac.new(_secret(), f"{salt}:{code}".encode(), hashlib.sha256).hexdigest()


# --- queries ---


def current(session: Session, case_id: str) -> IdentityVerification | None:
    return session.scalars(
        select(IdentityVerification)
        .where(IdentityVerification.case_id == case_id)
        .order_by(IdentityVerification.created_at.desc(), IdentityVerification.id.desc())
    ).first()


def identity_verified(session: Session, case_id: str) -> bool:
    row = current(session, case_id)
    return row is not None and row.status == "verified"


def _facts(session: Session, case: Case) -> dict[str, Any]:
    row = current(session, case.id)
    return {"identity_status": row.status if row else "none"}


def _key_context(session: Session, case: Case, body: dict[str, Any]) -> dict[str, object]:
    vid = body.get("verification_id")
    row = session.get(IdentityVerification, vid) if vid else current(session, case.id)
    return {
        "verification_id": row.id if row else "none",
        "attempt_no": (row.attempts + 1) if row else 1,
        "sends": (row.sends + 1) if row else 1,
    }


def _own(session: Session, case: Case, vid: str) -> IdentityVerification:
    row = session.get(IdentityVerification, vid, with_for_update=True)
    if row is None or row.case_id != case.id:
        raise CommandError("verification_not_found", 404, "No such verification request.")
    return row


def _active(row: IdentityVerification) -> None:
    if row.status != "requested":
        raise CommandError(
            "verification_not_active", 409, f"The verification request is {row.status}."
        )


def _clear_outbox(session: Session, vid: str) -> None:
    for box in session.scalars(
        select(VerificationOutbox).where(VerificationOutbox.verification_id == vid)
    ):
        session.delete(box)


def _out(row: IdentityVerification, **extra: Any) -> dict[str, Any]:
    return {
        "verification_id": row.id,
        "status": row.status,
        "channel": row.channel,
        "attempts": row.attempts,
        "attempts_left": max(row.max_attempts - row.attempts, 0),
        "expires_at": row.expires_at.isoformat(),
        **extra,
    }


def _deliver(session: Session, case: Case, row: IdentityVerification, now: datetime) -> None:
    """Send through the adapter framework; persist only the hash + delivery reference."""
    adapter = _adapter()
    op = "send_otp" if row.channel == "otp" else "send_push"
    res = adapters.execute(
        session,
        case_id=case.id,
        adapter=ADAPTER,
        operation=op,
        key=f"verification:{row.id}:{row.sends}",
        request={"verification_id": row.id, "channel": row.channel, "send": row.sends},
        now=now,
    )
    if res.status != "succeeded":  # never act on failed / uncertain
        raise CommandError(
            "verification_delivery_failed", 502, "The verification could not be delivered."
        )
    ref = str(res.result["delivery_ref"])
    row.delivery_ref = ref
    _clear_outbox(session, row.id)
    code: str | None = None
    if row.channel == "otp":
        code = adapter.take_code(ref)
        if code is None:
            raise CommandError(
                "verification_delivery_failed", 502, "The verification could not be delivered."
            )
        row.code_salt = secrets.token_hex(16)
        row.code_hash = hash_code(row.code_salt, code)
    session.flush()
    if not _synthetic():  # outside the synthetic demo the cleartext code is never stored
        return
    session.add(
        VerificationOutbox(verification_id=row.id, channel=row.channel, code=code, created_at=now)
    )
    session.flush()


# --- effects ---


def _send(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    prev = current(session, case.id)
    if prev is not None and prev.status in ("requested", "verified"):
        raise CommandError("verification_active", 409, "A verification request is already active.")
    report = ctx.first_report
    if report is None:
        raise CommandError("case_not_openable", 409, "The case has no cardholder report.")
    row = IdentityVerification(
        id=f"IDV-{uuid.uuid4().hex[:8].upper()}",
        case_id=case.id,
        cardholder_id=report.cardholder_id,
        channel=p.channel,
        status="requested",
        attempts=0,
        max_attempts=dom.MAX_ATTEMPTS,
        sends=1,
        requested_by=actor.user_id,
        sent_at=now,
        last_sent_at=now,
        expires_at=now + timedelta(seconds=dom.EXPIRES_AFTER_SECONDS),
        # current() orders by created_at: a request sent at the same (demo) instant as the one it
        # replaces must still sort after it, whatever its random id.
        created_at=max(now, prev.created_at + timedelta(microseconds=1)) if prev else now,
    )
    session.add(row)
    session.flush()
    _deliver(session, case, row, now)
    return _out(row)


def _resend(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _own(session, case, p.verification_id)
    _active(row)
    if row.sends >= dom.MAX_SENDS:
        raise CommandError("send_limit_reached", 409, dom.SEND_LIMIT_REASON)
    ready_at = row.last_sent_at + timedelta(seconds=dom.RESEND_COOLDOWN_SECONDS)
    if now < ready_at:
        raise CommandError("resend_cooldown", 429, "Wait a moment before resending.")
    row.sends += 1
    row.last_sent_at = now
    row.expires_at = now + timedelta(seconds=dom.EXPIRES_AFTER_SECONDS)
    _deliver(session, case, row, now)
    return _out(row)


def _close(status: str) -> Callable[..., dict[str, Any]]:
    def effect(
        session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
    ) -> dict[str, Any]:
        row = _own(session, case, p.verification_id)
        _active(row)
        row.status = status
        row.resolved_at = now
        _clear_outbox(session, row.id)
        session.flush()
        return _out(row)

    return effect


def _cardholder_row(session: Session, case: Case, actor: Actor, vid: str) -> IdentityVerification:
    row = _own(session, case, vid)
    user = session.get(User, actor.user_id)
    if user is None or user.cardholder_id != row.cardholder_id:
        raise CommandError("role_forbidden", 403, "Only the cardholder can answer this request.")
    _active(row)
    return row


def _submit_otp(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _cardholder_row(session, case, actor, p.verification_id)
    if row.channel != "otp":
        raise CommandError("schema_invalid", 422, "This request is a push prompt, not a code.")
    if now >= row.expires_at:
        raise CommandError("verification_expired", 409, "The code has expired.")
    row.attempts += 1
    ok = row.code_salt is not None and hmac.compare_digest(
        hash_code(row.code_salt, p.code), row.code_hash or ""
    )
    session.add(
        VerificationAttempt(
            verification_id=row.id,
            attempt_no=row.attempts,
            outcome="accepted" if ok else "rejected",
            actor_id=actor.user_id,
            created_at=now,
        )
    )
    if ok:
        row.status = "verified"
    elif row.attempts >= row.max_attempts:
        row.status = "failed"
    if row.status != "requested":
        row.resolved_at = now
        _clear_outbox(session, row.id)
    session.flush()
    return _out(row, outcome="accepted" if ok else "rejected")


def _answer_push(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: EffectContext
) -> dict[str, Any]:
    row = _cardholder_row(session, case, actor, p.verification_id)
    if row.channel != "push":
        raise CommandError("schema_invalid", 422, "This request is a code, not a push prompt.")
    if now >= row.expires_at:
        raise CommandError("verification_expired", 409, "The prompt has expired.")
    row.attempts += 1
    outcome = "approved" if p.approve else "denied"
    session.add(
        VerificationAttempt(
            verification_id=row.id,
            attempt_no=row.attempts,
            outcome=outcome,
            actor_id=actor.user_id,
            created_at=now,
        )
    )
    row.status = "verified" if p.approve else "declined"
    row.resolved_at = now
    _clear_outbox(session, row.id)
    session.flush()
    return _out(row, outcome=outcome)


_OUTCOME_EVENT = {
    "verified": "verification.verified",
    "failed": "verification.locked",
    "declined": "verification.declined",
}


def _after_answer(
    session: Session,
    case: Case,
    actor: Actor,
    p: Any,
    now: datetime,
    ctx: EffectContext,
    out: Outcome,
) -> None:
    """Follow-on events, attributed to the cardholder: rejected code, lock, verified, declined."""
    status = str(ctx.extra["status"])
    vid = str(ctx.extra["verification_id"])
    detail = {k: ctx.extra[k] for k in ("verification_id", "attempts", "attempts_left")}
    types = []
    if ctx.extra.get("outcome") == "rejected":
        types.append("verification.code_rejected")
    if status in _OUTCOME_EVENT:
        types.append(_OUTCOME_EVENT[status])
    for t in types:
        _emit(
            session,
            t,
            case,
            actor.user_id,
            actor.active_role,
            now,
            [case.id, vid],
            dom.EVENTS[t],
            detail,
        )
    session.flush()


gateway.register_commands(
    __name__,
    human=dom.HUMAN,
    service=dom.SERVICE,
    effects={
        dom.SEND.name: _send,
        dom.RESEND.name: _resend,
        dom.CANCEL.name: _close("cancelled"),
        dom.EXPIRE.name: _close("expired"),
        dom.SUBMIT_OTP.name: _submit_otp,
        dom.ANSWER_PUSH.name: _answer_push,
    },
    after_effects={dom.SUBMIT_OTP.name: _after_answer, dom.ANSWER_PUSH.name: _after_answer},
    key_context=_key_context,
)


# ---- what the case view offers: the same preconditions the effects check -------------------------


def _ref_defaults(session: Session, case: Case) -> dict[str, Any]:
    row = current(session, case.id)
    return {"verification_id": row.id} if row is not None else {}


def _already_active(session: Session, case: Case) -> CommandError | None:
    row = current(session, case.id)
    if row is not None and row.status in ("requested", "verified"):
        return gateway.blocked("verification_active", "A verification request is already active.")
    return None


def _not_active(channel: str | None = None, *, resend: bool = False) -> gateway.ActionGuard:
    def guard(session: Session, case: Case) -> CommandError | None:
        row = current(session, case.id)
        if row is None:
            return gateway.blocked(
                "verification_not_active", "No verification request has been sent."
            )
        if row.status != "requested":
            reason = f"The verification request is {row.status}."
            return gateway.blocked("verification_not_active", reason)
        if resend and row.sends >= dom.MAX_SENDS:
            return gateway.blocked("send_limit_reached", dom.SEND_LIMIT_REASON)
        if channel == "otp" and row.channel != "otp":
            return gateway.blocked("schema_invalid", "This request is a push prompt, not a code.")
        if channel == "push" and row.channel != "push":
            return gateway.blocked("schema_invalid", "This request is a code, not a push prompt.")
        return None

    return guard


gateway.register_actions(
    __name__,
    defaults={
        name: _ref_defaults
        for name in (dom.RESEND.name, dom.CANCEL.name, dom.SUBMIT_OTP.name, dom.ANSWER_PUSH.name)
    },
    guards={
        dom.SEND.name: _already_active,
        dom.RESEND.name: _not_active(resend=True),
        dom.CANCEL.name: _not_active(),
        dom.SUBMIT_OTP.name: _not_active("otp"),
        dom.ANSWER_PUSH.name: _not_active("push"),
    },
)
gateway.register_fact_provider(_facts)
plugins.register_reset_tables(
    ["verification_outbox", "verification_attempts", "identity_verifications"]
)

EXPIRER_JOB = "verification_expirer"

SYSTEM = Actor(
    "svc-verification-expirer", "Verification expirer", Role.SYSTEM, frozenset({Role.SYSTEM})
)


def expire(session: Session, verification_id: str, now: datetime, request_id: str) -> Outcome:
    """Run expire_verification_request as the system; the key makes expiry recorded once."""
    row = session.get(IdentityVerification, verification_id)
    if row is None:
        raise CommandError("verification_not_found", 404, "No such verification request.")
    case = session.get(Case, row.case_id)
    assert case is not None
    key = f"idv-expire:{verification_id}"
    version = case.case_version
    session.rollback()
    return gateway.execute_command(
        session,
        now=now,
        case_id=row.case_id,
        command=dom.EXPIRE.name,
        key=key,
        expected_version=version,
        payload={"verification_id": verification_id},
        actor=SYSTEM,
        request_id=request_id,
    )


@worker.register(EXPIRER_JOB)
def _expirer_job(session: Session, payload: dict[str, Any], touch: worker.Touch) -> None:
    """Job payload: {"verification_id", "now"} (demo-clock ISO time). Idempotent by expire key."""
    row = session.get(IdentityVerification, payload["verification_id"])
    if row is None or row.status != "requested":
        return
    now = datetime.fromisoformat(payload["now"])
    if now >= row.expires_at:
        with Session(session.get_bind()) as own:  # the gateway owns its transaction
            expire(own, row.id, now, f"expirer:{row.id}")


def verification_expirer(factory: sessionmaker[Session], now: datetime) -> list[str]:
    """Sweep: enqueue a verification_expirer job for every request past its demo-clock deadline."""
    with factory() as s:
        due = list(
            s.scalars(
                select(IdentityVerification.id).where(
                    IdentityVerification.status == "requested",
                    IdentityVerification.expires_at <= now,
                )
            )
        )
        for vid in due:
            worker.enqueue(
                s, EXPIRER_JOB, {"verification_id": vid, "now": now.isoformat()}, now=now
            )
        s.commit()
    return due


# --- routes ---


class VerificationView(BaseModel):
    """Staff view: status, channel, attempts, timestamps. Never the code."""

    id: str
    case_id: str
    channel: Literal["otp", "push"]
    status: dom.IdentityStatus
    attempts: int
    max_attempts: int
    attempts_left: int
    sends: int
    sent_at: datetime
    last_sent_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


class OutboxView(BaseModel):
    """Synthetic-demo control acting as the cardholder: the simulated delivery."""

    synthetic: Literal[True] = True
    label: str = "Synthetic demo: simulated message to the cardholder's device"
    verification_id: str
    channel: Literal["otp", "push"]
    code: str | None
    attempts_left: int
    next_attempt_no: int


class CommandBody(BaseModel):
    idempotency_key: str
    expected_case_version: int


class OtpBody(CommandBody):
    code: str


class AnswerBody(CommandBody):
    approve: bool


class CommandOut(BaseModel):
    status: str
    result: dict[str, Any]
    event_ids: list[str]


def _view(row: IdentityVerification) -> VerificationView:
    return VerificationView(
        id=row.id,
        case_id=row.case_id,
        channel=row.channel,
        status=row.status,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        attempts_left=max(row.max_attempts - row.attempts, 0),
        sends=row.sends,
        sent_at=row.sent_at,
        last_sent_at=row.last_sent_at,
        expires_at=row.expires_at,
        resolved_at=row.resolved_at,
    )


router = APIRouter(prefix="/api")
synthetic_router = APIRouter(prefix="/api")


@router.get("/cases/{case_id}/verifications")
def list_verifications(
    case_id: str, session: DbSession, actor: ReaderDep
) -> list[VerificationView]:
    if actor.active_role not in STAFF_ROLES:
        raise CommandError("role_forbidden", 403, "This role cannot read verification requests.")
    rows = session.scalars(
        select(IdentityVerification)
        .where(IdentityVerification.case_id == case_id)
        .order_by(IdentityVerification.created_at, IdentityVerification.id)
    )
    return [_view(r) for r in rows]


def _cardholder_case(session: Session, actor: Actor, vid: str) -> IdentityVerification:
    if actor.active_role != Role.CARDHOLDER:
        raise CommandError("role_forbidden", 403, "Only the cardholder can use this control.")
    row = session.get(IdentityVerification, vid)
    user = session.get(User, actor.user_id)
    if row is None or user is None or user.cardholder_id != row.cardholder_id:
        raise CommandError("verification_not_found", 404, "No such verification request.")
    return row


def _run(
    request: Request,
    session: Session,
    actor: Actor,
    vid: str,
    command: str,
    body: CommandBody,
    payload: dict[str, Any],
) -> CommandOut:
    row = _cardholder_case(session, actor, vid)
    clock: Clock = request.app.state.clock
    case_id = row.case_id
    session.rollback()
    out = gateway.execute_command(
        session,
        now=clock.now(),
        case_id=case_id,
        command=command,
        key=body.idempotency_key,
        expected_version=body.expected_case_version,
        payload={"verification_id": vid, **payload},
        actor=actor,
        request_id=request.headers.get("x-request-id") or uuid.uuid4().hex,
    )
    return CommandOut(status=out.status, result=out.result, event_ids=out.event_ids)


@router.post("/verifications/{verification_id}/submit_otp")
def submit_otp(
    verification_id: str, body: OtpBody, request: Request, session: DbSession, actor: ReaderDep
) -> CommandOut:
    return _run(
        request, session, actor, verification_id, dom.SUBMIT_OTP.name, body, {"code": body.code}
    )


@router.post("/verifications/{verification_id}/answer")
def answer(
    verification_id: str,
    body: AnswerBody,
    request: Request,
    session: DbSession,
    actor: ReaderDep,
) -> CommandOut:
    return _run(
        request,
        session,
        actor,
        verification_id,
        dom.ANSWER_PUSH.name,
        body,
        {"approve": body.approve},
    )


@synthetic_router.get("/verifications/{verification_id}/outbox")
def outbox(
    verification_id: str, request: Request, session: DbSession, actor: ReaderDep
) -> OutboxView:
    row = _cardholder_case(session, actor, verification_id)
    clock: Clock = request.app.state.clock
    if row.status == "requested" and clock.now() >= row.expires_at:
        raise CommandError("verification_expired", 410, "The verification request has expired.")
    box = session.scalars(
        select(VerificationOutbox).where(VerificationOutbox.verification_id == row.id)
    ).first()
    if box is None:
        raise CommandError("outbox_empty", 404, "No active verification message.")
    return OutboxView(
        verification_id=row.id,
        channel=row.channel,
        code=box.code,
        attempts_left=max(row.max_attempts - row.attempts, 0),
        next_attempt_no=row.attempts + 1,
    )


class ExpireOut(BaseModel):
    status: str
    result: dict[str, Any]
    event_ids: list[str]


@synthetic_router.post("/demo/verifications/{verification_id}/expire")
def demo_expire(
    verification_id: str, request: Request, session: DbSession, actor: ReaderDep
) -> ExpireOut:
    """Synthetic demo trigger: run the verification_expirer job for one request now."""
    if actor.active_role not in STAFF_ROLES:
        _cardholder_case(session, actor, verification_id)  # only the owning cardholder
    clock: Clock = request.app.state.clock
    out = expire(session, verification_id, clock.now(), uuid.uuid4().hex)
    return ExpireOut(status=out.status, result=out.result, event_ids=out.event_ids)


plugins.register_router(router)
plugins.register_router(synthetic_router, synthetic_only=True)
