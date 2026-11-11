"""Assignable people for the case UI (VER-016). Read-only."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.enums import Role
from vera_domain.errors import CommandError
from vera_domain.models import AssignableUser, AssignableUsers

from vera_api.activity import ActorDep, DbSession, require_staff
from vera_api.auth import STAFF_ROLES
from vera_api.models import User, UserRole


def assignable_users(session: Session) -> AssignableUsers:
    """Users holding at least one staff role; their staff roles only (never the cardholder)."""
    staff = [r.value for r in STAFF_ROLES]
    rows = session.execute(
        select(User.id, User.name, UserRole.role)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role.in_(staff))
        .order_by(User.id, UserRole.role)
    )
    users: dict[str, AssignableUser] = {}
    for uid, name, role in rows:
        users.setdefault(uid, AssignableUser(id=uid, name=name, roles=[])).roles.append(Role(role))
    return AssignableUsers(users=list(users.values()))


router = APIRouter(prefix="/api")


@router.get("/users")
def get_users(session: DbSession, actor: ActorDep, assignable: bool = True) -> AssignableUsers:
    """Staff who can own a case. Only `assignable=true` is supported (the default)."""
    require_staff(actor, "the user list")
    if not assignable:
        raise CommandError("schema_invalid", 422, "assignable: only true is supported")
    return assignable_users(session)
