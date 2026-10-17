# MAWAPRESS frontend

Next.js 15 (App Router, React 19, TypeScript strict, Tailwind v4, shadcn/ui). One app serves the
public site (`src/app/(public)`, built out in M4) and the newsroom admin (`src/app/admin`).

## Run

```bash
cd frontend
npm ci                       # installs the exact locked versions
cp .env.example .env.local   # optional
npm run dev                  # http://localhost:3000
```

The backend (`../backend`, `docker compose up -d`, `uvicorn app.main:app`) must be running for any
call to succeed.

## Environment

| Variable               | Default                         | Purpose                                                                                                                     |
| ---------------------- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `BACKEND_URL`          | `http://127.0.0.1:8000`         | Target of the `/api/*` and `/media/*` rewrites in `next.config.ts`.                                                         |
| `NEXT_PUBLIC_SITE_URL` | the origin the admin is open on | Public site origin (no trailing slash) for "Copy public link", media "Copy URL" and the SEO preview. Inlined at build time. |

Rewrite destinations are baked in at build time (`next build` writes them to the routes manifest), so
changing `BACKEND_URL` for a built app needs a rebuild. `npm run dev` picks it up on restart.

## API access

The browser only ever calls same-origin `/api/...`. `next.config.ts` rewrites `/api/:path*` (and
`/media/:path*`) to `${BACKEND_URL}`, so cookies (`mawa_refresh`, `mawa_csrf`) stay first-party and no
CORS is needed. Behind Nginx in production the proxy does the same job.

`src/lib/api/client.ts` is the typed fetch wrapper:

- JSON in and out; non-2xx responses throw `ApiError {status, code, message, details, retryAfter}`.
- Bearer token from an in-memory store (`setAccessToken`); never persisted.
- On 401 `INVALID_TOKEN` / `NOT_AUTHENTICATED` it refreshes once (`POST /api/auth/refresh`, cookie plus
  `X-CSRF-Token` from `mawa_csrf`), retries the request once, and shares one in-flight refresh between
  concurrent callers. `REFRESH_STALE` is retried after 300 ms. Any other refresh failure clears the
  session and dispatches a `window` `auth:expired` event (`onAuthExpired(handler)`).
- `ifMatch(updated_at)` gives the `If-Match` header for post state changes.
- `api.upload(path, formData, {onProgress})` does multipart uploads with progress (XMLHttpRequest).
- Pass `{auth: false}` for login.

## OpenAPI types

`npm run gen:api` exports the backend schema to `../contracts/openapi.json` (importing `app.main`
needs no server or database) and runs `openapi-typescript` into `src/lib/api/schema.d.ts`. It needs
the backend's `uv` environment (`python -m uv sync` in `../backend`); on Windows the script defaults
`UV_PYTHON_INSTALL_DIR` to `~/uv-python`. Use `SKIP_EXPORT=1 npm run gen:api` to regenerate types
from the committed JSON only. Commit both files whenever the backend API changes.

## Scripts

`npm run lint` (ESLint plus Prettier check), `npm run typecheck`, `npm test` (Vitest, jsdom, MSW),
`npm run build`, `npm run format`.

## UI

shadcn/ui components live in `src/components/ui`. Fonts: Mukta (Devanagari and Latin) and Inter via
`next/font/google`. Brand tokens (`--brand-red` #C8102E, `--brand-blue` #003893, `--ink` #111827) are
in `src/app/globals.css` with light and dark themes (`next-themes`, class strategy).
