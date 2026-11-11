#!/usr/bin/env bash
# One-command demo for Vera (synthetic environment; no funds move, no real provider in replay).
#
#   infra/demo.sh up       start API + worker + web in REPLAY, migrate, seed (demo reset), print URL
#   infra/demo.sh live     same, but VERA_EXECUTION_MODE=live (needs NVIDIA_API_KEY exported)
#   infra/demo.sh reset    stop worker, POST /api/demo/reset (also clears runs/jobs/checkpoints), restart worker
#   infra/demo.sh status   what is running, health, environment, mode
#   infra/demo.sh down     stop ONLY the processes this script started (pidfiles in $VERA_DEMO_RUN)
#
# Overrides (env): VERA_DEMO_DB (vera_demo), VERA_DEMO_API_PORT (8300), VERA_DEMO_WEB_PORT (3300),
#   VERA_DEMO_PG_HOST (127.0.0.1), VERA_DEMO_PG_PORT (54329), VERA_DEMO_RUN (/tmp/vera-demo),
#   VERA_DEMO_SKIP_WEB=1 (backend only), VERA_DEMO_REBUILD=1 (force `next build`),
#   VERA_DEMO_WEB_DIR (web app dir to build/serve; default apps/web of this checkout).
# Never stops Postgres, never kills anything it did not start.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${VERA_DEMO_DB:-vera_demo}"
API_PORT="${VERA_DEMO_API_PORT:-8300}"
WEB_PORT="${VERA_DEMO_WEB_PORT:-3300}"
PG_HOST="${VERA_DEMO_PG_HOST:-127.0.0.1}"
PG_PORT="${VERA_DEMO_PG_PORT:-54329}"
RUN="${VERA_DEMO_RUN:-/tmp/vera-demo}"
PGBIN="${VERA_PGBIN:-/usr/lib/postgresql/16/bin}"
API="http://127.0.0.1:${API_PORT}"
WEB="http://127.0.0.1:${WEB_PORT}"

export VERA_DATABASE_URL="postgresql+psycopg://vera:vera@${PG_HOST}:${PG_PORT}/${DB}"
export VERA_ENV=synthetic
# Not `python -m vera_api.worker`: run as __main__, the module's HANDLERS dict is a different
# object from the one vera_api.investigation registers into, so every job fails with
# KeyError 'specialist_runner'. Importing the module by name runs the same main().
WORKER_PY='from vera_api.worker import main; main()'

say() { printf '[demo] %s\n' "$*"; }
die() { printf '[demo] ERROR: %s\n' "$*" >&2; exit 1; }

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

read_pid() { [ -f "$RUN/$1.pid" ] && cat "$RUN/$1.pid" || true; }

# start NAME LOGFILE CMD... : new session (own process group) so `down` can stop its children too.
start_proc() {
  local name="$1"; shift
  local pid
  pid="$(read_pid "$name")"
  if pid_alive "$pid"; then say "$name already running (pid $pid)"; return 0; fi
  ( cd "$ROOT" && exec setsid "$@" >"$RUN/$name.log" 2>&1 < /dev/null ) &
  echo $! > "$RUN/$name.pid"
  say "$name started (pid $!, log $RUN/$name.log)"
}

stop_proc() {
  local name="$1" pid
  pid="$(read_pid "$name")"
  if ! pid_alive "$pid"; then rm -f "$RUN/$name.pid"; return 0; fi
  # setsid made pid the process-group leader: signal only that group.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 50); do pid_alive "$pid" || break; sleep 0.1; done
  if pid_alive "$pid"; then kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true; fi
  rm -f "$RUN/$name.pid"
  say "$name stopped (pid $pid)"
}

