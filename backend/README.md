# MAWAPRESS backend

FastAPI backend for MAWAPRESS: auth, posts with Nepali/English translations, SEO metadata, and a cached public read API. PostgreSQL stores content, Redis caches public posts.

## Prerequisites

- Docker (Docker Desktop on Windows). Tests start throwaway Postgres containers via testcontainers.
- [uv](https://docs.astral.sh/uv/), run as `python -m uv`.
- On this Windows machine, uv needs its Python install directory set. In Git Bash:

  ```bash
  export UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python'
  ```

## Setup

```bash
cd backend
python -m uv sync
cp .env.example .env   # optional, edit as needed
```

## Services

From the repo root, `docker compose up -d` starts Postgres and Redis.

The compose Postgres binds host port 5432 (Redis binds 6379). If another local Postgres container or service already uses that port, stop it or remap the port in `docker-compose.yml` (and update `MAWA_DATABASE_URL`).

## Migrate

```bash
python -m uv run alembic upgrade head
```

## Run the dev server

```bash
python -m uv run uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/api/healthz`.

## Tests

```bash
python -m uv run pytest
```

Docker must be running. The suite includes migration upgrade, downgrade and model-drift checks (`alembic check`).

## Configuration

All settings are read from `MAWA_*` environment variables or `.env`; see `.env.example`. Outside `dev`, `MAWA_JWT_SECRET` must be at least 32 random characters or the app refuses to start.

Session and rate-limit settings:

- `MAWA_REFRESH_DAYS` (default `14`): lifetime of the refresh-token cookie.
- `MAWA_COOKIE_SECURE` (default `true`): sets the `Secure` flag on auth cookies. Set it to `false` for plain-http local development; the shipped `.env.example` does this. The app refuses to start with `false` when `MAWA_ENV` is not `dev`.
- `MAWA_TRUST_PROXY` (default `false`): use the first `X-Forwarded-For` entry as the client IP for rate limiting. Enable only behind a proxy that overwrites the header with the real client address rather than appending to it; only the first entry is used, and it is ignored (falling back to the socket peer) unless it is a valid IP address.
- `MAWA_RATE_LIMIT_WINDOW_SECONDS` (default `60`): window for the login (5 per IP+email, 20 per IP) and public search (30 per IP) limits.

## Background worker

The outbox worker (arq, backed by Redis) drains the `outbox` table every 10 seconds: it calls the Next.js revalidation route and purges the Cloudflare cache for published, updated and unpublished articles. Failed events retry with exponential backoff (20 s, 40 s, 80 s, ...) and are dead-lettered after 5 attempts. A daily job also deletes refresh tokens that expired or were revoked more than 7 days ago.

```bash
python -m uv run arq app.worker.settings.WorkerSettings
```

Settings (all optional; an unset integration is skipped and the event is still marked processed): `MAWA_REVALIDATE_URL`, `MAWA_REVALIDATE_SECRET`, `MAWA_CF_ZONE_ID`, `MAWA_CF_API_TOKEN`. Admins can inspect failed events with `GET /api/admin/jobs?state=dead|pending` and requeue one with `POST /api/admin/jobs/{id}/retry`.
