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

All settings are read from `MAWA_*` environment variables or `.env`; `.env.example` lists every one. Outside `dev`, `MAWA_JWT_SECRET` must be at least 32 random characters and `MAWA_COOKIE_SECURE` must be `true`, or the app refuses to start. Outside `dev` the app also logs a startup warning when `MAWA_TRUST_PROXY=false` or `MAWA_STORAGE=local` (both are legitimate for a direct, single-host deployment, so neither is refused).

| Setting | Default | Meaning |
| --- | --- | --- |
| `MAWA_ENV` | `dev` | `dev` relaxes the secret, cookie and warning checks. |
| `MAWA_DATABASE_URL` | local Postgres | SQLAlchemy asyncpg URL. |
| `MAWA_REDIS_URL` | `redis://localhost:6379/0` | Cache, rate limits, view counters, worker queue. |
| `MAWA_JWT_SECRET` | dev placeholder | Signs access tokens; 32+ chars outside dev. |
| `MAWA_JWT_ACCESS_MINUTES` | `15` | Access-token lifetime. |
| `MAWA_SITE_URL` | `https://mawapress.com` | Canonical origin for SEO, sitemaps, RSS and CDN purge URLs. |
| `MAWA_REFRESH_DAYS` | `14` | Refresh-token cookie lifetime. |
| `MAWA_COOKIE_SECURE` | `true` | `Secure` flag on auth cookies; `false` only for plain-http local dev. |
| `MAWA_TRUST_PROXY` | `false` | Trust proxy headers for the client IP (see below). |
| `MAWA_CLIENT_IP_HEADER` | `CF-Connecting-IP` | Preferred client-IP header when `MAWA_TRUST_PROXY=true`. |
| `MAWA_RATE_LIMIT_WINDOW_SECONDS` | `60` | Fixed window for the per-IP limits: login 5 per IP+email and 20 per IP, search 30 per IP, view count 60 per IP. Failed logins are also capped at 20 per account (hashed email) per hour, whatever the IP; the 21st attempt gets 429 even with the right password. |
| `MAWA_STATS_SALT` | unset | Secret for the daily view-dedup salt; falls back to `MAWA_JWT_SECRET`. |
| `MAWA_STORAGE` | `local` | `local` (disk, served by the API at `/media`) or `s3` (R2/S3). |
| `MAWA_MEDIA_LOCAL_DIR` | `.media` | Directory for local storage. |
| `MAWA_MEDIA_BASE_URL` | empty | Public origin that serves media; required for `s3`. |
| `MAWA_S3_ENDPOINT`, `MAWA_S3_BUCKET`, `MAWA_S3_ACCESS_KEY`, `MAWA_S3_SECRET_KEY` | unset | Required when `MAWA_STORAGE=s3`. |
| `MAWA_REVALIDATE_URL`, `MAWA_REVALIDATE_SECRET` | unset | Next.js revalidation route and shared secret. |
| `MAWA_CF_ZONE_ID`, `MAWA_CF_API_TOKEN` | unset | Cloudflare cache purge. |

### Behind Cloudflare and Nginx

Rate limits and view de-duplication need the real client IP. With `MAWA_TRUST_PROXY=true` the client IP is, in order:

1. the header named by `MAWA_CLIENT_IP_HEADER` (default `CF-Connecting-IP`, which Cloudflare sets) if it is a valid IP;
2. the right-most valid `X-Forwarded-For` entry, which is the hop your own proxy appended (entries to its left are client-supplied and can be spoofed, so the first entry is never used);
3. the socket peer.

Only enable it when the API is reachable exclusively through your proxy; otherwise a client can send these headers itself. A typical Cloudflare, then Nginx, then uvicorn setup:

```nginx
# Trust Cloudflare's edge addresses (refresh from https://www.cloudflare.com/ips/) so $remote_addr is the visitor.
include /etc/nginx/cloudflare-ips.conf;   # lines of: set_real_ip_from <cidr>;
real_ip_header CF-Connecting-IP;
real_ip_recursive on;

location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;   # must reach the API
    proxy_set_header X-Forwarded-For $remote_addr;              # overwrite, never append client input
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Block direct access to the origin from anywhere but Cloudflare (firewall or Cloudflare Authenticated Origin Pulls). Without a proxy, leave `MAWA_TRUST_PROXY=false`.

## Background worker

One arq worker (backed by Redis) runs the background jobs. Start it next to the API:

```bash
python -m uv run arq app.worker.settings.WorkerSettings
```

| Job | Trigger | What it does |
| --- | --- | --- |
| `process_outbox` | cron, every 10 s | Claims `outbox` rows and calls the Next.js revalidation route and the Cloudflare purge (article, redirect, category and home pages, plus the listing pages, `sitemap.xml`, `news-sitemap.xml`, `rss.xml` and category RSS they affect; purge batches of 30). Failures retry with exponential backoff (20 s, 40 s, ... capped at 1 h) and are dead-lettered after 10 attempts. A Redis lock (`lock:outbox`, lease 120 s) makes a tick exit at once if the previous run is still going. |
| `publish_due_posts` | cron, every 30 s | Publishes scheduled posts whose time has come (published time = the scheduled time, or "now" if more than 5 minutes late). A failing post backs off 2^n minutes (max 60) and is left scheduled after 10 failures; the error is visible as `schedule_last_error` on the post. |
| `flush_views` | cron, every 60 s | Drains the Redis view counters into `posts.view_count`. |
| `make_variants` | enqueued on media upload | Generates the responsive image variants and the 1200x630 social image. |
| `refresh_seo_for(kind, id)` | enqueued after a category rename (`category`) or an author rename (`user`) | Re-runs the stored SEO of every affected post in batches of 100 and, for published posts, emits `post.updated` and drops their caches. |
| `purge_refresh_tokens` | cron, daily 03:17 | Deletes refresh tokens that expired or were revoked more than 7 days ago. |

Admins can inspect outbox events with `GET /api/admin/jobs?state=dead|pending`, requeue one with `POST /api/admin/jobs/{id}/retry`, or requeue every dead event with `POST /api/admin/jobs/retry-dead` (returns `{"requeued": n}`). An unset integration is skipped and the event is still marked processed.

## API overview

The OpenAPI schema is served at `/openapi.json` (interactive docs at `/docs`). `docs/api-contract.md` is the contract for the admin app and the public site. Endpoint groups:

- **Auth** (`/api/auth`): login, refresh (cookie + CSRF), logout, `me` (read and update profile or password). Users: `/api/users` (admin).
- **Posts** (`/api/posts`): CRUD with `If-Match`, submit, publish (also from scheduled), schedule, unschedule, send back, unpublish, unarchive, per-translation publish, revisions and restore. Categories and tags: `/api/categories`, `/api/tags`.
- **Media** (`/api/media`): upload (JPEG, PNG, WebP, GIF up to 10 MB), list, patch alt text and caption, delete.
- **Import** (`/api/import/docx`): `.docx` upload to a draft post.
- **Admin jobs** (`/api/admin/jobs`): outbox inspection and retry.
- **Public read API** (`/api/public`): posts, home, category feeds, category tree, search, redirect resolution, trending.
- **Sitemaps and RSS** (`/api/public`): `sitemap.xml`, `sitemaps/categories.xml`, `sitemaps/posts-YYYY-MM.xml`, `news-sitemap.xml`, `rss.xml?locale=`, `category/{slug}/rss.xml?locale=`.
- **Stats** (`/api/public/stats/view`, `/api/public/trending`): view counting and trending.
- Health: `GET /api/healthz`.
