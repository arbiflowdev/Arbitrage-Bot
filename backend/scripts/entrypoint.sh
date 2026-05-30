#!/usr/bin/env bash
# Container entrypoint: wait for Postgres, run migrations, exec the command.
set -euo pipefail

wait_for_postgres() {
    if [[ -z "${DATABASE_URL:-}" ]]; then
        return 0
    fi
    # Extract host:port from the URL with a small Python helper so we don't
    # need extra binaries (pg_isready, netcat, ...) in the image.
    python - <<'PY'
import os, socket, sys, time
from urllib.parse import urlparse

url = urlparse(os.environ["DATABASE_URL"])
host = url.hostname or "postgres"
port = url.port or 5432
deadline = time.time() + 60

while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            sys.exit(0)
    except OSError:
        time.sleep(1)

print(f"Database {host}:{port} did not become reachable in time", file=sys.stderr)
sys.exit(1)
PY
}

echo "[entrypoint] Waiting for PostgreSQL..."
wait_for_postgres

if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
    echo "[entrypoint] Running alembic migrations..."
    alembic upgrade head
fi

echo "[entrypoint] Starting: $*"
exec "$@"
