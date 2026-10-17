# MAWAPRESS API contract

For the M3 admin app and the M4 public site. The machine-readable schema is `/openapi.json` (docs at `/docs`); this file covers what the schema cannot say: flows, headers, limits and side effects. All JSON; locales are `ne` and `en`.

## Errors

Every error uses one envelope:

```json
{"error": {"code": "VERSION_CONFLICT", "message": "Post was changed by someone else", "details": {"current_updated_at": "..."}}}
```

Branch on `code`, never on `message`. Codes by status:

- 401: `NOT_AUTHENTICATED`, `INVALID_TOKEN` (expired, revoked, or user deactivated), `INVALID_CREDENTIALS`, `INVALID_REFRESH_TOKEN`, `REFRESH_STALE`, `REFRESH_REUSED`.
- 403: `FORBIDDEN_ROLE`, `CSRF_FAILED`, `INVALID_CURRENT_PASSWORD`.
- 404: `NOT_FOUND`, `POST_NOT_FOUND`, `TRANSLATION_NOT_FOUND`, `REVISION_NOT_FOUND`, `CATEGORY_NOT_FOUND`, `TAG_NOT_FOUND`, `MEDIA_NOT_FOUND`, `USER_NOT_FOUND`, `JOB_NOT_FOUND`, `LOCALE_NOT_FOUND`, `REDIRECT_NOT_FOUND`, `SITEMAP_NOT_FOUND`.
- 409: `INVALID_TRANSITION`, `NO_PUBLISHED_TRANSLATION`, `SLUG_TAKEN`, `CATEGORY_CYCLE`, `CATEGORY_TOO_DEEP`, `CATEGORY_IN_USE`, `MEDIA_IN_USE`, `EMAIL_TAKEN`, `LAST_ADMIN`, `CANNOT_MODIFY_SELF`, `JOB_ALREADY_PROCESSED`, `CONFLICT`.
- 412 `VERSION_CONFLICT`; 428 `PRECONDITION_REQUIRED` (see If-Match).
- 413: `FILE_TOO_LARGE`, `IMAGE_TOO_LARGE`, `DOCX_TOO_LARGE`; 415: `UNSUPPORTED_MEDIA`, `NOT_A_DOCX`.
- 422: `VALIDATION_ERROR` (details.errors lists fields), plus `INVALID_SLUG`, `SLUG_NOT_EDITABLE`, `INVALID_SCHEDULE_TIME`, `TRANSLATION_INCOMPLETE`, `CATEGORY_NOT_FOUND`, `TAG_NOT_FOUND`, `MEDIA_NOT_FOUND`, `NEW_PASSWORD_REQUIRED`, `PASSWORD_UNCHANGED`, `QUERY_TOO_SHORT`, `INVALID_PATH`, `DOCX_UNREADABLE`, `IMPORT_TIMEOUT`. Revision ids outside 1..2^63-1 are `VALIDATION_ERROR`.
- 429 `RATE_LIMITED` with a `Retry-After` header (seconds). 503 `IMPORT_BUSY` (retry shortly). 500 `INTERNAL_ERROR`.

## Auth flow (admin app)

1. `POST /api/auth/login` with `{email, password}`. Response `{access_token, token_type: "bearer"}`. It also sets two cookies: `mawa_refresh` (httpOnly, path `/api/auth`) and `mawa_csrf` (readable by JS, path `/`). Keep the access token in memory only. Send it as `Authorization: Bearer <token>` on every authenticated call. It lives `MAWA_JWT_ACCESS_MINUTES` (15 by default).
2. When a call returns 401 `INVALID_TOKEN` (or before expiry), call `POST /api/auth/refresh` with credentials included and the header `X-CSRF-Token: <value of the mawa_csrf cookie>`. Response is a new `{access_token}`, and the refresh and CSRF cookies are rotated. Retry the original request once with the new token.
3. Refresh errors:
   - `REFRESH_STALE`: another tab rotated the cookie a moment ago. Re-read the cookies and call `/refresh` once more (the browser now holds the new cookie). It is not an error state.
   - `REFRESH_REUSED`: the token was replayed, so the whole session family was revoked. Go to the login screen.
   - `INVALID_REFRESH_TOKEN`, `INVALID_TOKEN`, `NOT_AUTHENTICATED`, `CSRF_FAILED` after a retry: go to login.
