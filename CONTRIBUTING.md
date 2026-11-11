# Contributing

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12
uv sync
cp .env.example .env   # optional; defaults match the values below
```

## Database

Postgres 16 on `127.0.0.1:54329` (role `vera`/`vera`, databases `vera` and `vera_test`).

- With Docker: `docker compose -f infra/docker-compose.yml up -d postgres`
- Without Docker: `infra/dev-db.sh start|stop|reset|status` (data in `${VERA_PGDATA:-/tmp/vera-pg}`;
  uses the `postgres` user when run as root).

Apply migrations: `uv run alembic upgrade head` (uses `VERA_DATABASE_URL`).

## Run the API

```bash
uv run uvicorn vera_api.app:create_app --factory --reload
```

Environment: `VERA_DATABASE_URL`, `VERA_ENV` (`synthetic` enables `/api/demo/*`, default),
`VERA_DEMO_TZ` (default `America/Los_Angeles`; the demo clock is fixed at 2026-11-10 09:08 in it).
Seed the canonical data with `POST /api/demo/reset`.

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy packages services
infra/dev-db.sh start && uv run alembic upgrade head
uv run pytest -q            # integration tests use VERA_TEST_DATABASE_URL (default: vera_test)
```

## Layout

- `packages/domain/vera_domain`: pure Python (enums, Pydantic models, clock). No SQLAlchemy or FastAPI.
- `services/api/vera_api`: FastAPI app, SQLAlchemy models, intake, seed and reset.
- `infra/migrations`: Alembic. History tables (`audit_events`, `reports`, `claims`,
  `state_transitions`) are append-only through database triggers; reset uses `TRUNCATE`.

## Case writes (VER-002)

Every case write goes through `vera_api.gateway.execute_command` (commands registered in
`vera_domain.commands.REGISTRY`; state/step come only from `vera_domain.facts.derive_step`).
Set `VERA_SESSION_SECRET` for any non-synthetic environment; `POST /api/session/role` exists
only when `VERA_ENV=synthetic`.

Idempotency keys: the server resolves the command's key template from the case, the actor and
the payload (`report:{report_id}`, `hold:{case_id}:{case_version}`); the client's
`idempotency_key` must equal it (else 422 `idempotency_key_mismatch`). Every `ActionView`
carries a fully resolved `idempotency_key` (never a placeholder) that the client echoes as
given. Server-allocated payload fields (the next `report_id` for `link_report`) come in
`ActionView.payload_defaults`; the client merges them under its own payload. `key_template` is
informational only. A key replayed with a different command, user, role or payload returns
409 `idempotency_key_conflict`. `link_report` creates the linked report
row itself (payload needs `report_id` and `statement`) and rejects ids that already exist,
including the case's original report.

Demo-only behavior: in the synthetic environment a missing or tampered session cookie falls back
to Sam Rivera as analyst. Any other environment returns 401 `unauthenticated` instead.
