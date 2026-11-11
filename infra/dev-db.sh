#!/usr/bin/env bash
# Local Postgres 16 for environments without Docker.
# Usage: infra/dev-db.sh start|stop|reset|status
# Creates role vera/vera and databases vera and vera_test on port 54329.
set -euo pipefail

D="${VERA_PGDATA:-/tmp/vera-pg}"
PORT="${VERA_PGPORT:-54329}"
B="${VERA_PGBIN:-/usr/lib/postgresql/16/bin}"
[ -x "$B/pg_ctl" ] || B="$(dirname "$(command -v pg_ctl)")"

# postgres refuses to run as root: switch to the postgres user when root.
if [ "$(id -u)" = "0" ]; then
  as_pg() { runuser -u postgres -- "$@"; }
else
  as_pg() { "$@"; }
fi

is_running() { as_pg "$B/pg_ctl" -D "$D/data" status >/dev/null 2>&1; }
psql_super() { PGPASSWORD=superpw "$B/psql" -h 127.0.0.1 -p "$PORT" -U postgres -d postgres -v ON_ERROR_STOP=1 "$@"; }

init() {
  [ -f "$D/data/PG_VERSION" ] && return 0
  mkdir -p "$D/run"
  printf 'superpw\n' > "$D/superpw"
  chmod 644 "$D/superpw"
  chmod 755 "$D"
  if [ "$(id -u)" = "0" ]; then
    install -d -o postgres -g postgres -m 700 "$D/data"
    chown postgres:postgres "$D/run"
  else
    install -d -m 700 "$D/data"
  fi
  as_pg "$B/initdb" -D "$D/data" -U postgres --pwfile="$D/superpw" \
    --auth-local=trust --auth-host=scram-sha-256 -E UTF8 >/dev/null
}

ensure_roles() {
  if [ -z "$(psql_super -tAc "select 1 from pg_roles where rolname='vera'")" ]; then
    psql_super -c "create role vera login password 'vera';" >/dev/null
  fi
  for db in vera vera_test; do
    if [ -z "$(psql_super -tAc "select 1 from pg_database where datname='$db'")" ]; then
      psql_super -c "create database $db owner vera;" >/dev/null
    fi
  done
}

start() {
  init
  if ! is_running; then
    as_pg "$B/pg_ctl" -D "$D/data" -l "$D/run/pg.log" -w -t 30 \
      -o "-p $PORT -k $D/run -c listen_addresses=127.0.0.1" start >/dev/null 2>&1 </dev/null
  fi
  ensure_roles
  echo "postgres running on 127.0.0.1:$PORT (databases: vera, vera_test)"
}

stop() {
  if is_running; then as_pg "$B/pg_ctl" -D "$D/data" -m fast -w stop >/dev/null; fi
  echo "postgres stopped"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  reset) stop; rm -rf "$D/data"; start ;;
  status) if is_running; then echo running; else echo stopped; exit 1; fi ;;
  *) echo "usage: $0 start|stop|reset|status" >&2; exit 2 ;;
esac
