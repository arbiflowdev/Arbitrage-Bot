# Arbitrage-Bot

Digital Goods Arbitrage Platform — an automated repricing + fulfillment engine
for digital-key marketplaces (Kinguin, G2G), with an admin dashboard.

The application is a **single deployable**: one FastAPI process serves both the
API and the dashboard.

## Dashboard

- **Dashboard (SPA):** served at `/`
- **JSON API:** served under `/api/v1` (e.g. `/api/v1/health`)
- **API docs:** `/docs` (Swagger) and `/redoc`

The dashboard is a no-build static SPA served by the backend — there is nothing
to build or host separately.

## Run locally (step by step)

### Prerequisites

- **Python 3.11+**
- A **PostgreSQL** database (a free [Neon](https://neon.tech) project works well)
- **Redis** (optional locally — the app fails-fast and runs without it; required
  for the background pricing/fulfillment workers and the kill-switches)

### Windows (PowerShell)

```powershell
# 1. Clone and enter the project
git clone <repo-url>
cd "Arbitrage bot"

# 2. Create and activate a virtual environment (from the project root)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install backend dependencies
pip install -r backend\requirements.txt

# 4. Create your environment file and fill it in
copy backend\.env.example backend\.env
#    Then edit backend\.env and set at least:
#      DATABASE_URL              -> your Postgres/Neon connection string
#      BOOTSTRAP_ADMIN_EMAIL     -> the admin login email (default: admin@example.com)
#      BOOTSTRAP_ADMIN_PASSWORD  -> the admin login password (default: ArbAdmin!2026)
#    (REDIS_URL is optional locally.)

# 5. Apply database migrations
cd backend
alembic upgrade head

# 6. Start the app (serves API + dashboard on one port)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### macOS / Linux (bash)

```bash
git clone <repo-url>
cd "Arbitrage bot"

python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cp backend/.env.example backend/.env
# edit backend/.env — set DATABASE_URL + BOOTSTRAP_ADMIN_EMAIL/PASSWORD

cd backend
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Open it

| What | URL |
|------|-----|
| **Dashboard** | http://127.0.0.1:8000/ |
| API root | http://127.0.0.1:8000/api |
| API docs (Swagger) | http://127.0.0.1:8000/docs |

Sign in with the `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` you set in
`backend/.env`. A matching admin account is created automatically on startup, so
to change the login the client just edits those two values and restarts the app.

> Use a real, non-reserved email domain (e.g. `@example.com`) — reserved domains
> like `.local` are rejected by email validation.

### Run the tests (optional)

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q        # 109 tests
..\.venv\Scripts\python.exe -m ruff check app tests
```

The backend lives in [`backend/`](backend/); see [`backend/README.md`](backend/README.md)
for full setup, the API surface, and the database schema.

## Documentation

- **[`docs/MILESTONE_5_DELIVERY.md`](docs/MILESTONE_5_DELIVERY.md)** — final
  delivery & handover note (what shipped, the dashboard, the API, verification).
- **[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)** — cloud-agnostic deployment guide
  (Neon/Postgres, Redis, env vars, migrations, Docker, provider notes, first admin).
- **[`docs/OPERATOR_GUIDE.md`](docs/OPERATOR_GUIDE.md)** — page-by-page dashboard
  walkthrough for operators.