4. `POST /api/auth/logout` (same CSRF header) revokes the refresh token and clears both cookies. Returns 204.
5. `GET /api/auth/me` returns `{id, email, name, role, bio}`. `PATCH /api/auth/me` accepts `name`, `bio`, and `current_password` + `new_password` together.
6. A **self password change** revokes every session of the user, then starts a fresh one for the caller: the response is the profile plus `access_token`, and new `mawa_refresh` and `mawa_csrf` cookies are set. Replace the in-memory token with `access_token`; do not log the user out. Other devices must log in again. Admin password resets (`POST /api/users/{id}/password`) revoke everything with no replacement session.
7. Login is rate limited: 5 attempts per IP and email per window, 20 per IP, and 20 failed attempts per email per hour (429 `RATE_LIMITED`, honour `Retry-After`).

Roles: `reporter` < `editor` < `admin`. Reporters see and edit only their own drafts; editors publish, schedule and manage categories and tags; admins manage users and jobs.

## If-Match (optimistic concurrency)

Every post state change except create requires `If-Match: <updated_at>`, where the value is the `updated_at` of the **last post response you hold** (PATCH, publish, schedule, unschedule, unpublish, unarchive, send-back, translation publish, restore). Use the ISO string exactly as returned. Missing header: 428 `PRECONDITION_REQUIRED`. Stale value: 412 `VERSION_CONFLICT` with `details.current_updated_at`; reload the post and let the user re-apply. Always replace your stored `updated_at` with the one in each response.

Post statuses: `draft`, `in_review`, `scheduled`, `published`, `archived`. Publish accepts `draft`, `in_review` and `scheduled` ("publish now" clears the schedule). A scheduled post the worker cannot publish stays `scheduled`; `schedule_attempts` and `schedule_last_error` on the post show why (after 10 failures the worker gives up until an editor reschedules).

## Media upload

`POST /api/media`, multipart field `file`. JPEG, PNG, WebP and GIF (up to 300 frames); at most 10 MB and 40 megapixels. EXIF is stripped. Errors: 413 `FILE_TOO_LARGE` / `IMAGE_TOO_LARGE`, 415 `UNSUPPORTED_MEDIA`. The response has `id`, `url`, `width`, `height`, `alt_ne`, `alt_en`, `caption` and `variants` (a map that is empty at first and fills in once the worker has run `make_variants`: 320, 640, 1024 and 1600 px widths plus `og`, 1200x630). Edit alt text with `PATCH /api/media/{id}`. Delete fails with 409 `MEDIA_IN_USE` while a post features it. Any request body above 1 MB on other routes is a 413.

## .docx import

`POST /api/import/docx`, multipart: `file` (the .docx, max 15 MB), `locale`, `category_id`, optional `title`. Creates a **draft** post for the caller and returns 201 `{post, report: {images, warnings[]}}`. Images are uploaded to media (at most 50; later ones are skipped with a warning). Open the returned post in the editor; `warnings` lists things dropped or approximated. Errors: 413 `DOCX_TOO_LARGE`, 415 `NOT_A_DOCX`, 422 `DOCX_UNREADABLE` / `IMPORT_TIMEOUT` / `CATEGORY_NOT_FOUND`, 503 `IMPORT_BUSY` (conversions are limited to 2 at a time).

## Revalidate webhook (worker to Next.js)

The outbox worker calls `MAWA_REVALIDATE_URL` after posts are published, updated, unpublished or unarchived, and after SEO refreshes:

```
POST <MAWA_REVALIDATE_URL>
x-revalidate-secret: <MAWA_REVALIDATE_SECRET>
Content-Type: application/json

{"tags": ["post:<uuid>", "home", "category:<slug>", "search", "feeds"], "paths": ["/ne/<category>/<slug>", ...]}
```

Tags: `post:{post_id}`, `home`, `category:{slug}` (the new category, and the old one after a move), `search`, `feeds` (sitemaps and RSS). `paths` are article paths (`/{locale}/{category}/{slug}`) plus old and new paths of any redirect. The route must check the secret (reject with 401) and call `revalidateTag` / `revalidatePath` for each entry; any non-2xx makes the worker retry with backoff. Tag your `fetch` calls with the same names (`home`, `category:{slug}`, `search`, `feeds`, and `post:{id}` using the `id` in the article response) so `revalidateTag` reaches them.

