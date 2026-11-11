"""Case activity feed and queue filter counts: read-only views over stored rows (VER-016)."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.errors import CommandError
from vera_domain.labels import event_summary
from vera_domain.models import ActivityEvent, ActivityFeed, FilterCounts

from vera_api import auth, queries
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.config import Settings
from vera_api.models import AuditEvent, Case, User


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


DbSession = Annotated[Session, Depends(_session)]


def _actor(request: Request, session: DbSession) -> Actor:
    settings: Settings = request.app.state.settings
    return auth.load_actor(
        session,
        settings.secret(),
        auth.session_cookie(request.headers.getlist("cookie")),
        settings.synthetic,
    )


ActorDep = Annotated[Actor, Depends(_actor)]


def require_staff(actor: Actor, what: str) -> None:
    """Same rule as the evidence register: an active staff role the user really holds."""
    if actor.active_role not in STAFF_ROLES or actor.active_role not in actor.roles:
        raise CommandError("role_forbidden", 403, f"This role cannot read {what}.")


def case_activity(session: Session, case_id: str, after: int | None) -> ActivityFeed:
    if session.get(Case, case_id) is None:
        raise CommandError("case_not_found", 404, "No such case.")
    stmt = select(AuditEvent).where(AuditEvent.case_id == case_id)
    if after is not None:
        stmt = stmt.where(AuditEvent.id > after)
    events = session.scalars(stmt.order_by(AuditEvent.id)).all()
    ids = {e.actor_id for e in events}
    names = {u.id: u.name for u in session.scalars(select(User).where(User.id.in_(ids)))}
    return ActivityFeed(
        events=[
            ActivityEvent(
                id=e.id,
                type=e.type,
                at=e.at,
                actor_name=names.get(e.actor_id, e.actor_id),
                actor_role=e.actor_role,
                summary=event_summary(e.type),
                record_ids=[str(r) for r in e.record_ids],
            )
            for e in events
        ]
    )


router = APIRouter(prefix="/api")


@router.get("/cases/filter-counts")
def get_filter_counts(request: Request, session: DbSession, actor: ActorDep) -> FilterCounts:
    """Counts for the queue filter chips; `mine` is relative to the session user."""
    require_staff(actor, "the case queue")
    settings: Settings = request.app.state.settings
    clock = request.app.state.clock
    return queries.filter_counts(session, clock.now(), settings.demo_tz, actor.user_id)


@router.get("/cases/{case_id}/activity")
def get_activity(
    case_id: str,
    session: DbSession,
    actor: ActorDep,
    after: Annotated[int | None, Query(ge=0, le=2**63 - 1)] = None,
) -> ActivityFeed:
    """Audit events for the case, oldest first; `after` = last event id seen (polling)."""
    require_staff(actor, "case activity")
    return case_activity(session, case_id, after)
