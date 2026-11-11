import uuid
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from vera_domain.clock import Clock, default_demo_clock
from vera_domain.commands import ReportId
from vera_domain.enums import Role
from vera_domain.errors import CommandError
from vera_domain.exposure import MixedCurrencyError
from vera_domain.models import ActionView, CaseView, Person, QueueRow, Summary

from vera_api import auth, queries
from vera_api import evidence as evidence_api
from vera_api.auth import Actor
from vera_api.config import Settings
from vera_api.db import make_engine
from vera_api.gateway import execute_command
from vera_api.intake import CaseNotOpenableError, UnknownTransactionError, submit_report
from vera_api.models import ALL_TABLES
from vera_api.policy import router as policy_router
from vera_api.runs import router as runs_router
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


def get_actor(request: Request, session: DbSession, settings: SettingsDep) -> Actor:
    return auth.load_actor(
        session,
        settings.secret(),
        auth.session_cookie(request.headers.getlist("cookie")),
        settings.synthetic,
    )


ActorDep = Annotated[Actor, Depends(get_actor)]

cases = APIRouter(prefix="/api")


@cases.get("/cases")
def list_cases(session: DbSession, clock: ClockDep, settings: SettingsDep) -> list[QueueRow]:
    return queries.list_cases(session, clock.now(), settings.demo_tz)


@cases.get("/cases/summary")
def summary(session: DbSession, clock: ClockDep, settings: SettingsDep) -> Summary:
    try:
        return queries.summarize(session, clock.now(), settings.demo_tz)
    except MixedCurrencyError as exc:
        raise CommandError("mixed_currency", 409, str(exc)) from None


def _view(
    session: Session, case_id: str, clock: Clock, settings: Settings, actor: Actor
) -> CaseView:
    try:
        return queries.get_case_view(
            session,
            case_id,
            clock.now(),
            settings.demo_tz,
            (actor.user_id, actor.active_role) if actor.active_role in actor.roles else None,
        )
    except queries.CaseNotFoundError:
        raise CommandError("case_not_found", 404, "No such case.") from None
    except queries.CaseNotOpenableError:
        raise CommandError(
            "case_not_openable", 404, "This row is display-only and cannot be opened."
        ) from None


@cases.get("/cases/{case_id}")
def get_case(
    case_id: str, session: DbSession, clock: ClockDep, settings: SettingsDep, actor: ActorDep
) -> CaseView:
    return _view(session, case_id, clock, settings, actor)


@cases.get("/cases/{case_id}/available-actions")
def available(
    case_id: str, session: DbSession, clock: ClockDep, settings: SettingsDep, actor: ActorDep
) -> list[ActionView]:
    return _view(session, case_id, clock, settings, actor).available_actions


class CommandIn(BaseModel):
    idempotency_key: str = Field(min_length=1)
    expected_case_version: int
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandOut(BaseModel):
    status: Literal["recorded", "replayed"]
    result: dict[str, Any]
    event_ids: list[str]
    case: CaseView


@cases.post("/cases/{case_id}/commands/{command}")
def run_command(
    case_id: str,
    command: str,
    body: CommandIn,
    request: Request,
    session: DbSession,
    clock: ClockDep,
    settings: SettingsDep,
    actor: ActorDep,
) -> CommandOut:
    outcome = execute_command(
        session,
        now=clock.now(),
        case_id=case_id,
        command=command,
        key=body.idempotency_key,
        expected_version=body.expected_case_version,
        payload=body.payload,
        actor=actor,
        request_id=request.headers.get("x-request-id") or uuid.uuid4().hex,
    )
    return CommandOut(
        status="replayed" if outcome.status == "replayed" else "recorded",
        result=outcome.result,
        event_ids=outcome.event_ids,
        case=_view(session, case_id, clock, settings, actor),
    )


session_router = APIRouter(prefix="/api")
role_router = APIRouter(prefix="/api")  # demo only: mounted in the synthetic environment


class SessionOut(BaseModel):
    user: Person
    active_role: Role
    roles: list[Role]
    environment: str


class RoleIn(BaseModel):
    role: Role


def _session_out(actor: Actor, settings: Settings) -> SessionOut:
    active = actor.active_role
    if active not in actor.roles:  # a signed cookie may name a role the user does not hold
        held = [r for r in auth.HUMAN_ROLES if r in actor.roles]
        if not held:
            raise CommandError("unauthenticated", 401, "The session holds no role.")
        active = auth.DEFAULT_ROLE if auth.DEFAULT_ROLE in held else held[0]
    return SessionOut(
        user=Person(id=actor.user_id, name=actor.name),
        active_role=active,
        roles=sorted(actor.roles),
        environment=settings.env,
    )


@session_router.get("/session")
def get_session_info(actor: ActorDep, settings: SettingsDep) -> SessionOut:
    return _session_out(actor, settings)


@role_router.post("/session/role")
def switch_role(
    body: RoleIn, response: Response, session: DbSession, settings: SettingsDep
) -> SessionOut:
    """Demo view change only: the server picks the user; nothing is written to cases."""
    if body.role not in auth.HUMAN_ROLES:
        raise CommandError("schema_invalid", 422, f"{body.role.value} is not a demo role.")
    user = auth.user_for_role(session, body.role)
    if user is None:
        raise CommandError("schema_invalid", 422, f"Nobody holds the {body.role.value} role.")
    secret = settings.secret()
    cookie = auth.sign(secret, user.id, body.role.value)
    response.set_cookie(auth.COOKIE, cookie, httponly=True, samesite="lax")
    actor = auth.load_actor(session, secret, cookie, settings.synthetic)
    return _session_out(actor, settings)


class ReportIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    report_id: ReportId
    transaction_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)


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
        raise CommandError("transaction_not_found", 404, "Unknown transaction.") from None
    except CaseNotOpenableError:
        raise CommandError(
            "case_not_openable",
            409,
            "This transaction's case is display-only and cannot take reports.",
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
    settings.secret()  # fail fast when a non-synthetic env has no session secret
    app = FastAPI(title="Vera API")

    @app.exception_handler(CommandError)
    async def _command_error(_: Request, exc: CommandError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.http_status)

    @app.exception_handler(ValidationError)
    async def _model_invalid(_: Request, exc: ValidationError) -> JSONResponse:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "body"
        return JSONResponse(
            {"code": "schema_invalid", "message": f"{where}: {first['msg']}"}, status_code=422
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"][1:]) or "body"
        return JSONResponse(
            {"code": "schema_invalid", "message": f"{where}: {first['msg']}"}, status_code=422
        )

    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.clock = clock or default_demo_clock(settings.demo_tz)
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.include_router(cases)
    app.include_router(policy_router)
    app.include_router(session_router)
    app.include_router(runs_router)
    app.include_router(evidence_api.router)
    if settings.synthetic:
        app.include_router(role_router)
        app.include_router(demo)
        app.include_router(evidence_api.demo_router)
    return app
