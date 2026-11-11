"""Signed demo session cookie and the actor it resolves to. The actor never comes from a body."""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.enums import Role
from vera_domain.errors import CommandError

from vera_api.models import User, UserRole

COOKIE = "vera_session"
DEFAULT_USER = "usr-sam-rivera"
DEFAULT_ROLE = Role.ANALYST
# Roles a person can pick in the demo; service principals are never selectable.
HUMAN_ROLES = (Role.ANALYST, Role.OPS_ADMIN, Role.REVIEWER, Role.CARD_ADMIN, Role.CARDHOLDER)
# Roles that may own a case.
STAFF_ROLES = (Role.ANALYST, Role.OPS_ADMIN, Role.REVIEWER, Role.CARD_ADMIN)


@dataclass(frozen=True)
class Actor:
    user_id: str
    name: str
    active_role: Role
    roles: frozenset[Role]


def sign(secret: str, user_id: str, role: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"user_id": user_id, "active_role": role}).encode())
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{body.decode()}.{mac}"


def verify(secret: str, cookie: str | None) -> tuple[str, str] | None:
    """Return (user_id, active_role) for a correctly signed cookie, else None."""
    if not cookie or "." not in cookie:
        return None
    body, _, mac = cookie.rpartition(".")
    good = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, good):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body.encode()))
        return str(data["user_id"]), str(data["active_role"])
    except (ValueError, KeyError, TypeError):
        return None


def _roles_of(session: Session, user_id: str) -> frozenset[Role]:
    rows = session.scalars(select(UserRole.role).where(UserRole.user_id == user_id)).all()
    return frozenset(Role(r) for r in rows if r in Role._value2member_map_)


def load_actor(session: Session, secret: str, cookie: str | None, synthetic: bool) -> Actor:
    claim = verify(secret, cookie)
    if claim is None:
        if not synthetic:
            raise CommandError("unauthenticated", 401, "Sign in to continue.")
        claim = (DEFAULT_USER, DEFAULT_ROLE.value)
    user_id, role_name = claim
    user = session.get(User, user_id)
    if user is None:
        raise CommandError("unauthenticated", 401, "Unknown session user.")
    roles = _roles_of(session, user_id)
    # The cookie's role claim is not trusted: the database must say this user holds it.
    active = Role(role_name) if role_name in Role._value2member_map_ else None
    if active is None or active not in roles:
        # Keep the identity but deny acting under a role the user does not hold.
        return Actor(user.id, user.name, active or Role.SYSTEM, roles - {active or Role.SYSTEM})
    return Actor(user.id, user.name, active, roles)


def user_for_role(session: Session, role: Role) -> User | None:
    """The seeded person who actually holds this role (user_roles), chosen by the server."""
    return session.scalars(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role == role.value)
        .order_by(User.id)
    ).first()
