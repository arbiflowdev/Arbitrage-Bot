# VPS Deployment — Digital Goods Arbitrage Platform

Deploys the whole platform to a single cheap VPS (Hetzner CX22 recommended) with
a **free static IP**, replacing Render. Postgres stays on **Neon** (no data
migration). Redis is self-hosted on the box. HTTPS is automatic via Caddy.

```
                         ┌─────────────────────── VPS (one box) ───────────────────────┐
   Internet  ──443──▶    │  caddy (auto-HTTPS)  ──▶  app (API + dashboard + 3 workers)  │
                         │                                    │                          │
   Outbound ◀────────────  static public IP  ◀────────────────┘   redis (locks/queues)  │
   to Kinguin/G2G/Eneba  └──────────────────────────────────────────────────────────────┘
                                                              │
                                                              ▼  external
                                                        Neon Postgres
```

The VPS's **own public IPv4 is the static outbound IP** — whitelist it on each
marketplace. No proxy needed.

---

## What's in this folder

| File | Purpose |
|------|---------|
| `server-setup.sh` | One-time bootstrap of a fresh Ubuntu 24.04 box (Docker, swap, firewall, fail2ban). |
| `docker-compose.prod.yml` | The 3-container production stack (app + redis + caddy). |
| `Caddyfile` | Reverse proxy + automatic HTTPS. |
| `env.example` | Template for `deploy/.env` (secrets live only there; gitignored). |
| `deploy.sh` | Build + migrate + (re)start. Run for every deploy/update. |

---

## First-time deployment

### 1. Create the server (client)
Hetzner Cloud **CX22** (2 vCPU / 4 GB / 40 GB) — or DigitalOcean 2 GB droplet —
running **Ubuntu 24.04 LTS**, EU region. During creation, **add the developer's
SSH public key** so access is granted without sharing a password.

### 2. Bootstrap the box (one time)
SSH in as root, then:
```bash
git clone <YOUR_GITHUB_REPO_URL> arbitrage
cd arbitrage/deploy
bash server-setup.sh
```
The script prints the server's **public IPv4** at the end — note it for step 5.

### 3. Configure secrets
```bash
cp env.example .env
nano .env          # set DOMAIN, DATABASE_URL (Neon), JWT_SECRET, admin login, API keys
```
Generate a strong JWT secret with `openssl rand -hex 32`.
Leave `OUTBOUND_PROXY_URL` / `QUOTAGUARDSTATIC_URL` blank.

### 4. Point DNS (recommended)
Create an **A record** for your domain (e.g. `app.yourdomain.com`) pointing at the
server's IPv4, and set the same value as `DOMAIN` in `.env`. Caddy fetches the TLS
cert automatically on first request.
*No domain yet?* Set `DOMAIN=:80` in `.env` to run http-only on the IP for now,
and add a domain later (just change `DOMAIN` and re-run `deploy.sh`).

### 5. Deploy
```bash
bash deploy.sh
```
This builds the image, runs DB migrations automatically, and starts everything.
Open `https://app.yourdomain.com` and log in with the bootstrap admin.

### 6. Whitelist the static IP
Give the server's public IPv4 to each marketplace (Kinguin ESA, Eneba, Rokky) for
their API IP allowlist. That same single IP covers all of them.

---

## Day-to-day operations

```bash
cd arbitrage/deploy

# Deploy latest code
bash deploy.sh

# Live logs
docker compose -f docker-compose.prod.yml logs -f app

# Status / health
docker compose -f docker-compose.prod.yml ps

# Restart just the app
docker compose -f docker-compose.prod.yml restart app

# Stop everything
docker compose -f docker-compose.prod.yml down
```

Change a setting or API key → edit `.env`, then `bash deploy.sh`.

---

## Notes & safety

- **Database:** stays on Neon. Migrations run automatically on every deploy via
  the container entrypoint (`alembic upgrade head`). Nothing to run by hand.
- **Redis:** self-hosted here (appendonly, noeviction) — durable across restarts.
- **Backups:** Neon handles Postgres backups. Redis only holds locks/flags, so it
  is safe to lose.
- **Firewall:** only 22/80/443 are open. The app port (8000) is internal-only.
- **Secrets:** only ever in `deploy/.env` (gitignored). Never commit it.
- **Rollback:** `git -C .. checkout <previous-commit>` then `bash deploy.sh`.
