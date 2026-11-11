# Deploying Vera

Vera ships as two images plus Postgres 16:

| Service  | Image build        | Command                         | Port |
|----------|--------------------|---------------------------------|------|
| `api`    | `Dockerfile.api`   | `api` (migrate, then uvicorn)   | 8000 |
| `worker` | `Dockerfile.api`   | `worker` (waits for DB, polls jobs) | none |
| `web`    | `Dockerfile.web`   | `next start -H 0.0.0.0 -p 3000` | 3000 |

The entrypoint (`infra/docker/entrypoint.sh`) has modes `api`, `worker`, `migrate`; any other
arguments are exec'd as a command (for example `python -m vera_api.model_client probe`).

> Status: these images and the compose file were written in a workspace with no Docker daemon.
> `docker compose config`, `bash -n` on the entrypoint and a clean `uv sync --frozen --no-dev`
> import check were run; the images were NOT built or run. Expect to fix small things on the first build.

## (a) Local run, REPLAY (no key needed)

```bash
cd infra
docker compose up --build
```

Open http://localhost:3000. REPLAY reads recordings from `evals/recordings` baked into the API image.
`VERA_EXECUTION_MODE` defaults to `replay` in compose. Postgres is also published on host port 54329.

## (b) LIVE run

Set these names (values from your provider; never commit them) in the shell, or in a `.env`
at the repo root passed with `--env-file`:

```bash
cp .env.example .env     # then edit: NVIDIA_API_KEY, VERA_MODEL_ID, VERA_BASE_URL
cd infra
VERA_EXECUTION_MODE=live docker compose --env-file ../.env up --build
```

Compose passes `NVIDIA_API_KEY`, `VERA_SESSION_SECRET`, `VERA_MODEL_ID`, `VERA_BASE_URL` through by
name with no values in the file. Use `--env-file ../.env` or exported shell variables; a plain
`.env` is not read for pass-through otherwise. (Also set `VERA_EXECUTION_MODE=live` there.)

Check the model supports JSON mode and tool calls:

```bash
docker compose --env-file ../.env run --rm api python -m vera_api.model_client probe
```

Capture a recording (one LIVE call, written under `evals/recordings`; the container path is
inside the image, so run this from a dev checkout with `uv run` and commit the file, then rebuild):

```bash
uv run python -m vera_api.model_client record --specialist S --prompt-version V \
  --case-id CHG-1042 --request request.json
```

**LIVE has never been exercised against the real provider from the build workspace.** Treat the
first LIVE run as untested. Note that without `VERA_EXECUTION_MODE` set, the app refuses to start
model calls (no silent replay), so always set it.

## (c) Generic container host

Run three services (api, worker, web) plus Postgres 16. api and worker share the same image and
the same environment. The API runs `alembic upgrade head` on start.

| Name | Required? | Purpose | Example |
|------|-----------|---------|---------|
| `VERA_DATABASE_URL` | yes | SQLAlchemy URL, api and worker | `postgresql+psycopg://vera:vera@postgres:5432/vera` |
| `VERA_ENV` | yes | `synthetic` enables demo routes; anything else is non-demo | `synthetic` |
| `VERA_EXECUTION_MODE` | yes | `replay` or `live` (no default outside tests) | `replay` |
| `VERA_DEMO_TZ` | no | demo clock timezone | `America/Los_Angeles` |
| `VERA_SESSION_SECRET` | yes unless `VERA_ENV=synthetic` | session signing | secret |
| `NVIDIA_API_KEY` | live only | model provider key | secret |
| `VERA_MODEL_ID` | no | model id | `meta/llama-3.3-70b-instruct` |
| `VERA_BASE_URL` | no | OpenAI-compatible endpoint | `https://integrate.api.nvidia.com/v1` |
| `VERA_API_ORIGIN` | web build arg | where the web proxies `/api/*` | `http://api:8000` |
| `VERA_DB_WAIT_SECONDS` | no | entrypoint DB wait | `60` |
| `PORT` | no | api listen port (default 8000) | `8000` |

`VERA_MODEL_PROVIDER` appears in `.env.example` but is not read by any code.

**The API origin is build-time.** `apps/web/next.config.mjs` evaluates the `/api/*` rewrite during
`next build` and Next bakes the destination in. Changing the origin needs a web image rebuild:
`docker build -f Dockerfile.web --build-arg VERA_API_ORIGIN=https://api.internal:8000 .`
(the Dockerfile sets both `VERA_API_ORIGIN` and `VERA_API_URL`). The browser only talks to the
web service; the web server must be able to reach the API origin. Health checks: `GET /api/health`
(no session; checks the database; 503 when it is unreachable).

## (d) Synthetic vs non-synthetic

Demo role switching (`POST /api/session/role`) and `/api/demo/*` are mounted only when
`VERA_ENV=synthetic`. Outside synthetic, `VERA_SESSION_SECRET` is required and there is no login
yet, so a non-synthetic deployment has no way to obtain a session. Deploy with `synthetic`.

## (e) Smoke test

```bash
API=http://localhost:8000   # or http://localhost:3000 to go through the web proxy
curl -fsS $API/api/session
curl -fsS -X POST $API/api/demo/reset
curl -fsS $API/api/cases
curl -fsS $API/api/cases/CHG-1042
```
