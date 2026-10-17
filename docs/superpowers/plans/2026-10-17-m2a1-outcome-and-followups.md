# M2a part 1 Outcome, Rulings and Follow-ups

**Branch:** `feat/m2a-content-api`. All 7 plan tasks are done and each passed its task review. The Opus whole-branch review said "ready to merge" with one Important finding, and a single fix wave addressed it. **118 tests pass with `-W error`.**

## What shipped
- Per-language publishing:
  - translation `status`, `published_at` and `updated_at`
  - publishing a post publishes the translations it has at that moment
  - `POST /api/posts/{id}/translations/{locale}/publish`
  - the public site serves a locale only when both the post and that translation are published
  - hreflang and alternates list only published translations
- Editing a **draft** translation of a live post emits no outbox event and leaves the public cache alone. Each locale's public `updated_at`/`dateModified` and `published_at`/`datePublished` come from that translation.
- `GET /api/posts` returns `{items, total, limit, offset}`. It filters by status, author, category, locale and `q`, and reporters only see their own posts. Each item includes `author_name`.
- Hardening:
  - JWTs must carry exp, sub and iat
  - a bad `sub` returns 401
  - failed logins run a dummy argon2 verify, so response time doesn't reveal whether the user exists
  - publish requires If-Match
  - slug collisions retry inside a SAVEPOINT, falling back to 409 `SLUG_TAKEN`; this applies to create, adding a translation and retitling a draft
  - server defaults are in place
  - an unknown public locale returns 404
  - the drift check also compares server defaults

## Rulings
| Ruling | Cost if wrong |
|---|---|
| A failed slug retry returns 409 `SLUG_TAKEN`. Slugs freeze per translation once that translation is published. Re-publishing a translation returns 409. An invalid locale returns 422 on editor routes and 404 on public routes. The outbox payload lists every translation's slug. | Small |
| Implementer commits use the trailer from their own attribution (Sonnet). Earlier Opus-trailer commits were left as they are. | Cosmetic |
| Final fix wave: draft edits stay off the public side, `post_translations.updated_at`, per-translation publish dates, slug retry on update, `compare_server_default`, `author_name` | Small |

## Carry into M2a part 2
- An outbox event and cache invalidation for unpublish and status changes, plus negative caching of 404s.
- A workflow decision: can an editor publish an unsubmitted draft? Add a "send back to reporter" transition (in_review → draft, editor+).
- Normalise email to lower case on every write (this lands with user admin).
- Add a `text_pattern_ops` index only if any slug lookup still uses LIKE (currently none do).
- SEO edge-case tests: `published_at=None` falls back, en-primary hreflang, `seo_title` passes through.
- Publishing a post or translation should bump `tr.updated_at`, so `dateModified` is never earlier than `datePublished`.

## Carry into M2b
- Login rate limit.
- Unarchive and the scheduler must also publish translations, or the post will be live in no locale.

## Deferred test polish (any time)
- Parametrize the JWT claim/sub loops.
- Test a valid token whose UUID `sub` matches no user.
- Assert row counts after a slug retry and after a 409.
- Assert that a stale publish changes nothing.
- Detect slug conflicts via `constraint_name`.
- Assert the enum is gone after downgrade (`pg_type`).
- Add backfill cases for scheduled and archived posts.
- Prove the href and caption tests fail when the escaping is broken.
