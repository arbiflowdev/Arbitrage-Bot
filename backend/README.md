# Digital Goods Arbitrage Platform — Backend (Milestone 1)

Production-oriented FastAPI backend implementing the foundation for the
Digital Goods Arbitrage Platform: configuration, structured logging,
async PostgreSQL + Redis, JWT authentication with admin RBAC, and a
clean-architecture project layout ready for the marketplace integration,
arbitrage engine, and order fulfilment work in later milestones.

> Scope: **Milestone 1 only**. Marketplace integrations, the arbitrage
> engine, dashboard/frontend, and deployment hardening are explicitly
> out of scope for this milestone.

---

## 1. Tech stack

| Concern        | Choice                                                      |
| -------------- | ----------------------------------------------------------- |
| Runtime        | Python **3.12+**                                            |
| Web framework  | **FastAPI** + Uvicorn (async)                               |
| ORM            | **SQLAlchemy 2.x** (async, asyncpg driver)                  |
| Database       | **PostgreSQL 16**                                           |
| Migrations     | **Alembic** (async env)                                     |
| Cache / Locks  | **Redis 7** (async client, distributed-lock primitives)     |
| Auth           | **JWT** (HS256) + bcrypt (passlib)                          |
| Validation     | Pydantic v2 + pydantic-settings                             |
| Logging        | `structlog` (JSON in prod, console in dev)                  |
| Container      | Docker + docker-compose (backend, postgres, redis)          |
| Tests          | pytest + httpx ASGITransport                                |

---

## 2. Project layout

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/      # FastAPI routers (auth, health, settings)
│   │       └── router.py       # /api/v1 aggregator
│   ├── core/                   # config, logging, db, redis, security, DI
│   ├── middlewares/            # request-id, access log
│   ├── models/                 # SQLAlchemy ORM models
│   ├── repositories/           # Data-access layer (one per aggregate)
│   ├── schemas/                # Pydantic request/response models
│   ├── services/               # Business-logic layer
│   ├── utils/                  # Small reusable helpers
│   └── main.py                 # FastAPI app factory + lifespan
├── alembic/                    # Migrations (async env)
├── scripts/entrypoint.sh       # Docker entrypoint: wait-for-db + migrate
├── tests/                      # pytest suite
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
├── pyproject.toml
└── .env.example
```

The layout follows a **clean-architecture** discipline:

* `api/` only deals with HTTP concerns and dependency injection.
* `services/` hold use-case logic and are framework-agnostic.
* `repositories/` are the only modules that talk to the database.
* `core/` contains cross-cutting infrastructure (config, security, logging).

---

## 3. Running with Docker (recommended)

```bash
cd backend
cp .env.example .env
# Edit .env — at minimum, set a strong JWT_SECRET.
docker compose up --build
```

On first startup the `backend` container will:

1. Wait for PostgreSQL to accept connections.
2. Apply Alembic migrations (`alembic upgrade head`).
3. Launch Uvicorn on port `8000`.

When it is up:

* Swagger UI:  http://localhost:8000/docs
* ReDoc:       http://localhost:8000/redoc
* OpenAPI:     http://localhost:8000/openapi.json
* Health:      http://localhost:8000/api/v1/health

Tail logs:

```bash
docker compose logs -f backend
```

Stop & remove containers:

```bash
docker compose down            # keep volumes
docker compose down -v         # also drop postgres/redis volumes
```

---

## 4. Running locally (without Docker)

You'll need PostgreSQL 16 and Redis 7 reachable from your machine.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit DATABASE_URL / REDIS_URL

alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## 5. Environment variables

See **`.env.example`** for the authoritative list. Required values:

| Variable                       | Purpose                                                  |
| ------------------------------ | -------------------------------------------------------- |
| `DATABASE_URL`                 | `postgresql+asyncpg://user:pass@host:5432/dbname`        |
| `REDIS_URL`                    | `redis://host:6379/0`                                    |
| `JWT_SECRET`                   | ≥16 char random secret (use ≥32 in production)           |
| `JWT_ALGORITHM`                | Default `HS256`                                          |
| `ACCESS_TOKEN_EXPIRE_MINUTES`  | Access-token TTL in minutes                              |

Optional convenience:

| Variable                  | Effect                                                  |
| ------------------------- | ------------------------------------------------------- |
| `BOOTSTRAP_ADMIN_EMAIL`   | Together with `_PASSWORD`, ensures an admin at startup. |
| `BOOTSTRAP_ADMIN_PASSWORD`| Plaintext password used only for the bootstrap admin.   |
| `LOG_JSON`                | `true` for JSON logs, `false` for dev-friendly output.  |
| `CORS_ORIGINS`            | Comma-separated origins or `*`.                         |

---

## 6. Database schema (Milestone 1)

The initial Alembic revision `0001_initial` creates:

| Table             | Purpose                                                          |
| ----------------- | ---------------------------------------------------------------- |
| `users`           | Application users (admin / user roles).                          |
| `api_credentials` | Marketplace API keys/secrets (Eneba, Kinguin, G2G, …).           |
| `products`        | Canonical product catalogue keyed by internal SKU.               |
| `sku_mappings`    | Per-marketplace SKU mapped to internal products.                 |
| `logs`            | Persistent structured log/event records for the admin dashboard. |

All tables include `id`, `created_at`, and `updated_at`.

Manage migrations from inside the backend container:

```bash
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
# Create a new revision after editing models:
docker compose exec backend alembic revision --autogenerate -m "describe change"
```

---

## 7. API surface (Milestone 1)

All endpoints are versioned under `${API_V1_PREFIX}/v1`, i.e. `/api/v1/...`.

| Method | Path                  | Auth          | Purpose                                  |
| ------ | --------------------- | ------------- | ---------------------------------------- |
| GET    | `/api/v1/health`      | public        | Liveness + database + redis checks       |
| POST   | `/api/v1/auth/register` | public      | Create a new user, returns JWT          |
| POST   | `/api/v1/auth/login`  | public        | Email + password → JWT                   |
| GET    | `/api/v1/auth/me`     | bearer        | Current authenticated user               |
| GET    | `/api/v1/settings`    | admin         | Non-sensitive runtime config             |

### Examples

Register:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"correct horse battery","full_name":"Jane Doe"}'
```

Login:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"correct horse battery"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

Authenticated request:

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

Admin-only settings (requires a user with role `admin`):

```bash
curl http://localhost:8000/api/v1/settings \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Promoting a user to admin

The simplest path during Milestone 1 is the bootstrap admin env vars
(`BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD`). Alternatively,
promote an existing user via SQL:

```bash
docker compose exec postgres \
  psql -U arbitrage -d arbitrage \
  -c "UPDATE users SET role='admin' WHERE email='user@example.com';"
```

---

## 8. Logging

* Structured logs via `structlog`, bridged through stdlib logging.
* JSON output when `LOG_JSON=true`; readable console output otherwise.
* Every request gets an `X-Request-ID` header, propagated into every log
  line for that request via context vars.
* Levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

---

## 9. Tests

```bash
# Inside the container:
docker compose exec backend pytest -q

# Or locally (with deps installed and DATABASE_URL/REDIS_URL pointing at
# a disposable test database):
pytest -q
```

The included smoke tests use FastAPI's ASGI transport and exercise the
`/health` endpoint plus the register → login → me happy path.

---

