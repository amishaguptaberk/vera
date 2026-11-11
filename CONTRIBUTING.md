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

## Specialist runner, model clients and worker (VER-003A)

One runner (`vera_api.runner.SpecialistRunner`) serves two interchangeable model clients:
`LiveModelClient` (OpenAI-compatible chat completions, key from `NVIDIA_API_KEY`) and
`RecordedModelClient` (files under `evals/recordings/{specialist}/{prompt_version}/{case_id}[.{n}].json`,
`.n` being the n-th model call of a step). Modes never switch silently: if the mode is `live`
and the key is missing the step fails with `provider_error`; a live failure is only replaced by a
recording through an explicit retry with mode `replay`, and that step is stored as `replay`.
A missing recording is a `missing_recording` failure.

`VERA_EXECUTION_MODE` is `replay` in tests/CI (no key needed). `live` is the product default when
a key is present: set `VERA_EXECUTION_MODE=live` together with `NVIDIA_API_KEY`.

On a machine that can reach NVIDIA: `python -m vera_api.model_client probe` checks JSON-mode and
tool-call support of `VERA_MODEL_ID`; `python -m vera_api.model_client record --specialist S
--prompt-version V --case-id C --request req.json` runs one live call and writes a recording.

Schema: migration 0004 creates `workflow_runs`, `workflow_steps`, `jobs` and, through
`PostgresSaver.setup()`, the LangGraph checkpointer tables (dropped on downgrade). Run the worker
with `python -m vera_api.worker`.

## Investigation (VER-003B): run it in REPLAY and LIVE

`start_investigation` (analyst, after `open_case`, key `inv:{case_id}`) creates a run pinned to
the case's workflow and policy versions and enqueues a `specialist_runner` job. The worker runs
`charge_investigator` ∥ `related_transaction_investigator` → `receipt_document_reviewer` → `pc1`
(policy check) through LangGraph. A failed step stops the run; the case offers
`retry_specialist_step {step_key, mode: live|replay}` and `hold_case` in `recovery_actions`.

Configuration (names only; never commit values): `VERA_EXECUTION_MODE` (`live` or `replay`;
unset outside tests is a command error), `NVIDIA_API_KEY` (LIVE only), `VERA_MODEL_ID`,
`VERA_BASE_URL` (alias `VERA_MODEL_BASE_URL`), `VERA_RECORDINGS_DIR` (default `evals/recordings`).

REPLAY (offline):

```bash
export VERA_EXECUTION_MODE=replay
uv run uvicorn vera_api.app:create_app --factory --port 8000   # API
uv run python -m vera_api.worker                 # worker, in a second shell
```

LIVE (needs network and the key in the environment):

```bash
export VERA_EXECUTION_MODE=live NVIDIA_API_KEY=... VERA_MODEL_ID=...
uv run python -m vera_api.model_client probe
uv run python -m vera_api.investigation dump-requests   # evals/requests/{specialist}/v1/CHG-1042.json
```

The committed recordings are authored reference outputs (`model_id: authored-reference`); see
`evals/recordings/README.md` for capturing real ones.

LIVE requests use `response_format: {"type": "json_object"}` with the output JSON schema stated in
the prompt (not provider-side schema enforcement); every reply is validated after the fact by the
runner (pydantic schema, then grounding against the cited source fields), with two validation
retries.

<!-- VER-013:begin -->
## Checks (VER-013)

Backend (needs Postgres on `127.0.0.1:54329`, see Database; everything runs in REPLAY, no provider key):

```bash
uv sync --frozen
uv run ruff check . && uv run ruff format --check .
uv run mypy packages services
uv run alembic upgrade head
uv run pytest -q                      # unit, integration, contract, evals
```

Evaluation scenarios (data in `evals/scenarios/NN_name.json`, index in `evals/FIXTURES.md`):

```bash
uv run python -m evals.harness            # per-scenario PASS / FAIL / SKIPPED (pending) table
uv run python -m evals.harness --only 62  # one scenario
```

The harness RESETS the database it uses: `VERA_EVAL_DATABASE_URL`, else `VERA_TEST_DATABASE_URL`,
else `vera_test`. A failure names the scenario, case, workflow version, step and the broken
invariant. A scenario with `"status": "pending"` and `"requires": "VER-0xx"` is reported as
SKIPPED; the ticket that lands the stage replaces it with real steps and assertions.

Contract snapshot (API drift): `tests/contract/openapi.snapshot.json` must equal
`create_app().openapi()`. After an intentional API change regenerate and commit it:

```bash
uv run python -m evals.snapshot_openapi
```

Frontend (`apps/web`):

```bash
cd apps/web && npm ci
npm run typecheck && npm run lint && npm test && npm run build
npx playwright install --with-deps chromium && npm run test:parity   # needs a prior build
```

CI is `.github/workflows/ci.yml` (jobs `backend`, `frontend`, `frontend-browser`).

## Resettable demo seed

`POST /api/demo/reset` (only when `VERA_ENV=synthetic`) truncates every application table
(`ALL_TABLES`, with `restart identity cascade`; the append-only triggers stay in place), then
re-seeds the canonical data: users and roles, cardholders, merchants, transactions, the seeded
cases (CHG-1042 is the live case), reports and claims, evidence records and versions, and policy
v1. It also clears workflow runs, steps, queued jobs and LangGraph checkpoints, so a
mid-investigation reset leaves nothing behind. Case versions return to 1 and the demo clock is
fixed at 2026-11-10 09:08 (`VERA_DEMO_TZ`). Reset never calls a provider; the evals call it before
every scenario.
<!-- VER-013:end -->
