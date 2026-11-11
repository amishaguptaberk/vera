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
