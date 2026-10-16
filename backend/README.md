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