The worker also purges Cloudflare for the article paths, the home and locale pages, the category pages, `/sitemap.xml`, `/news-sitemap.xml`, `/rss.xml` and `/{locale}/{category}/rss.xml`.

## Next.js rewrites for feeds

Sitemaps and RSS are generated by the API; the public site proxies them so they live on the site origin:

```js
// next.config.js
async rewrites() {
  const api = process.env.API_ORIGIN; // e.g. https://api.mawapress.com
  return [
    { source: '/sitemap.xml', destination: `${api}/api/public/sitemap.xml` },
    { source: '/sitemaps/:path*', destination: `${api}/api/public/sitemaps/:path*` },
    { source: '/news-sitemap.xml', destination: `${api}/api/public/news-sitemap.xml` },
    { source: '/rss.xml', destination: `${api}/api/public/rss.xml?locale=ne` },
    { source: '/:locale(ne|en)/rss.xml', destination: `${api}/api/public/rss.xml?locale=:locale` },
    { source: '/:locale(ne|en)/:category/rss.xml', destination: `${api}/api/public/category/:category/rss.xml?locale=:locale` },
  ];
}
```

## Client IP: stats and search

`POST /api/public/stats/view` and `GET /api/public/search` are rate limited per client IP, and view counting is de-duplicated per IP. Call both **from the visitor's browser**, so the API sees the visitor. If the Next.js server calls them instead, it must forward the visitor's `CF-Connecting-IP` header (the API honours it when `MAWA_TRUST_PROXY=true`; Nginx must set it from `$remote_addr`, or use `MAWA_CLIENT_IP_HEADER=X-Real-IP` without Cloudflare, so it cannot be spoofed); otherwise every visitor shares the server's IP and gets throttled and under-counted. Never call these during server rendering or ISR.

## Public endpoints

Base `/api/public`, no auth. Responses carry `Cache-Control: public, s-maxage=60, stale-while-revalidate=86400` (XML feeds: `s-maxage=300`; trending padded: `s-maxage=15`) and an `X-Cache` header. `locale` is `ne` or `en` (else 404 `LOCALE_NOT_FOUND`). A card is `PublicCard`: `{id, title, slug, excerpt, category_slug, author_name, published_at, image: {url, width, height, alt, variants} | null}`.

| Endpoint | Returns |
| --- | --- |
| `GET /posts/{locale}/{slug}` | `PublicPostOut`: `{id, locale, title, slug, content_html, category_slug, author_name, published_at, updated_at, seo, alternates{locale: slug}, image}`. `seo` holds `title, description, canonical, og_image, hreflang, json_ld[]`. 404 `POST_NOT_FOUND`. |
| `GET /home?locale=` | `{breaking: [card], categories: [{category: {id, slug, name, seo_description}, posts: [card]}]}` |
| `GET /category/{slug}?locale=&limit=20&offset=0` | `{category, items: [card], total, limit, offset}` (limit 1..50). |
| `GET /categories` | Category tree: nodes with `children`. |
| `GET /search?q=&locale=&limit=20&offset=0` | `{items: [card], total, limit, offset}`. `q` needs 2+ characters (422 `QUERY_TOO_SHORT`). Rate limited. |
| `GET /trending?locale=&limit=10` | `[card]`, most viewed over the last 24 h (topped up from recent view counts on quiet days). Limit 1..20. |
| `POST /stats/view` | Body `{post_id, locale}`. Always 204, never reveals whether the view counted. |
| `GET /redirects/resolve?path=` | `{to_path, code}` (301) for an old article path, else 404 `REDIRECT_NOT_FOUND`. Call it from Next.js middleware before rendering a 404. |
| `GET /sitemap.xml`, `/sitemaps/categories.xml`, `/sitemaps/posts-YYYY-MM.xml`, `/news-sitemap.xml` | Sitemap XML. |
| `GET /rss.xml?locale=`, `GET /category/{slug}/rss.xml?locale=` | RSS 2.0. |
| `GET /api/healthz` | `{"status": "ok"}` (not under `/api/public`). |

The admin endpoints (`/api/posts`, `/api/media`, `/api/categories`, `/api/tags`, `/api/users`, `/api/admin/jobs`, `/api/import`) are fully described in `/openapi.json`. `GET /api/admin/jobs` rows carry `id, topic, attempts, last_error, payload, created_at, next_attempt_at, dead_at`; `POST /api/admin/jobs/retry-dead` requeues every dead event and returns `{"requeued": n}`.