wait_http() {  # url seconds
  for _ in $(seq 1 "$2"); do
    curl -fsS -o /dev/null "$1" 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

ensure_db() {
  if PGPASSWORD=vera "$PGBIN/psql" -h "$PG_HOST" -p "$PG_PORT" -U vera -d "$DB" -tAc 'select 1' >/dev/null 2>&1; then
    return 0
  fi
  say "database $DB not reachable as vera; creating it (dev superuser of infra/dev-db.sh)"
  PGPASSWORD=superpw "$PGBIN/psql" -h "$PG_HOST" -p "$PG_PORT" -U postgres -d postgres \
    -v ON_ERROR_STOP=1 -c "create database $DB owner vera" >/dev/null \
    || die "cannot reach or create database $DB on $PG_HOST:$PG_PORT (is Postgres running? infra/dev-db.sh start)"
}

do_reset() {
  local had_worker=0
  pid_alive "$(read_pid worker)" && had_worker=1
  [ "$had_worker" = 1 ] && stop_proc worker
  curl -fsS -X POST "$API/api/demo/reset" >/dev/null || die "demo reset failed (is the API up? $API)"
  say "demo data reset (cases, evidence, runs, jobs, checkpoints, feature tables)"
  if [ "$had_worker" = 1 ]; then
    start_proc worker env VERA_EXECUTION_MODE="$(cat "$RUN/mode" 2>/dev/null || echo replay)" \
      uv run --no-sync python -c "$WORKER_PY"
  fi
}

up() {
  local mode="$1"
  mkdir -p "$RUN"
  if [ "$mode" = live ]; then
    [ -n "${NVIDIA_API_KEY:-}" ] || die "LIVE mode needs NVIDIA_API_KEY exported in this shell (it is read from the environment only). Not starting."
  else
    unset NVIDIA_API_KEY  # replay never reaches a provider
  fi
  if [ -f "$RUN/mode" ] && pid_alive "$(read_pid api)" && [ "$(cat "$RUN/mode")" != "$mode" ]; then
    die "demo already running in $(cat "$RUN/mode") mode; run infra/demo.sh down first"
  fi
  export VERA_EXECUTION_MODE="$mode"
  echo "$mode" > "$RUN/mode"

  pid_alive "$(read_pid api)" || ! port_busy "$API_PORT" || die "port $API_PORT is in use by something else (set VERA_DEMO_API_PORT)"
  if [ "${VERA_DEMO_SKIP_WEB:-0}" != 1 ]; then
    pid_alive "$(read_pid web)" || ! port_busy "$WEB_PORT" || die "port $WEB_PORT is in use by something else (set VERA_DEMO_WEB_PORT)"
  fi

  ensure_db
  say "migrating $DB"
  (cd "$ROOT" && uv run --no-sync alembic upgrade head >"$RUN/migrate.log" 2>&1) \
    || { tail -20 "$RUN/migrate.log" >&2; die "migration failed"; }

  start_proc api uv run --no-sync uvicorn vera_api.app:create_app --factory \
    --host 127.0.0.1 --port "$API_PORT"
  wait_http "$API/api/health" 60 || { tail -20 "$RUN/api.log" >&2; die "API did not become healthy"; }
  say "API healthy at $API"

  do_reset
  start_proc worker uv run --no-sync python -c "$WORKER_PY"

  if [ "${VERA_DEMO_SKIP_WEB:-0}" != 1 ]; then
    local web="${VERA_DEMO_WEB_DIR:-$ROOT/apps/web}"
    export VERA_API_ORIGIN="$API" VERA_API_URL="$API"
    if [ ! -f "$web/node_modules/.package-lock.json" ] \
       || [ "$web/package-lock.json" -nt "$web/node_modules/.package-lock.json" ]; then
      say "installing web dependencies (npm ci)"
      (cd "$web" && npm ci --no-audit --no-fund >"$RUN/web-install.log" 2>&1) \
        || { tail -20 "$RUN/web-install.log" >&2; die "npm ci failed"; }
    fi
    # Rewrites are baked in at build time, so rebuild when the API origin changes.
    if [ "${VERA_DEMO_REBUILD:-0}" = 1 ] || [ ! -f "$web/.next/BUILD_ID" ] \
       || [ "$(cat "$RUN/web-origin" 2>/dev/null)" != "$API $web" ] \
       || [ -n "$(find "$web/src" "$web/next.config.mjs" -newer "$web/.next/BUILD_ID" -print -quit 2>/dev/null)" ]; then
      say "building web (next build, ~1-2 min)"
      (cd "$web" && npx next build >"$RUN/web-build.log" 2>&1) \
        || { tail -30 "$RUN/web-build.log" >&2; die "web build failed (backend is still up; VERA_DEMO_SKIP_WEB=1 to skip)"; }
      echo "$API $web" > "$RUN/web-origin"
    fi
    start_proc web bash -c "cd '$web' && exec npx next start -H 127.0.0.1 -p $WEB_PORT"
    wait_http "$WEB/" 60 || { tail -20 "$RUN/web.log" >&2; die "web did not answer on $WEB"; }
  fi

  say "------------------------------------------------------------"
  say "Vera demo up  mode=$(echo "$mode" | tr a-z A-Z)  env=synthetic  db=$DB"
  say "API  $API   (docs $API/docs)"
  [ "${VERA_DEMO_SKIP_WEB:-0}" = 1 ] || say "Open $WEB"
  say "Between takes: infra/demo.sh reset   Stop: infra/demo.sh down"
}

status() {
  local n pid
  for n in api worker web; do
    pid="$(read_pid "$n")"
    if pid_alive "$pid"; then say "$n: running (pid $pid)"; else say "$n: not running"; fi
  done
  say "mode: $(cat "$RUN/mode" 2>/dev/null || echo unknown)  db: $DB"
  if curl -fsS -o /dev/null "$API/api/health" 2>/dev/null; then
    say "API health: ok ($API)"
    curl -fsS "$API/api/session" 2>/dev/null | sed 's/^/[demo] session: /' || true
    echo
    curl -fsS "$API/api/cases/CHG-1042" 2>/dev/null \
      | python3 -c 'import json,sys; v=json.load(sys.stdin); print("[demo] CHG-1042:", v["state"], "/", v["step"], "v%d" % v["case_version"])' 2>/dev/null || true
  else
    say "API health: DOWN ($API)"
  fi
  [ "${VERA_DEMO_SKIP_WEB:-0}" = 1 ] || { curl -fsS -o /dev/null "$WEB/" 2>/dev/null && say "web: ok ($WEB)" || say "web: not answering ($WEB)"; }
}

down() {
  stop_proc web
  stop_proc worker
  stop_proc api
  rm -f "$RUN/mode"
  say "down (Postgres left running)"
}

case "${1:-}" in
  up) up replay ;;
  live) up live ;;
  reset) do_reset ;;
  status) status ;;
  down) down ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
