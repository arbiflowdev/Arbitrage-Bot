#!/usr/bin/env bash
# =============================================================================
# Deploy / update the platform on the VPS.
#
# Pulls the latest code (if this is a git checkout), rebuilds the image, applies
# DB migrations automatically (the container entrypoint runs `alembic upgrade
# head`), and restarts with zero leftover images.
#
# Run from the deploy/ directory:
#   bash deploy.sh
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env"

if [ ! -f .env ]; then
  echo "ERROR: deploy/.env not found. Run: cp env.example .env  then edit it." >&2
  exit 1
fi

# Pull latest code when deployed from a git checkout.
if git -C .. rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "==> Pulling latest code"
  git -C .. pull --ff-only
fi

echo "==> Building image"
$COMPOSE build

echo "==> Starting / updating containers"
$COMPOSE up -d --remove-orphans

echo "==> Pruning dangling images"
docker image prune -f >/dev/null || true

echo "==> Current status"
$COMPOSE ps

echo
echo "Done. Tail logs with:  docker compose -f docker-compose.prod.yml logs -f app"
