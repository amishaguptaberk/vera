#!/usr/bin/env bash
# Vera container entrypoint. Usage: entrypoint.sh api | worker | migrate | <any command>
set -euo pipefail

cd /app

wait_for_db() {
  python - <<'PY'
import os, sys, time
import psycopg

url = os.environ.get("VERA_DATABASE_URL", "")
url = url.replace("postgresql+psycopg://", "postgresql://", 1)
deadline = time.time() + int(os.environ.get("VERA_DB_WAIT_SECONDS", "60"))
while True:
    try:
        psycopg.connect(url, connect_timeout=3).close()
        break
    except Exception as exc:  # noqa: BLE001
        if time.time() > deadline:
            print(f"database not reachable: {type(exc).__name__}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY
}

mode="${1:-api}"
case "$mode" in
  api)
    wait_for_db
    alembic upgrade head
    exec uvicorn vera_api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  worker)
    wait_for_db
    exec python -m vera_api.worker
    ;;
  migrate)
    wait_for_db
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
