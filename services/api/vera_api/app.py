from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from vera_domain.clock import Clock, default_demo_clock
from vera_domain.models import CaseView, QueueRow, Summary

from vera_api import queries
from vera_api.config import Settings
from vera_api.db import make_engine
from vera_api.intake import CaseNotOpenableError, UnknownTransactionError, submit_report
from vera_api.models import ALL_TABLES
from vera_api.seed import reset_database


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


DbSession = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

cases = APIRouter(prefix="/api")


@cases.get("/cases")
def list_cases(session: DbSession, clock: ClockDep, settings: SettingsDep) -> list[QueueRow]:
    return queries.list_cases(session, clock.now(), settings.demo_tz)


@cases.get("/cases/summary")
def summary(session: DbSession, clock: ClockDep, settings: SettingsDep) -> Summary:
    return queries.summarize(session, clock.now(), settings.demo_tz)


@cases.get("/cases/{case_id}")
def get_case(case_id: str, session: DbSession, clock: ClockDep, settings: SettingsDep) -> CaseView:
    try:
        return queries.get_case_view(session, case_id, clock.now(), settings.demo_tz)
    except queries.CaseNotFoundError:
        raise HTTPException(404, {"code": "case_not_found", "message": "No such case."}) from None
    except queries.CaseNotOpenableError:
        raise HTTPException(
            404,
            {
                "code": "case_not_openable",
                "message": "This row is display-only and cannot be opened.",
            },
        ) from None


class ReportIn(BaseModel):
    report_id: str
    transaction_id: str
    statement: str


class ReportOut(BaseModel):
    case_id: str
    report_id: str
    created: bool


@cases.post("/reports")
def post_report(
    body: ReportIn, session: DbSession, clock: ClockDep, settings: SettingsDep
) -> ReportOut:
    try:
        result = submit_report(
            session,
            report_id=body.report_id,
            transaction_id=body.transaction_id,
            statement=body.statement,
            now=clock.now(),
        )
    except UnknownTransactionError:
        raise HTTPException(
            404, {"code": "transaction_not_found", "message": "Unknown transaction."}
        ) from None
    except CaseNotOpenableError:
        raise HTTPException(
            409,
            {
                "code": "case_not_openable",
                "message": "This transaction's case is display-only and cannot take reports.",
            },
        ) from None
    session.commit()
    return ReportOut(case_id=result.case_id, report_id=result.report_id, created=result.created)


demo = APIRouter(prefix="/api/demo")


@demo.post("/reset")
def reset(session: DbSession, clock: ClockDep, settings: SettingsDep) -> dict[str, str]:
    reset_database(session, clock, settings.demo_tz)
    return {"status": "reset"}


@demo.get("/counts")
def counts(session: DbSession) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in ALL_TABLES:
        out[table] = session.execute(text(f"select count(*) from {table}")).scalar_one()
    return out


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Vera API")
    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.clock = clock or default_demo_clock(settings.demo_tz)
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.include_router(cases)
    if settings.synthetic:
        app.include_router(demo)
    return app
