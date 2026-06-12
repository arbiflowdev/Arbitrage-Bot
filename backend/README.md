# Digital Goods Arbitrage Platform — Backend (Milestones 1–2)

Production-oriented FastAPI backend for the Digital Goods Arbitrage Platform.

**Milestone 1** delivered the foundation: configuration, structured logging,
async PostgreSQL + Redis, JWT authentication with admin RBAC, and a
clean-architecture project layout.

**Milestone 2** adds **marketplace API integrations**: a provider adapter
architecture with a unified abstraction layer (Kinguin + G2G), product/price
fetch, listing synchronisation, order retrieval, signature-verified webhook
handling, and retry + rate-limit handling. API keys are supplied via **`.env`**,
and adapters run in a credential-free **mock mode** by default, so the platform
is fully usable before real API keys are added.

**Milestone 5** completes the MVP: the **arbitrage/repricing engine** (M3),
**hybrid inventory & JIT fulfillment** (M4), an **alerts** subsystem, a global
kill-switch, and the **admin dashboard** — a no-build static SPA served by this
same FastAPI process.

---

## Dashboard

The platform is a **single deployable**: one FastAPI process serves both the API
and the admin dashboard.

- **Dashboard (SPA):** served at `/` (any non-API path falls back to the SPA's
  `index.html` for client-side routing).
- **JSON API:** served under `/api/v1` (e.g. `/api/v1/health`, `/api/v1/alerts`).
- **API docs:** `/docs` (Swagger) and `/redoc`.

The dashboard is a no-build static SPA (vanilla HTML + Tailwind + Alpine.js +
Chart.js, all vendored locally — no runtime CDN) living in `app/static/`. There
is no separate frontend build or deployment.

