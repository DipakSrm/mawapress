# M1 Outcome, Rulings and Follow-ups

**Branch:** `feat/m1-backend-core` (20 commits on top of `main`, f1b8090..e174913)
**Result:** all 8 plan tasks are done. Every task passed a Sonnet task review, and the branch passed an Opus whole-branch review followed by one fix wave. **78 tests pass.**

## Decision needed before M3 (contract checkpoint)

- **Translation visibility.** Status lives on the post, so adding an English translation to an already-published post makes it public on the first save. With M3 autosave every 10 s, a half-written translation would go live. Options: (a) add a per-translation `status`/`is_published` field, or (b) require an explicit "publish translation" action on live posts. *Recommended: (a).*
- **Posts list endpoint.** `GET /api/posts` with filters for status, author and locale is missing. M3's posts list needs it, so add it before the OpenAPI freeze.

## Rulings made during execution

| # | Ruling | Cost if wrong |
|---|--------|---------------|
| R1 | The repo root is the project root, not a `mawapress/` subfolder | One directory move |
| R2/R4 | uv runs as `python -m uv` with `UV_PYTHON_INSTALL_DIR=C:\Users\dipak\uv-python`, because the default AppData install fails on this machine | None |
| R3 | Commits carry the Co-Authored-By trailer | Cosmetic |
| T2 | The slug tokenizer splits on runs of Devanagari letters, so a word followed by punctuation keeps schwa deletion (मोरङ, → morang) | Small |
| T4 | The renderer never raises on malformed JSON: non-dict nodes and non-str attributes are dropped, and nesting depth is capped at 64 | Small |
| T5 | Imports use `testcontainers.community.postgres`; `downgrade()` drops the enum types | None |
| T6 | The dev JWT secret was lengthened to silence a PyJWT warning | None |
| T7 | `update`, `submit` and `publish` take a `SELECT … FOR UPDATE` row lock, so the If-Match check is atomic | Minor lock contention |
| T8 | Redis errors degrade to a cache miss or a skipped invalidation, never a 500. The uvicorn smoke run was skipped because host port 5432 is held by another container | An untested live boot |
| Final | One fix wave: full error envelope, prod JWT-secret guard, ॉ/ऑ/ळ/ॐ mappings, `post.updated` outbox event, numbered slugs ≤ 80, cache helpers moved to `public/service.py`, `alembic check` drift test, README + `.env.example` | Small |
| Final | Translation visibility was left unchanged and goes to the user (above) | A draft translation could go live in M1 |

## Deferred follow-ups by milestone

**M2 (backend completion)**
- Security:
  - Fix the login timing oracle by verifying against a dummy hash for unknown or inactive emails, and add the login rate limit at the same time.
  - JWT decode must require `exp`/`sub`/`iat`, and a non-string `sub` must return 401, not 500.
- Concurrent creates with the same title hit the unique constraint and return a 500. Retry with the next suffix.
- Add an outbox and invalidation hook for unpublish and status changes. Consider negative caching for 404s.
- Editors can currently publish an unsubmitted draft without If-Match. Decide the workflow, and consider a "send back to reporter" transition.
- Data model:
  - add `server_default` for status, timestamps and `seo_auto`
  - enforce lower-case email (citext or normalise on write)
  - add a `text_pattern_ops` index for the slug `LIKE` lookup
- Tests to add first:
  - GET permission and non-author submit
  - `POST_NOT_FOUND`
  - malformed If-Match
  - expired, bad-signature and deactivated-user tokens
  - publish-time cache invalidation
  - the `en` locale and alternates
  - renderer quote-breaking in alt, href and caption
  - SEO edge cases
- An invalid locale on the public route should return 404, not 422.

**M3 (editor):** add Table, Youtube, Embed and codeBlock nodes to the renderer (they are currently flattened to text).

**M4 (public site):** escape `</script>` and entities when emitting JSON-LD and meta tags. SEO descriptions are unescaped plain text, so naive `dangerouslySetInnerHTML` would be a stored XSS. Sitewide JSON-LD, Twitter tags and the OG image route also belong here.

**M5 (infra):**
- Give the compose Postgres a MAWAPRESS-specific host port (5432 is taken on the dev machine).
- Add ruff excludes for `migrations/`.
- Close the Redis client in a lifespan hook.
- Put an Nginx body-size cap on `content_json`.
- Use a placeholder under 32 characters for `MAWA_JWT_SECRET` in `.env.example`, so the startup guard catches an unedited copy.
- Make the README's uv path generic.

**Cosmetic, any time:**
- `truncate_words` and `make_slug` drop a whole word when the cut lands on a separator.
- Use `fullmatch` for the renderer regexes.
- A non-string `HTTPException.detail` is rendered as its repr.
