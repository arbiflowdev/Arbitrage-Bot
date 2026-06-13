# Production image for the Digital Goods Arbitrage Platform.
#
# This builds the WHOLE product as one container: the FastAPI backend AND the
# dashboard SPA. Unlike backend/Dockerfile (which only sees the backend build
# context), this Dockerfile is built from the REPO ROOT so the repo-root
# `dashboard/` folder is included and served by the app.
#
#   docker build -t arbitrage .
#   docker run -p 8000:8000 --env-file backend/.env arbitrage
#
# On Render/Railway/Fly: set the Dockerfile path to `./Dockerfile` and the build
# context to the repo root.

# ---- builder stage ---------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build deps for psycopg2 / bcrypt; removed in the runtime stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --prefix=/install -r requirements.txt

# ---- runtime stage ---------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# libpq for asyncpg/psycopg2 at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

COPY --from=builder /install /usr/local

WORKDIR /app

# Backend application code (app/, alembic/, alembic.ini, scripts/, ...).
COPY backend/ /app/
# Dashboard SPA — placed next to the backend so _find_dashboard_dir() locates it
# at /app/dashboard inside the container.
COPY dashboard/ /app/dashboard/

RUN chmod +x /app/scripts/entrypoint.sh \
    && chown -R app:app /app
USER app

EXPOSE 8000

# entrypoint.sh waits for Postgres, runs `alembic upgrade head`, then execs CMD.
# Bind to $PORT when the platform provides one (Render/Railway), else 8000.
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