**Run locally:**

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# Dashboard: http://localhost:8000/   ·   API: http://localhost:8000/api/v1
```

Pages: Overview KPIs, Orders (filter/retry), Inventory (upload TXT/CSV,
invalidate keys), Pricing (scan/preview/kill-switch/history), Wallets
(fund/monitor), Logs, Alerts (acknowledge/resolve), and Connections with the
global "Stop everything" kill-switch.

See **`docs/DEPLOYMENT.md`** for the cloud-agnostic deployment guide and
**`docs/OPERATOR_GUIDE.md`** for a page-by-page operator walkthrough.

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
│   │       ├── endpoints/      # auth, health, settings, marketplaces, webhooks
│   │       └── router.py       # /api/v1 aggregator
│   ├── core/                   # config, logging, db, redis, security, DI
│   ├── integrations/           # marketplace adapters + unified abstraction
│   │                           #   (base, http, registry, kinguin, g2g, mock)
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

Marketplace integrations (Milestone 2):

| Variable                       | Effect                                                       |
| ------------------------------ | ----------------------------------------------------------- |
| `MARKETPLACE_MODE`             | `mock` (default, no keys needed) or `live` (real APIs).     |
| `KINGUIN_API_KEY`              | Kinguin API key (paste to go live; blank = mock).           |
| `KINGUIN_API_SECRET`          | Kinguin webhook/HMAC signing secret.                        |
| `G2G_API_KEY`                 | G2G API key (paste to go live; blank = mock).               |
| `G2G_API_SECRET`              | G2G request + webhook signing secret.                       |
| `KINGUIN_API_BASE_URL`         | Kinguin ESA API base URL.                                   |
| `G2G_API_BASE_URL`             | G2G API base URL.                                           |
| `KINGUIN_RATE_LIMIT_PER_MINUTE`| Proactive client-side rate limit for Kinguin.               |
| `G2G_RATE_LIMIT_PER_MINUTE`    | Proactive client-side rate limit for G2G.                   |
| `HTTP_TIMEOUT_SECONDS`         | Per-request timeout for marketplace calls.                  |
| `HTTP_MAX_RETRIES`             | Retry attempts on 429/5xx/network errors.                   |
| `HTTP_RETRY_BACKOFF_SECONDS`   | Base for exponential backoff between retries.               |

Optional convenience:

| Variable                  | Effect                                                  |
| ------------------------- | ------------------------------------------------------- |
| `BOOTSTRAP_ADMIN_EMAIL`   | Together with `_PASSWORD`, ensures an admin at startup. |
| `BOOTSTRAP_ADMIN_PASSWORD`| Plaintext password used only for the bootstrap admin.   |
| `LOG_JSON`                | `true` for JSON logs, `false` for dev-friendly output.  |
| `CORS_ORIGINS`            | Comma-separated origins or `*`.                         |

---

## 6. Database schema

Revision `0001_initial` (Milestone 1):

| Table             | Purpose                                                          |
| ----------------- | ---------------------------------------------------------------- |
| `users`           | Application users (admin / user roles).                          |
| `api_credentials` | Created in M1; **dropped in M2** — API keys now live in `.env`.   |
| `products`        | Canonical product catalogue keyed by internal SKU.               |
| `sku_mappings`    | Per-marketplace SKU mapped to internal products.                 |
| `logs`            | Persistent structured log/event records for the admin dashboard. |

Revision `0002_marketplace_integrations` (Milestone 2):

| Table                | Purpose                                                         |
| -------------------- | -------------------------------------------------------------- |
| `marketplace_prices` | Latest fetched price per `(provider, marketplace_sku)`.        |
| `listings`           | Our listings on each marketplace + sync status.                |
| `webhook_events`     | Inbound provider webhooks (idempotent, audit trail).           |

It also **drops `api_credentials`** — marketplace API keys now live in `.env`
only. All tables include `id`, `created_at`, and `updated_at`.

Manage migrations from inside the backend container:

```bash
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade -1
# Create a new revision after editing models:
docker compose exec backend alembic revision --autogenerate -m "describe change"
```

---

## 7. API surface

All endpoints are versioned under `${API_V1_PREFIX}/v1`, i.e. `/api/v1/...`.

### Milestone 1

| Method | Path                  | Auth          | Purpose                                  |
| ------ | --------------------- | ------------- | ---------------------------------------- |
| GET    | `/api/v1/health`      | public        | Liveness + database + redis checks       |
| POST   | `/api/v1/auth/register` | public      | Create a new user, returns JWT          |
| POST   | `/api/v1/auth/login`  | public        | Email + password → JWT                   |
| GET    | `/api/v1/auth/me`     | bearer        | Current authenticated user               |
| GET    | `/api/v1/settings`    | admin         | Non-sensitive runtime config             |

### Milestone 2 — marketplace integrations

| Method | Path                                          | Auth     | Purpose                                  |
| ------ | --------------------------------------------- | -------- | ---------------------------------------- |
| GET    | `/api/v1/marketplaces`                        | admin    | List providers + mode + credential state |
| POST   | `/api/v1/marketplaces/{provider}/sync/prices` | admin    | Fetch + store marketplace prices         |
| POST   | `/api/v1/marketplaces/{provider}/sync/listings`| admin   | Fetch + store our listings               |
| GET    | `/api/v1/marketplaces/{provider}/orders`      | admin    | Fetch recent orders (live read)          |
| GET    | `/api/v1/marketplace-prices`                  | admin    | List stored prices                       |
| GET    | `/api/v1/listings`                            | admin    | List stored listings                     |
| POST   | `/api/v1/webhooks/{provider}`                 | signature| Receive a marketplace webhook            |
| GET    | `/api/v1/webhook-events`                      | admin    | List received webhook events             |

`{provider}` is one of `kinguin`, `g2g`.

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

## 8. Marketplace integrations (Milestone 2)

### Mock vs live mode

`MARKETPLACE_MODE=mock` (the default) makes every adapter return deterministic
data with **no API keys required** — ideal for development, demos, and tests.
Set `MARKETPLACE_MODE=live` to route adapters at the real Kinguin/G2G REST APIs;
in live mode an adapter stays **dormant** (raises a clear "credentials not
configured" error) until an active credential exists for that provider.

> The real endpoint paths/field names follow each provider's documented API and
> should be re-verified against current docs once live API access is granted.

### Providing live API keys

Credentials live in **`.env` only** — there is no database credential store.
Paste the keys into the placeholders and flip the mode to live:

```dotenv
MARKETPLACE_MODE=live
KINGUIN_API_KEY=your-kinguin-key
KINGUIN_API_SECRET=your-kinguin-webhook-secret
G2G_API_KEY=your-g2g-key
G2G_API_SECRET=your-g2g-signing-secret
```

Restart the app and the adapters go live immediately. Leave a provider's keys
blank to keep it dormant (live mode) or to return mock data (mock mode).
`*_API_SECRET` is the provider's webhook/HMAC signing secret. Since `.env` is
gitignored, keys never reach version control.

### Syncing data

```bash
# Fetch + store current prices (works immediately in mock mode):
curl -X POST http://localhost:8000/api/v1/marketplaces/kinguin/sync/prices \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Read what was stored:
curl "http://localhost:8000/api/v1/marketplace-prices?provider=kinguin" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Webhooks

`POST /api/v1/webhooks/{provider}` is public and verified by the provider's
signature (not JWT). Events are de-duplicated by `(provider, external_id)` and
recorded in `webhook_events`; invalid signatures are stored and rejected with
`400`. Resilience is built into the shared HTTP client: exponential-backoff
retries on `429`/`5xx`/network errors (honouring `Retry-After`) plus proactive
Redis-backed per-provider rate limiting.

### Adding a new marketplace (e.g. Eneba)

1. Implement `MarketplaceAdapter` in `app/integrations/<provider>.py`.
2. Register it in `app/integrations/registry.py` (`_ADAPTERS` + `_http_for`).
3. Add its base URL / rate-limit settings to `app/core/config.py`.

---

## 9. Logging

* Structured logs via `structlog`, bridged through stdlib logging.
* JSON output when `LOG_JSON=true`; readable console output otherwise.
* Every request gets an `X-Request-ID` header, propagated into every log
  line for that request via context vars.
* Levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

---

## 10. Tests

```bash
# Inside the container:
docker compose exec backend pytest -q

# Or locally (with deps installed and DATABASE_URL/REDIS_URL pointing at
# a disposable test database):
pytest -q
```

The suite uses FastAPI's ASGI transport and `respx` for mocking outbound HTTP.
It covers the `/health` endpoint, the register → login → me happy path, the
`.env` credential resolution, the HTTP client's retry/error handling, the mock
and real (transport-mocked) adapters, and the marketplace sync + webhook APIs
end-to-end in mock mode.

---

