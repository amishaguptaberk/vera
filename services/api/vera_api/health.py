"""Liveness for container healthchecks: no session, no data, just a database round trip."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from vera_domain.errors import CommandError

router = APIRouter(prefix="/api")


class Health(BaseModel):
    status: Literal["ok"]


@router.get("/health")
def health(request: Request) -> Health:
    try:
        with request.app.state.session_factory() as session:
            session.execute(text("select 1"))
    except SQLAlchemyError:
        raise CommandError("database_unavailable", 503, "The database is unreachable.") from None
    return Health(status="ok")
