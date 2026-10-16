# M2a part 2: Editorial Management and Public Feeds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution roles:** implementer **Sonnet**, per-task reviewer **Sonnet**, final whole-branch review **Opus**.
> **Branch:** `feat/m2a-content-api` (already checked out). Commit after every task.

**Goal:** Finish the editorial backend (user admin, taxonomy, revisions, slug redirects, workflow carry-overs) and add the read-only feeds the M4 public site needs (home, category, search, redirect resolution).

**Architecture:** Each concern lives in its spec module (`users`, `taxonomy`, `seo`, `posts`, `public`) with a thin `router.py` and the logic in `service.py`. Public feeds are cached in Redis under a single **feed generation counter**: invalidating feeds is one `INCR`, so no key scans are needed and stale keys expire through their 60 s TTL. Search uses a stored, generated `tsvector` built from the title (weight A) and a Python-derived plain-text body column (weight B), plus a `pg_trgm` index on the title for typo tolerance.

**Tech Stack:** Python 3.13, FastAPI 0.143, Pydantic 2.14, SQLAlchemy 2.1 (async, asyncpg), Alembic 1.20, PostgreSQL 17 (`pg_trgm`), Redis 7 (`redis.asyncio`, fakeredis in tests), pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-10-16-mawapress-design.md` (§3 modules, roles, workflow incl. "Per-language publishing"; §4 data model; §7 SEO; §8 caching; §9 errors). Carry-overs come from `docs/superpowers/plans/2026-10-17-m2a1-outcome-and-followups.md` and `docs/superpowers/plans/2026-10-16-m1-outcome-and-followups.md`.

## How to run things

All commands run from `backend/` in Git Bash with Docker running:

```bash
cd D:/Projects/BLOG/backend
UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/<path> -v
```

Full suite (must stay green with warnings as errors at the end of every task):

```bash
UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q
```

## Task order and independence

Run the tasks **in order**. The migrations form one linear chain (`b2e4f6a8c0d1` → T1 → T2 → T3 → T5 → T7 → T8), so a task's `down_revision` assumes the previous migration task has landed.

| Task | Code depends on | Notes |
|---|---|---|
| T1 Users admin + self-service | nothing | Code-independent of every other task |
| T2 Categories tree + feed cache plumbing | nothing | Introduces `invalidate_feeds`, `invalidate_public`, `is_valid_slug`, test helpers |
| T3 Tags + post tags | T2 (`is_valid_slug`, test helpers) | |
| T4 Workflow carry-overs | T2 (`invalidate_public`) | Code-independent of T3 |
| T5 Card fields + search | T2, T3 (rewrites `update_post`) | |
| T6 Home and category feeds | T2, T5 | |
| T7 Revisions + restore | T5 (rewrites `update_post`) | |
| T8 Slug change + redirects | T5, T7 (rewrites `update_post`) | |

## Global Constraints

- Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, PostgreSQL 17, Redis 7 (spec §2).
- Each module is a package under `backend/app/modules/<name>/` with `router.py`, `schemas.py`, `models.py`, `service.py`; modules talk to each other only through `service.py` functions (spec §3). Routers stay thin.
- Roles (spec §3): reporters create/edit own drafts and submit; editors also edit others' posts, publish, unpublish, and manage categories/tags; only admins manage users and roles.
- Workflow: `draft → in_review → scheduled | published → archived`. A post is public in a locale only when the post is published **and** that translation is published (spec §3 "Per-language publishing").
- Every save of a published post creates a `post_revisions` row (spec §3).
- Errors use the single envelope `{error: {code, message, details}}` via `AppError(status, code, message, details)` (spec §9).
- Slugs: kebab-case `[a-z0-9]+(-[a-z0-9]+)*`, ≤ 80 characters, unique per locale (spec §7).
- Canonical/public path shape: `/{locale}/{category}/{slug}` (spec §7).
- Slug change → automatic 301 in `redirects`; Next.js middleware checks a Redis-cached map (spec §7).
- Search: Postgres `tsvector` + `pg_trgm`; `GIN(search_vector)`, `GIN(title gin_trgm_ops)` (spec §2, §4).
- Redis: `public/*` API responses are cached for 60 s and cleared on publish; `Cache-Control: public, s-maxage=60, stale-while-revalidate=86400` (spec §8). A Redis error degrades to a cache miss or a skipped invalidation, never a 500 (M1 ruling T8).
- Invalid locale: 422 on editor routes, 404 on public routes (M2a1 ruling).
- Emails are stored lower-case (M1/M2a1 carry-over).
- Every schema change ships an Alembic migration with a working `downgrade()`; `tests/db/test_migrations.py` (upgrade, `alembic check` with `compare_server_default=True`, downgrade→upgrade round trip) must keep passing. Models and migrations agree exactly, including server defaults, FKs and indexes.
- The full suite passes with `-W error`.
- Commit messages end with a blank line and `Co-Authored-By: <implementer model> <noreply@anthropic.com>` (M2a1 ruling: implementers use their own attribution).

## Review Focus

1. **A slug changed back to an earlier value (A→B, then B→A).** Expect `A` live with no self-redirect and exactly one row `B → A`. Test: T8 `test_slug_change_back_never_leaves_a_self_redirect`.
2. **The same email with different case (`Asha@Mawapress.com` vs `asha@mawapress.com`).** Expect 409 `EMAIL_TAKEN`, and a mixed-case login works. Test: T1 `test_duplicate_email_any_case_is_409` and `test_admin_creates_user_with_lowercased_email_and_it_can_log_in`.
3. **Moving a category under its own descendant, or moving a subtree so it would be deeper than 3 levels.** Expect 409 (`CATEGORY_CYCLE` / `CATEGORY_TOO_DEEP`), nothing changed. Test: T2 `test_move_into_own_subtree_is_409` and `test_move_subtree_beyond_depth_3_is_409`.
4. **Search input that is only punctuation or tsquery syntax (`"!!"`, `"a & (b"`, `"' OR 1=1"`).** Expect 200 with an empty or trigram-only result, never a 500. Test: T5 `test_search_punctuation_and_operators_never_500`.
5. **Redis down on the new public endpoints (home, category, categories tree, redirect resolve).** Expect the response served from Postgres. Test: T6 `test_feeds_survive_redis_outage` and T8 `test_resolve_survives_redis_outage`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/app/modules/users/models.py` | Modify | add `bio` |
| `backend/app/modules/users/schemas.py` | Create | user admin and self-service request/response models |
| `backend/app/modules/users/service.py` | Create | create/list/update users, set password, self-service update, email normalisation |
| `backend/app/modules/users/router.py` | Create | `/api/users` (admin only) |
| `backend/app/modules/auth/router.py` | Modify | `PATCH /api/auth/me`, `MeOut.bio` |
| `backend/app/modules/taxonomy/models.py` | Modify | `Category.parent_id/sort/seo_description`, `Tag`, `post_tags` |
| `backend/app/modules/taxonomy/schemas.py` | Create | category and tag models, tree node |
| `backend/app/modules/taxonomy/service.py` | Create | category tree rules (cycle, depth 3, in-use), tag CRUD, `get_tags`, `category_tree`, `descendant_ids` |
| `backend/app/modules/taxonomy/router.py` | Create | `/api/categories`, `/api/tags` |
| `backend/app/modules/seo/slug.py` | Modify | `is_valid_slug` |
| `backend/app/modules/seo/models.py` | Create | `Redirect` |
| `backend/app/modules/seo/service.py` | Create | `article_path`, `record_slug_change` (chain collapse), `resolve_redirect`, `SlugChange` |
| `backend/app/modules/posts/models.py` | Modify | `Post.is_breaking`, `Post.tags`, translation `excerpt`, `body_text`, `search_vector`, indexes; `PostRevision` |
| `backend/app/modules/posts/schemas.py` | Modify | `tag_ids`, `excerpt`, `is_breaking`, `slug`, `TagOut`, `RevisionOut`, `SendBackIn` |
| `backend/app/modules/posts/service.py` | Modify | tags, excerpt/body_text, is_breaking, send-back, unpublish, publish bumps `tr.updated_at`, revisions, restore, explicit slug change |
| `backend/app/modules/posts/router.py` | Modify | new endpoints; `invalidate_public` everywhere |
| `backend/app/modules/public/service.py` | Modify | feed generation counter, cache keys, `invalidate_feeds`, `invalidate_public`, negative caching marker, `cache_get_json`/`cache_set_json` |
| `backend/app/modules/public/schemas.py` | Create | `PublicCard`, `CardPage`, `PublicCategory`, `HomeOut`, `CategoryFeedOut` |
| `backend/app/modules/public/feeds.py` | Create | card query, excerpt rule, home feed, category feed |
| `backend/app/modules/public/search.py` | Create | ranked search query |
| `backend/app/modules/public/router.py` | Modify | categories tree, home, category, search, redirect resolve, post 404 negative cache |
| `backend/app/db/models.py` | Modify | register `Tag`, `post_tags`, `PostRevision`, `Redirect` |
| `backend/app/main.py` | Modify | include users and taxonomy routers |
| `backend/migrations/versions/3c5e7a9b1d20_users_bio.py` | Create | T1 |
| `backend/migrations/versions/4d6f8b0c2e31_category_tree.py` | Create | T2 |
| `backend/migrations/versions/5e7a9c1d3f42_tags.py` | Create | T3 |
| `backend/migrations/versions/6f8b0d2e4a53_cards_and_search.py` | Create | T5 (incl. `pg_trgm`) |
| `backend/migrations/versions/7a9c1e3f5b64_post_revisions.py` | Create | T7 |
| `backend/migrations/versions/8b0d2f4a6c75_redirects.py` | Create | T8 |
| `backend/tests/conftest.py` | Modify | `CREATE EXTENSION pg_trgm` before `create_all` (T5) |
| `backend/tests/factories.py` | Modify | `make_category(parent_id, sort)`, `make_tag`, `doc`, `create_post_via_api`, `publish_via_api`, `DownRedis`, `down_client` |
| `backend/tests/public/test_public_api.py` | Modify | use the shared `DownRedis`/`down_client` (T2) |
| `backend/tests/users/test_users_admin.py`, `tests/users/test_me.py` | Create | T1 |
| `backend/tests/taxonomy/test_categories.py`, `tests/taxonomy/test_tags.py` | Create | T2, T3 |
| `backend/tests/posts/test_workflow.py` | Create | T4 |
| `backend/tests/posts/test_card_fields.py`, `tests/public/test_search.py` | Create | T5 |
| `backend/tests/public/test_feeds.py` | Create | T6 |
| `backend/tests/posts/test_revisions.py`, `tests/seo/test_redirects.py` | Create | T7, T8 |
| `backend/tests/seo/test_generator.py` | Modify | SEO edge cases (T4) |
| `backend/tests/db/test_migrations.py` | Modify | backfill test for `body_text` (T5) |

**Why these packages.** User admin goes in the existing `users` module (spec §3 lists `/users` there); the self-service `PATCH /api/auth/me` stays in `auth` next to `GET /me` but calls `users.service`. Categories and tags go in `taxonomy` (spec §3). Redirects belong to `seo` (spec §3 lists `/redirects` under `seo`), so the table and chain-collapse logic live in `seo`, and `posts.service` calls `seo.service.record_slug_change`. The public resolve endpoint lives in `public` because it is a cache-friendly read for Next.js. Feed and search queries go in new `public/feeds.py` and `public/search.py` so that `public/service.py` stays the home of cache keys and invalidation, as M1 decided.

## Decisions made in this plan

| Decision | Why |
|---|---|
| Editors may publish an unsubmitted draft (draft → published). | Editors own publishing (spec §3 matrix); forcing a self-submit adds a click and no safety. It is now explicit in `publish_post`'s docstring and pinned by a test. |
| The send-back note goes in the `post.sent_back` outbox payload; no new column. | It is a one-off message to the reporter. The M2b worker can notify from the payload, and nothing else reads it. |
| `body_text` is a stored plain-text column written in Python; `search_vector` is a **generated** column over `title` + `body_text`. | A generated column must be an immutable SQL expression. Regex-stripping HTML in SQL would index figcaptions and HTML entities (`&amp;`), whereas `seo.generator.plain_text` already drops captions and unescapes entities. `body_text` also feeds the auto excerpt. |
| `excerpt` is stored only when an editor sets it; the card excerpt is computed at read time as `excerpt or truncate_words(body_text, 200)`. | The auto value can never go stale after a body edit. |
| Feed caches (home, category, categories tree) are keyed by a generation counter `public:feeds:gen`; invalidation is `INCR`. | Category pages have many `(slug, locale, limit, offset)` keys. Without the counter we would need a `SCAN` on every publish. |
| Public post 404s are negatively cached for 30 s; every path that can make a slug public already deletes that key. | M2a1 carry-over. Publish, translation publish and slug change all call `invalidate_post_cache` over the post's current slugs. |
| Revision `editor_id` is the user whose save replaced that state. | Translations do not track a last editor; the saver is the only actor we know. |
| Restore does not restore the slug. | The slug is URL identity and changes only through the explicit `slug` field, which writes redirects. |
| Category slugs are immutable through `PATCH /api/categories/{id}` (`extra="forbid"` gives 422). | Changing a category slug would need path redirects for every post; that is out of scope. |
| Downgrades never drop `pg_trgm`. | Another schema or a DBA may rely on it, and `alembic check` ignores extensions. Upgrade uses `CREATE EXTENSION IF NOT EXISTS`, so the round trip is idempotent. |
| `users.name_ne` and `avatar_media_id` are not added. | Out of scope (avatar needs media, M2b). |
| No `text_pattern_ops` slug index. | The M2a1 carry-over asked for one only if a slug lookup still uses `LIKE`. None does: slug lookups are equality checks, and the title `ILIKE` in `GET /api/posts` is a staff-only filter. |
| Revisions are recorded for saves that change a **published** translation (not for draft saves of a published post). | Draft translations are invisible to readers. Recording them would flood the table with 10 s autosaves (spec §5). |

---

### Task 1: User admin and self-service profile

Admins list, create and update users and reset passwords. Every user can edit their own name and bio and change their own password. Emails are lower-cased on every write; login already lower-cases.

**Files:**
- Modify: `backend/app/modules/users/models.py` (add `bio`)
- Create: `backend/app/modules/users/schemas.py`, `backend/app/modules/users/service.py`, `backend/app/modules/users/router.py`
- Modify: `backend/app/modules/auth/router.py` (`MeOut.bio`, `PATCH /me`)
- Modify: `backend/app/main.py` (include users router)
- Create: `backend/migrations/versions/3c5e7a9b1d20_users_bio.py`
- Test: `backend/tests/users/__init__.py` (empty), `backend/tests/users/test_users_admin.py`, `backend/tests/users/test_me.py`

**Interfaces:**
- Consumes: `require_role(Role)` and `current_user` from `app.modules.auth.deps`; `hash_password`, `verify_password` from `app.modules.auth.security`.
- Produces:
  - `users.service.normalize_email(email: str) -> str`
  - `users.service.list_users(session) -> list[User]`
  - `users.service.get_user(session, user_id: uuid.UUID) -> User` (404 `USER_NOT_FOUND`)
  - `users.service.create_user(session, data: UserCreate) -> User` (409 `EMAIL_TAKEN`)
  - `users.service.update_user(session, actor: User, user_id: uuid.UUID, data: UserUpdate) -> User` (409 `CANNOT_MODIFY_SELF`)
  - `users.service.set_password(session, user_id: uuid.UUID, password: str) -> None`
  - `users.service.update_me(session, user: User, data: MeUpdate) -> User` (403 `INVALID_CURRENT_PASSWORD`)
  - `User.bio: str | None`
  - Migration revision `3c5e7a9b1d20` (down: `b2e4f6a8c0d1`)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/users/__init__.py` (empty file).

Create `backend/tests/users/test_users_admin.py`:

```python
from app.modules.users.models import Role
from tests.factories import auth_header, make_user


async def login(client, email: str, password: str):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def create_user(client, admin, **overrides):
    body = {"email": "asha@mawapress.com", "name": "Asha Rai", "role": "reporter", "password": "long-enough-1"}
    body.update(overrides)
    return await client.post("/api/users", json=body, headers=auth_header(admin))


async def test_only_admins_reach_user_admin(client, session):
    editor = await make_user(session, role=Role.editor)
    assert (await client.get("/api/users")).status_code == 401
    denied = await client.get("/api/users", headers=auth_header(editor))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_admin_creates_user_with_lowercased_email_and_it_can_log_in(client, session):
    admin = await make_user(session, role=Role.admin)
    r = await create_user(client, admin, email="Asha.Rai@Mawapress.com", bio="Biratnagar desk")
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "asha.rai@mawapress.com"
    assert body["role"] == "reporter"
    assert body["is_active"] is True
    assert body["bio"] == "Biratnagar desk"
    assert "password_hash" not in body and "password" not in body

    ok = await login(client, "ASHA.RAI@mawapress.com", "long-enough-1")
    assert ok.status_code == 200


async def test_duplicate_email_any_case_is_409(client, session):
    admin = await make_user(session, role=Role.admin)
    assert (await create_user(client, admin, email="asha@mawapress.com")).status_code == 201
    dup = await create_user(client, admin, email="Asha@MAWAPRESS.com")
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_create_validates_password_role_and_name(client, session):
    admin = await make_user(session, role=Role.admin)
    assert (await create_user(client, admin, password="short-9ch")).status_code == 422
    assert (await create_user(client, admin, role="owner")).status_code == 422
    assert (await create_user(client, admin, name="   ")).status_code == 422
    assert (await create_user(client, admin, email="not-an-email")).status_code == 422


async def test_list_users_includes_everyone(client, session):
    admin = await make_user(session, role=Role.admin, name="Admin")
    await make_user(session, name="Reporter One")
    r = await client.get("/api/users", headers=auth_header(admin))
    assert r.status_code == 200
    names = {u["name"] for u in r.json()}
    assert {"Admin", "Reporter One"} <= names


async def test_admin_updates_name_role_and_deactivates(client, session):
    admin = await make_user(session, role=Role.admin)
    target = await make_user(session, name="Old Name")
    r = await client.patch(
        f"/api/users/{target.id}",
        json={"name": "  New Name ", "role": "editor", "is_active": False},
        headers=auth_header(admin),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"
    assert r.json()["role"] == "editor"
    assert r.json()["is_active"] is False
    # A deactivated user's existing token stops working.
    assert (await client.get("/api/auth/me", headers=auth_header(target))).status_code == 401


async def test_admin_cannot_deactivate_or_demote_self(client, session):
    admin = await make_user(session, role=Role.admin)
    url = f"/api/users/{admin.id}"
    for patch in ({"is_active": False}, {"role": "editor"}):
        r = await client.patch(url, json=patch, headers=auth_header(admin))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CANNOT_MODIFY_SELF"
    renamed = await client.patch(url, json={"name": "Still Admin", "role": "admin"}, headers=auth_header(admin))
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Still Admin"


async def test_patch_rejects_unknown_fields_and_unknown_user(client, session):
    admin = await make_user(session, role=Role.admin)
    target = await make_user(session)
    bad = await client.patch(f"/api/users/{target.id}", json={"email": "x@mawapress.com"}, headers=auth_header(admin))
    assert bad.status_code == 422
    missing = await client.patch(
        "/api/users/00000000-0000-0000-0000-000000000000", json={"name": "x"}, headers=auth_header(admin)
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_admin_sets_password(client, session):
    admin = await make_user(session, role=Role.admin)
    target = await make_user(session, email="pw@mawapress.com", password="old-password-1")
    url = f"/api/users/{target.id}/password"
    short = await client.post(url, json={"password": "123456789"}, headers=auth_header(admin))
    assert short.status_code == 422
    r = await client.post(url, json={"password": "new-password-1"}, headers=auth_header(admin))
    assert r.status_code == 204
    assert (await login(client, "pw@mawapress.com", "old-password-1")).status_code == 401
    assert (await login(client, "pw@mawapress.com", "new-password-1")).status_code == 200
```

Create `backend/tests/users/test_me.py`:

```python
from tests.factories import auth_header, make_user


async def test_me_includes_bio(client, session):
    user = await make_user(session)
    r = await client.get("/api/auth/me", headers=auth_header(user))
    assert r.status_code == 200
    assert r.json()["bio"] is None


async def test_update_own_name_and_bio(client, session):
    user = await make_user(session, name="Old")
    r = await client.patch(
        "/api/auth/me", json={"name": "  Sita Rai ", "bio": "Covers Urlabari"}, headers=auth_header(user)
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Sita Rai"
    assert r.json()["bio"] == "Covers Urlabari"

    cleared = await client.patch("/api/auth/me", json={"bio": ""}, headers=auth_header(user))
    assert cleared.json()["bio"] is None
    assert cleared.json()["name"] == "Sita Rai"


async def test_change_own_password_requires_current_password(client, session):
    user = await make_user(session, email="me@mawapress.com", password="first-password-1")
    url, headers = "/api/auth/me", auth_header(user)

    missing = await client.patch(url, json={"new_password": "second-password-2"}, headers=headers)
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    wrong = await client.patch(
        url, json={"current_password": "nope", "new_password": "second-password-2"}, headers=headers
    )
    assert wrong.status_code == 403

    ok = await client.patch(
        url, json={"current_password": "first-password-1", "new_password": "second-password-2"}, headers=headers
    )
    assert ok.status_code == 200
    login = await client.post("/api/auth/login", json={"email": "me@mawapress.com", "password": "second-password-2"})
    assert login.status_code == 200


async def test_me_cannot_change_role_or_use_short_password(client, session):
    user = await make_user(session, password="first-password-1")
    headers = auth_header(user)
    assert (await client.patch("/api/auth/me", json={"role": "admin"}, headers=headers)).status_code == 422
    short = await client.patch(
        "/api/auth/me", json={"current_password": "first-password-1", "new_password": "short"}, headers=headers
    )
    assert short.status_code == 422


async def test_me_update_requires_login(client):
    assert (await client.patch("/api/auth/me", json={"name": "x"})).status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/users -v`
Expected: FAIL. `/api/users` returns 404 and `/api/auth/me` has no `bio`.

- [ ] **Step 3: Add `bio` to the model and write the migration**

In `backend/app/modules/users/models.py`, add `Text` to the `sqlalchemy` import and add the column after `is_active`:

```python
from sqlalchemy import DateTime, Enum, String, Text, Uuid, func, true
```

```python
    bio: Mapped[str | None] = mapped_column(Text)
```

Create `backend/migrations/versions/3c5e7a9b1d20_users_bio.py`:

```python
"""users.bio and lower-case emails

Revision ID: 3c5e7a9b1d20
Revises: b2e4f6a8c0d1
Create Date: 2026-10-17 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3c5e7a9b1d20"
down_revision: Union[str, Sequence[str], None] = "b2e4f6a8c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    # Emails are stored lower-case from now on; normalise older rows. A case-only
    # duplicate fails here on the unique index, loudly, which is what we want.
    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "bio")
```

- [ ] **Step 4: Write the schemas**

Create `backend/app/modules/users/schemas.py`:

```python
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.modules.users.models import Role

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Password = Annotated[str, Field(min_length=10, max_length=128)]
Bio = Annotated[str, Field(max_length=2000)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: Role
    is_active: bool
    bio: str | None
    created_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: Name
    role: Role
    password: Password
    bio: Bio | None = None


class UserUpdate(BaseModel):
    """Admin edit. Email is deliberately not editable here (extra fields are a 422)."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    role: Role | None = None
    is_active: bool | None = None


class PasswordSet(BaseModel):
    password: Password


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    bio: Bio | None = None
    current_password: str | None = Field(default=None, max_length=128)
    new_password: Password | None = None
```

- [ ] **Step 5: Write the service**

Create `backend/app/modules/users/service.py`:

```python
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.auth.security import hash_password, verify_password
from app.modules.users.models import Role, User
from app.modules.users.schemas import MeUpdate, UserCreate, UserUpdate


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_taken_error() -> AppError:
    return AppError(409, "EMAIL_TAKEN", "A user with this email already exists")


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.created_at, User.id))).all())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "User not found")
    return user


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    email = normalize_email(data.email)
    if await session.scalar(select(User.id).where(User.email == email)) is not None:
        raise _email_taken_error()
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        name=data.name,
        role=data.role,
        bio=data.bio or None,
    )
    try:
        async with session.begin_nested():  # a concurrent create can still win the race
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise _email_taken_error() from exc
    await session.commit()
    return user


async def update_user(session: AsyncSession, actor: User, user_id: uuid.UUID, data: UserUpdate) -> User:
    user = await get_user(session, user_id)
    if user.id == actor.id and (data.is_active is False or (data.role is not None and data.role != Role.admin)):
        raise AppError(409, "CANNOT_MODIFY_SELF", "Admins cannot deactivate or demote themselves")
    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    await session.commit()
    return user


async def set_password(session: AsyncSession, user_id: uuid.UUID, password: str) -> None:
    user = await get_user(session, user_id)
    user.password_hash = hash_password(password)
    await session.commit()


async def update_me(session: AsyncSession, user: User, data: MeUpdate) -> User:
    if data.new_password is not None:
        if data.current_password is None or not verify_password(data.current_password, user.password_hash):
            raise AppError(403, "INVALID_CURRENT_PASSWORD", "Current password is incorrect")
        user.password_hash = hash_password(data.new_password)
    if data.name is not None:
        user.name = data.name
    if "bio" in data.model_fields_set:
        user.bio = data.bio or None
    await session.commit()
    return user
```

Access tokens issued before a password change stay valid until they expire (15 min). Revoking them needs refresh tokens, which are M2b.

- [ ] **Step 6: Write the routers and register them**

Create `backend/app/modules/users/router.py`:

```python
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.auth.deps import require_role
from app.modules.users import service
from app.modules.users.models import Role, User
from app.modules.users.schemas import PasswordSet, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])
admins = require_role(Role.admin)


@router.get("", response_model=list[UserOut])
async def list_users(admin: User = Depends(admins), session: AsyncSession = Depends(get_session)) -> list[User]:
    return await service.list_users(session)


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate, admin: User = Depends(admins), session: AsyncSession = Depends(get_session)
) -> User:
    return await service.create_user(session, body)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, admin: User = Depends(admins), session: AsyncSession = Depends(get_session)
) -> User:
    return await service.update_user(session, admin, user_id, body)


@router.post("/{user_id}/password", status_code=204)
async def set_password(
    user_id: uuid.UUID, body: PasswordSet, admin: User = Depends(admins), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.set_password(session, user_id, body.password)
    return Response(status_code=204)
```

In `backend/app/modules/auth/router.py`:
1. Add the imports:

```python
from app.modules.users import service as users_service
from app.modules.users.schemas import MeUpdate
```

2. Replace `MeOut` with:

```python
class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: Role
    bio: str | None
```

3. Add this route after `me`:

```python
@router.patch("/me", response_model=MeOut)
async def update_me(
    body: MeUpdate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> User:
    return await users_service.update_me(session, user, body)
```

In `backend/app/main.py`, import the users router and include it after the auth router:

```python
from app.modules.users.router import router as users_router
```

```python
    app.include_router(users_router)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/users tests/auth tests/db/test_migrations.py -v`
Expected: all PASS, including `test_models_match_migrations` and the round trip.

- [ ] **Step 8: Run the full suite**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add app/modules/users app/modules/auth/router.py app/main.py migrations/versions/3c5e7a9b1d20_users_bio.py tests/users
git commit -m "feat(users): admin user management, self-service profile, lower-case emails

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
```

---

### Task 2: Category tree, public categories endpoint, feed-cache plumbing

Categories gain `parent_id` (a tree at most 3 levels deep, no cycles), `sort` and `seo_description`. Editors manage them; reporters can list them, because the editor sidebar needs the list. `GET /api/public/categories` returns the tree. This task also adds the feed generation counter and `invalidate_public`, and switches the existing post routes to it, so later feed tasks only add readers.

**Files:**
- Modify: `backend/app/modules/taxonomy/models.py`
- Create: `backend/app/modules/taxonomy/schemas.py`, `backend/app/modules/taxonomy/service.py`, `backend/app/modules/taxonomy/router.py`
- Modify: `backend/app/modules/seo/slug.py` (`is_valid_slug`)
- Modify: `backend/app/modules/public/service.py` (generation counter, cache helpers, `invalidate_feeds`, `invalidate_public`)
- Modify: `backend/app/modules/public/router.py` (`GET /api/public/categories`)
- Modify: `backend/app/modules/posts/router.py` (use `invalidate_public`)
- Modify: `backend/app/main.py` (include taxonomy router)
- Create: `backend/migrations/versions/4d6f8b0c2e31_category_tree.py`
- Modify: `backend/tests/factories.py` (`make_category` params, `doc`, `create_post_via_api`, `publish_via_api`, `DownRedis`, `down_client`)
- Modify: `backend/tests/public/test_public_api.py` (use the shared `DownRedis`/`down_client`)
- Test: `backend/tests/taxonomy/__init__.py` (empty), `backend/tests/taxonomy/test_categories.py`, `backend/tests/seo/test_slug.py`

**Interfaces:**
- Consumes: `make_slug` from `app.modules.seo.slug`; `CACHE_CONTROL`, `CACHE_TTL_SECONDS`, `invalidate_post_cache` from `app.modules.public.service`.
- Produces:
  - `seo.slug.is_valid_slug(slug: str, max_len: int = 80) -> bool`
  - `public.service.FEED_GEN_KEY = "public:feeds:gen"`
  - `public.service.feed_generation(redis) -> str | None` (`None` means Redis is down: skip the cache)
  - `public.service.categories_cache_key(gen: str) -> str`
  - `public.service.cache_get(redis, key: str) -> str | None` and `public.service.cache_set(redis, key: str, value: str, ttl: int = CACHE_TTL_SECONDS) -> None` (both swallow `RedisError`)
  - `public.service.invalidate_feeds(redis) -> None`
  - `public.service.invalidate_public(redis, post: Post) -> None` (post keys + feeds)
  - `taxonomy.service.MAX_CATEGORY_DEPTH = 3`
  - `taxonomy.service.all_categories(session) -> dict[int, Category]` (ordered by `sort, id`)
  - `taxonomy.service.descendant_ids(cats: dict[int, Category], cat_id: int) -> set[int]` (includes `cat_id`)
  - `taxonomy.service.list_categories`, `create_category`, `update_category`, `delete_category`, `category_tree(session) -> list[CategoryNode]`
  - `taxonomy.schemas.CategoryOut`, `CategoryNode`, `CategoryCreate`, `CategoryUpdate`
  - Test helpers: `make_category(session, slug="morang", name_ne="मोरङ", name_en="Morang", parent_id=None, sort=0)`, `doc(text)`, `create_post_via_api(client, user, category, *, title="बाढी समाचार", locale="ne", body="पानी परिरहेको छ", **extra) -> dict`, `publish_via_api(client, editor, post: dict) -> dict`, `DownRedis`, `down_client(session) -> AsyncClient`
  - Migration revision `4d6f8b0c2e31` (down: `3c5e7a9b1d20`)

- [ ] **Step 1: Extend the test factories**

Replace `backend/tests/factories.py` with:

```python
import uuid

from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.db.session import get_session
from app.main import create_app
from app.modules.auth.security import create_access_token, hash_password
from app.modules.taxonomy.models import Category
from app.modules.users.models import Role, User


async def make_user(
    session: AsyncSession,
    *,
    role: Role = Role.reporter,
    email: str | None = None,
    password: str = "secret-pass-1",
    name: str = "Test User",
    is_active: bool = True,
) -> User:
    user = User(
        email=(email or f"{uuid.uuid4().hex[:10]}@mawapress.com").lower(),
        password_hash=hash_password(password),
        name=name,
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


async def make_category(
    session: AsyncSession,
    slug: str = "morang",
    name_ne: str = "मोरङ",
    name_en: str = "Morang",
    *,
    parent_id: int | None = None,
    sort: int = 0,
) -> Category:
    cat = Category(slug=slug, name_ne=name_ne, name_en=name_en, parent_id=parent_id, sort=sort)
    session.add(cat)
    await session.flush()
    return cat


def auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.value)}"}


def auth_if_match(user: User, updated_at: str) -> dict[str, str]:
    return {**auth_header(user), "If-Match": updated_at}


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def create_post_via_api(
    client: AsyncClient,
    user: User,
    category: Category,
    *,
    title: str = "बाढी समाचार",
    locale: str = "ne",
    body: str = "पानी परिरहेको छ",
    **extra,
) -> dict:
    r = await client.post(
        "/api/posts",
        json={"locale": locale, "title": title, "content_json": doc(body), "category_id": category.id, **extra},
        headers=auth_header(user),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def publish_via_api(client: AsyncClient, editor: User, post: dict) -> dict:
    r = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 200, r.text
    return r.json()


class DownRedis:
    """Every Redis call fails the way a dropped connection does."""

    async def get(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    set = delete = incr = get


async def down_client(session: AsyncSession) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: DownRedis()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
```

In `backend/tests/public/test_public_api.py`, delete the local `class DownRedis` and `async def down_client` definitions, remove the now-unused imports (`ASGITransport`, `AsyncClient`, `RedisConnectionError`, `get_redis`, `get_session`, `create_app`), and import them from the factories instead:

```python
from tests.factories import auth_header, auth_if_match, down_client, make_category, make_user
```

(`invalidate_feeds` calls `redis.incr`; the old local `DownRedis` had no `incr`, so it would raise `AttributeError` instead of `RedisError`.)

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/seo/test_slug.py`:

```python
from app.modules.seo.slug import is_valid_slug


def test_is_valid_slug():
    assert is_valid_slug("local-news")
    assert is_valid_slug("province-1")
    assert is_valid_slug("a" * 80)
    for bad in ("", "Local", "bad--slug", "-lead", "trail-", "with space", "नेपाल", "a" * 81, "snake_case"):
        assert not is_valid_slug(bad), bad
```

Create `backend/tests/taxonomy/__init__.py` (empty file).

Create `backend/tests/taxonomy/test_categories.py`:

```python
from app.modules.public.service import FEED_GEN_KEY
from app.modules.users.models import Role
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    down_client,
    make_category,
    make_user,
    publish_via_api,
)


async def create_cat(client, user, **body):
    payload = {"name_ne": "खेलकुद", "name_en": "Sports"}
    payload.update(body)
    return await client.post("/api/categories", json=payload, headers=auth_header(user))


async def test_editor_creates_category_with_derived_slug(client, session):
    editor = await make_user(session, role=Role.editor)
    r = await create_cat(client, editor)
    assert r.status_code == 201
    assert r.json() == {
        "id": r.json()["id"], "parent_id": None, "slug": "sports", "name_ne": "खेलकुद",
        "name_en": "Sports", "sort": 0, "seo_description": None,
    }


async def test_reporter_can_list_but_not_manage(client, session):
    reporter = await make_user(session)
    await make_category(session)
    assert (await create_cat(client, reporter)).status_code == 403
    listed = await client.get("/api/categories", headers=auth_header(reporter))
    assert listed.status_code == 200
    assert [c["slug"] for c in listed.json()] == ["morang"]


async def test_invalid_and_duplicate_slugs(client, session):
    editor = await make_user(session, role=Role.editor)
    await make_category(session)
    for bad in ("Bad Slug", "bad--slug", "नेपाल"):
        r = await create_cat(client, editor, slug=bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "INVALID_SLUG"
    assert (await create_cat(client, editor, slug="a" * 81)).status_code == 422
    dup = await create_cat(client, editor, slug="morang")
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "SLUG_TAKEN"


async def test_tree_is_at_most_three_levels(client, session):
    editor = await make_user(session, role=Role.editor)
    root = await make_category(session, slug="province-1")
    child = await make_category(session, slug="morang", parent_id=root.id)
    grand = await create_cat(client, editor, slug="biratnagar", parent_id=child.id)
    assert grand.status_code == 201
    too_deep = await create_cat(client, editor, slug="ward-5", parent_id=grand.json()["id"])
    assert too_deep.status_code == 409
    assert too_deep.json()["error"]["code"] == "CATEGORY_TOO_DEEP"


async def test_unknown_parent_is_422(client, session):
    editor = await make_user(session, role=Role.editor)
    r = await create_cat(client, editor, parent_id=999999)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CATEGORY_NOT_FOUND"


async def test_move_into_own_subtree_is_409(client, session):
    editor = await make_user(session, role=Role.editor)
    a = await make_category(session, slug="a")
    b = await make_category(session, slug="b", parent_id=a.id)
    for parent in (b.id, a.id):
        r = await client.patch(f"/api/categories/{a.id}", json={"parent_id": parent}, headers=auth_header(editor))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CATEGORY_CYCLE"


async def test_move_subtree_beyond_depth_3_is_409(client, session):
    editor = await make_user(session, role=Role.editor)
    x = await make_category(session, slug="x")
    await make_category(session, slug="y", parent_id=x.id)
    z = await make_category(session, slug="z")
    w = await make_category(session, slug="w", parent_id=z.id)

    deep = await client.patch(f"/api/categories/{x.id}", json={"parent_id": w.id}, headers=auth_header(editor))
    assert deep.status_code == 409
    assert deep.json()["error"]["code"] == "CATEGORY_TOO_DEEP"

    ok = await client.patch(f"/api/categories/{x.id}", json={"parent_id": z.id}, headers=auth_header(editor))
    assert ok.status_code == 200
    assert ok.json()["parent_id"] == z.id


async def test_update_names_sort_seo_and_move_to_root(client, session):
    editor = await make_user(session, role=Role.editor)
    root = await make_category(session, slug="province-1")
    cat = await make_category(session, slug="morang", parent_id=root.id)
    r = await client.patch(
        f"/api/categories/{cat.id}",
        json={"name_en": "Morang District", "sort": 5, "seo_description": "News from Morang", "parent_id": None},
        headers=auth_header(editor),
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["name_en"], body["sort"], body["seo_description"], body["parent_id"]) == (
        "Morang District", 5, "News from Morang", None,
    )
    assert body["slug"] == "morang"


async def test_patch_cannot_change_slug_and_unknown_id_is_404(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    r = await client.patch(f"/api/categories/{cat.id}", json={"slug": "renamed"}, headers=auth_header(editor))
    assert r.status_code == 422
    missing = await client.patch("/api/categories/999999", json={"sort": 1}, headers=auth_header(editor))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CATEGORY_NOT_FOUND"


async def test_delete_refused_while_posts_or_children_reference_it(client, session):
    editor = await make_user(session, role=Role.editor)
    used = await make_category(session, slug="used")
    await create_post_via_api(client, editor, used)
    parent = await make_category(session, slug="parent")
    await make_category(session, slug="child", parent_id=parent.id)
    empty = await make_category(session, slug="empty")

    r = await client.delete(f"/api/categories/{used.id}", headers=auth_header(editor))
    assert r.status_code == 409
    assert r.json()["error"] == {
        "code": "CATEGORY_IN_USE", "message": r.json()["error"]["message"], "details": {"posts": 1, "children": 0},
    }
    r = await client.delete(f"/api/categories/{parent.id}", headers=auth_header(editor))
    assert r.status_code == 409
    assert r.json()["error"]["details"] == {"posts": 0, "children": 1}

    assert (await client.delete(f"/api/categories/{empty.id}", headers=auth_header(editor))).status_code == 204
    assert (await client.delete(f"/api/categories/{empty.id}", headers=auth_header(editor))).status_code == 404


async def test_public_tree_is_nested_sorted_and_cached(client, session):
    editor = await make_user(session, role=Role.editor)
    second = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports", sort=2)
    first = await make_category(session, slug="province-1", name_ne="प्रदेश १", name_en="Province 1", sort=1)
    await make_category(session, slug="morang", parent_id=first.id)

    r = await client.get("/api/public/categories")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    assert r.headers["x-cache"] == "MISS"
    tree = r.json()
    assert [n["slug"] for n in tree] == ["province-1", "sports"]
    assert [c["slug"] for c in tree[0]["children"]] == ["morang"]
    assert tree[0]["children"][0]["children"] == []
    assert tree[1]["id"] == second.id

    assert (await client.get("/api/public/categories")).headers["x-cache"] == "HIT"

    await create_cat(client, editor, name_en="Weather", name_ne="मौसम", sort=3)
    after = await client.get("/api/public/categories")
    assert after.headers["x-cache"] == "MISS"
    assert [n["slug"] for n in after.json()] == ["province-1", "sports", "weather"]


async def test_public_tree_survives_redis_outage(session):
    await make_category(session)
    async with await down_client(session) as down:
        r = await down.get("/api/public/categories")
    assert r.status_code == 200
    assert [n["slug"] for n in r.json()] == ["morang"]


async def test_public_post_changes_bump_feed_generation(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await create_post_via_api(client, editor, cat)
    assert await fake_redis.get(FEED_GEN_KEY) is None  # drafts do not touch public caches

    live = await publish_via_api(client, editor, post)
    assert await fake_redis.get(FEED_GEN_KEY) == "1"

    r = await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    assert r.status_code == 200
    assert await fake_redis.get(FEED_GEN_KEY) == "2"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/taxonomy tests/seo/test_slug.py -v`
Expected: FAIL (ImportError for `FEED_GEN_KEY` / `is_valid_slug`; `make_category` has no `parent_id`).

- [ ] **Step 4: Add `is_valid_slug`**

Append to `backend/app/modules/seo/slug.py`:

```python
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def is_valid_slug(slug: str, max_len: int = 80) -> bool:
    """True when slug looks like make_slug output: lower-case kebab-case ASCII, <= max_len."""
    return len(slug) <= max_len and SLUG_PATTERN.fullmatch(slug) is not None
```

- [ ] **Step 5: Extend the model and write the migration**

Replace `backend/app/modules/taxonomy/models.py` with:

```python
from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", name="fk_categories_parent_id"))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name_ne: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))
    sort: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    seo_description: Mapped[str | None] = mapped_column(String(320))
```

Create `backend/migrations/versions/4d6f8b0c2e31_category_tree.py`:

```python
"""category tree, sort and seo_description

Revision ID: 4d6f8b0c2e31
Revises: 3c5e7a9b1d20
Create Date: 2026-10-17 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4d6f8b0c2e31"
down_revision: Union[str, Sequence[str], None] = "3c5e7a9b1d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("categories", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_categories_parent_id", "categories", "categories", ["parent_id"], ["id"])
    op.add_column("categories", sa.Column("sort", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("categories", sa.Column("seo_description", sa.String(length=320), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("categories", "seo_description")
    op.drop_column("categories", "sort")
    op.drop_constraint("fk_categories_parent_id", "categories", type_="foreignkey")
    op.drop_column("categories", "parent_id")
```

- [ ] **Step 6: Add the feed-cache plumbing to `public/service.py`**

Replace `backend/app/modules/public/service.py` with:

```python
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.posts.models import Post

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=86400"

# Every feed key (home, category pages, the category tree) embeds the current value of this
# counter. Invalidating all feeds is one INCR; the orphaned keys expire through their TTL.
FEED_GEN_KEY = "public:feeds:gen"


def post_cache_key(locale: str, slug: str) -> str:
    return f"public:post:{locale}:{slug}"


def categories_cache_key(gen: str) -> str:
    return f"public:categories:{gen}"


async def feed_generation(redis: Redis) -> str | None:
    """Current feed generation, or None when Redis is unavailable (callers then skip the cache)."""
    try:
        return await redis.get(FEED_GEN_KEY) or "0"
    except RedisError:
        logger.warning("Cache read failed; serving from database", exc_info=True)
        return None


async def cache_get(redis: Redis, key: str) -> str | None:
    try:
        return await redis.get(key)
    except RedisError:
        logger.warning("Cache read failed; serving from database", exc_info=True)
        return None


async def cache_set(redis: Redis, key: str, value: str, ttl: int = CACHE_TTL_SECONDS) -> None:
    try:
        await redis.set(key, value, ex=ttl)
    except RedisError:
        logger.warning("Cache write failed; response not cached", exc_info=True)


async def invalidate_post_cache(redis: Redis, post: Post) -> None:
    keys = [post_cache_key(t.locale, t.slug) for t in post.translations]
    if not keys:
        return
    try:
        await redis.delete(*keys)
    except RedisError:
        logger.warning("Cache invalidation failed; stale entries expire via TTL", exc_info=True)


async def invalidate_feeds(redis: Redis) -> None:
    try:
        await redis.incr(FEED_GEN_KEY)
    except RedisError:
        logger.warning("Feed invalidation failed; stale feeds expire via TTL", exc_info=True)


async def invalidate_public(redis: Redis, post: Post) -> None:
    """Everything a public change to this post can affect: its article keys and every feed."""
    await invalidate_post_cache(redis, post)
    await invalidate_feeds(redis)
```

In `backend/app/modules/posts/router.py`, change the import

```python
from app.modules.public.service import invalidate_post_cache
```

to

```python
from app.modules.public.service import invalidate_public
```

and replace each of the three calls `await invalidate_post_cache(redis, post)` (in `update_post`, `publish_post`, `publish_translation`) with `await invalidate_public(redis, post)`.

- [ ] **Step 7: Write the taxonomy schemas**

Create `backend/app/modules/taxonomy/schemas.py`:

```python
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
SlugIn = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Sort = Annotated[int, Field(ge=-10000, le=10000)]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_ne: Text120
    name_en: Text120
    slug: SlugIn | None = None  # defaults to make_slug(name_en)
    parent_id: int | None = None
    sort: Sort = 0
    seo_description: str | None = Field(default=None, max_length=320)


class CategoryUpdate(BaseModel):
    """The slug is immutable here: changing it would break every article URL in the category."""

    model_config = ConfigDict(extra="forbid")

    name_ne: Text120 | None = None
    name_en: Text120 | None = None
    parent_id: int | None = None  # send null explicitly to move to the root
    sort: Sort | None = None
    seo_description: str | None = Field(default=None, max_length=320)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    slug: str
    name_ne: str
    name_en: str
    sort: int
    seo_description: str | None


class CategoryNode(CategoryOut):
    children: list["CategoryNode"] = Field(default_factory=list)
```

- [ ] **Step 8: Write the taxonomy service**

Create `backend/app/modules/taxonomy/service.py`:

```python
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.posts.models import Post
from app.modules.seo.slug import is_valid_slug, make_slug
from app.modules.taxonomy.models import Category
from app.modules.taxonomy.schemas import CategoryCreate, CategoryNode, CategoryUpdate

MAX_CATEGORY_DEPTH = 3  # root = 1


def _slug_taken() -> AppError:
    return AppError(409, "SLUG_TAKEN", "That slug is already in use")


def _invalid_slug() -> AppError:
    return AppError(422, "INVALID_SLUG", "Slug must be lower-case letters, digits and single hyphens, at most 80 chars")


async def all_categories(session: AsyncSession) -> dict[int, Category]:
    rows = await session.scalars(select(Category).order_by(Category.sort, Category.id))
    return {c.id: c for c in rows}


def _depth(cats: dict[int, Category], cat_id: int) -> int:
    depth, current = 0, cat_id
    while current is not None:
        depth += 1
        current = cats[current].parent_id
    return depth


def _height(cats: dict[int, Category], cat_id: int) -> int:
    children = [c.id for c in cats.values() if c.parent_id == cat_id]
    return 1 + max((_height(cats, child) for child in children), default=0)


def descendant_ids(cats: dict[int, Category], cat_id: int) -> set[int]:
    found = {cat_id}
    frontier = [cat_id]
    while frontier:
        parent = frontier.pop()
        for c in cats.values():
            if c.parent_id == parent and c.id not in found:
                found.add(c.id)
                frontier.append(c.id)
    return found


def _check_parent(cats: dict[int, Category], cat_id: int | None, parent_id: int) -> None:
    if parent_id not in cats:
        raise AppError(422, "CATEGORY_NOT_FOUND", "Parent category does not exist")
    if cat_id is not None and parent_id in descendant_ids(cats, cat_id):
        raise AppError(409, "CATEGORY_CYCLE", "A category cannot be moved under itself or its descendants")
    height = _height(cats, cat_id) if cat_id is not None else 1
    if _depth(cats, parent_id) + height > MAX_CATEGORY_DEPTH:
        raise AppError(409, "CATEGORY_TOO_DEEP", f"Categories nest at most {MAX_CATEGORY_DEPTH} levels deep")


async def list_categories(session: AsyncSession) -> list[Category]:
    return list((await all_categories(session)).values())


async def get_category(session: AsyncSession, cat_id: int) -> Category:
    cat = await session.get(Category, cat_id)
    if cat is None:
        raise AppError(404, "CATEGORY_NOT_FOUND", "Category not found")
    return cat


async def create_category(session: AsyncSession, data: CategoryCreate) -> Category:
    slug = data.slug if data.slug is not None else make_slug(data.name_en)
    if not is_valid_slug(slug):
        raise _invalid_slug()
    cats = await all_categories(session)
    if data.parent_id is not None:
        _check_parent(cats, None, data.parent_id)
    if any(c.slug == slug for c in cats.values()):
        raise _slug_taken()
    cat = Category(
        slug=slug,
        name_ne=data.name_ne,
        name_en=data.name_en,
        parent_id=data.parent_id,
        sort=data.sort,
        seo_description=data.seo_description or None,
    )
    try:
        async with session.begin_nested():
            session.add(cat)
            await session.flush()
    except IntegrityError as exc:
        raise _slug_taken() from exc
    await session.commit()
    return cat


async def update_category(session: AsyncSession, cat_id: int, data: CategoryUpdate) -> Category:
    cats = await all_categories(session)
    cat = cats.get(cat_id)
    if cat is None:
        raise AppError(404, "CATEGORY_NOT_FOUND", "Category not found")
    fields = data.model_fields_set
    if "parent_id" in fields and data.parent_id != cat.parent_id:
        if data.parent_id is not None:
            _check_parent(cats, cat.id, data.parent_id)
        cat.parent_id = data.parent_id
    if data.name_ne is not None:
        cat.name_ne = data.name_ne
    if data.name_en is not None:
        cat.name_en = data.name_en
    if data.sort is not None:
        cat.sort = data.sort
    if "seo_description" in fields:
        cat.seo_description = data.seo_description or None
    await session.commit()
    return cat


async def delete_category(session: AsyncSession, cat_id: int) -> None:
    cat = await get_category(session, cat_id)
    posts = await session.scalar(select(func.count()).select_from(Post).where(Post.category_id == cat_id))
    children = await session.scalar(select(func.count()).select_from(Category).where(Category.parent_id == cat_id))
    if posts or children:
        raise AppError(409, "CATEGORY_IN_USE", "Move its posts and child categories first",
                       {"posts": posts or 0, "children": children or 0})
    await session.delete(cat)
    await session.commit()


async def category_tree(session: AsyncSession) -> list[CategoryNode]:
    cats = await all_categories(session)  # ordered by sort, id, so siblings come out ordered
    nodes = {cid: CategoryNode.model_validate(c) for cid, c in cats.items()}
    roots: list[CategoryNode] = []
    for cid, c in cats.items():
        if c.parent_id is None:
            roots.append(nodes[cid])
        else:
            nodes[c.parent_id].children.append(nodes[cid])
    return roots
```

Known limitation, recorded for M2b: renaming a category does not refresh the stored `seo_auto` (`articleSection`, breadcrumb name) of its posts until each post is saved again. The M2b worker can re-run SEO on a `category.updated` event.

- [ ] **Step 9: Write the taxonomy router, the public tree endpoint, and register the router**

Create `backend/app/modules/taxonomy/router.py`:

```python
from fastapi import APIRouter, Depends, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.db.session import get_session
from app.modules.auth.deps import require_role
from app.modules.public.service import invalidate_feeds
from app.modules.taxonomy import service
from app.modules.taxonomy.models import Category
from app.modules.taxonomy.schemas import CategoryCreate, CategoryOut, CategoryUpdate
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api", tags=["taxonomy"])
any_staff = require_role(Role.reporter)
editors = require_role(Role.editor)


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)) -> list[Category]:
    return await service.list_categories(session)


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryCreate,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Category:
    cat = await service.create_category(session, body)
    await invalidate_feeds(redis)
    return cat


@router.patch("/categories/{cat_id}", response_model=CategoryOut)
async def update_category(
    cat_id: int,
    body: CategoryUpdate,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Category:
    cat = await service.update_category(session, cat_id, body)
    await invalidate_feeds(redis)
    return cat


@router.delete("/categories/{cat_id}", status_code=204)
async def delete_category(
    cat_id: int,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Response:
    await service.delete_category(session, cat_id)
    await invalidate_feeds(redis)
    return Response(status_code=204)
```

In `backend/app/modules/public/router.py`:
1. Add the imports:

```python
from pydantic import TypeAdapter

from app.modules.public.service import cache_get, cache_set, categories_cache_key, feed_generation
from app.modules.taxonomy import service as taxonomy_service
from app.modules.taxonomy.schemas import CategoryNode
```

2. Add below `SUPPORTED_LOCALES`:

```python
_category_tree = TypeAdapter(list[CategoryNode])
```

3. Add this route at the end of the file:

```python
@router.get("/categories", response_model=list[CategoryNode])
async def public_categories(
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> list[CategoryNode]:
    response.headers["Cache-Control"] = CACHE_CONTROL
    gen = await feed_generation(redis)
    key = categories_cache_key(gen) if gen is not None else None
    cached = await cache_get(redis, key) if key else None
    if cached:
        response.headers["X-Cache"] = "HIT"
        return _category_tree.validate_json(cached)
    tree = await taxonomy_service.category_tree(session)
    if key:
        await cache_set(redis, key, _category_tree.dump_json(tree).decode())
    response.headers["X-Cache"] = "MISS"
    return tree
```

In `backend/app/main.py`, import the taxonomy router and include it after the posts router:

```python
from app.modules.taxonomy.router import router as taxonomy_router
```

```python
    app.include_router(taxonomy_router)
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/taxonomy tests/seo tests/public tests/db/test_migrations.py -v`
Expected: all PASS.

- [ ] **Step 11: Run the full suite**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`
Expected: all PASS.

- [ ] **Step 12: Commit**

```bash
git add app/modules/taxonomy app/modules/seo/slug.py app/modules/public app/modules/posts/router.py app/main.py migrations/versions/4d6f8b0c2e31_category_tree.py tests/factories.py tests/public/test_public_api.py tests/taxonomy tests/seo/test_slug.py
git commit -m "feat(taxonomy): category tree CRUD, public category tree, feed cache generation

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
```

---

### Task 3: Tags and post tags

Editors manage tags. Posts get a many-to-many `tags` relation through `post_tags`. `POST /api/posts` and `PATCH /api/posts/{id}` accept `tag_ids`: omitted means unchanged, `[]` clears, and unknown ids give 422. `PostOut` includes `tags`.

**Files:**
- Modify: `backend/app/modules/taxonomy/models.py` (`Tag`, `post_tags`)
- Modify: `backend/app/modules/taxonomy/schemas.py`, `backend/app/modules/taxonomy/service.py`, `backend/app/modules/taxonomy/router.py`
- Modify: `backend/app/modules/posts/models.py` (`Post.tags`)
- Modify: `backend/app/modules/posts/schemas.py` (`tag_ids`, `PostOut.tags`)
- Modify: `backend/app/modules/posts/service.py` (`create_post`, `update_post`)
- Modify: `backend/app/db/models.py` (register `Tag`, `post_tags`)
- Create: `backend/migrations/versions/5e7a9c1d3f42_tags.py`
- Modify: `backend/tests/factories.py` (`make_tag`)
- Test: `backend/tests/taxonomy/test_tags.py`

**Interfaces:**
- Consumes: `is_valid_slug`, `make_slug` (T2); `_slug_taken()`, `_invalid_slug()`, `Text120`, `SlugIn` in taxonomy (T2); `create_post_via_api`, `auth_if_match` test helpers (T2).
- Produces:
  - `taxonomy.models.Tag` (`id`, `slug`, `name_ne`, `name_en`) and the `post_tags` table (`post_id`, `tag_id`, PK both, `ix_post_tags_tag_id`)
  - `taxonomy.service.get_tags(session, ids: list[int]) -> list[Tag]` (deduplicated, ordered by id; 422 `TAG_NOT_FOUND` with `details.missing`)
  - `taxonomy.service.list_tags(session, q: str | None) -> list[Tag]`, `create_tag`, `update_tag`, `delete_tag`
  - `taxonomy.schemas.TagOut`, `TagCreate`, `TagUpdate`
  - `Post.tags: list[Tag]` (selectin, ordered by `Tag.id`)
  - `PostCreate.tag_ids: list[int]` (default `[]`, max 20), `PostUpdate.tag_ids: list[int] | None`, `PostOut.tags: list[TagOut]`
  - Test helper `make_tag(session, slug="flood", name_ne="बाढी", name_en="Flood") -> Tag`
  - Migration revision `5e7a9c1d3f42` (down: `4d6f8b0c2e31`)

- [ ] **Step 1: Add the `make_tag` factory**

In `backend/tests/factories.py`, change the taxonomy import to

```python
from app.modules.taxonomy.models import Category, Tag
```

and add below `make_category`:

```python
async def make_tag(session: AsyncSession, slug: str = "flood", name_ne: str = "बाढी", name_en: str = "Flood") -> Tag:
    tag = Tag(slug=slug, name_ne=name_ne, name_en=name_en)
    session.add(tag)
    await session.flush()
    return tag
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/taxonomy/test_tags.py`:

```python
from sqlalchemy import func, select

from app.modules.taxonomy.models import post_tags
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, create_post_via_api, make_category, make_tag, make_user


async def test_editor_tag_crud(client, session):
    editor = await make_user(session, role=Role.editor)
    created = await client.post("/api/tags", json={"name_ne": "बाढी", "name_en": "Flood"}, headers=auth_header(editor))
    assert created.status_code == 201
    tag = created.json()
    assert (tag["slug"], tag["name_ne"], tag["name_en"]) == ("flood", "बाढी", "Flood")

    found = await client.get("/api/tags", params={"q": "flo"}, headers=auth_header(editor))
    assert [t["slug"] for t in found.json()] == ["flood"]

    renamed = await client.patch(f"/api/tags/{tag['id']}", json={"name_en": "Floods"}, headers=auth_header(editor))
    assert renamed.status_code == 200
    assert (renamed.json()["name_en"], renamed.json()["slug"]) == ("Floods", "flood")

    assert (await client.delete(f"/api/tags/{tag['id']}", headers=auth_header(editor))).status_code == 204
    assert (await client.get("/api/tags", headers=auth_header(editor))).json() == []
    assert (await client.delete(f"/api/tags/{tag['id']}", headers=auth_header(editor))).status_code == 404


async def test_reporter_can_list_but_not_manage_tags(client, session):
    reporter = await make_user(session)
    await make_tag(session)
    assert (await client.get("/api/tags", headers=auth_header(reporter))).status_code == 200
    denied = await client.post("/api/tags", json={"name_ne": "क", "name_en": "K"}, headers=auth_header(reporter))
    assert denied.status_code == 403


async def test_tag_slug_rules(client, session):
    editor = await make_user(session, role=Role.editor)
    tag = await make_tag(session)
    dup = await client.post("/api/tags", json={"name_ne": "बाढी", "name_en": "Flood"}, headers=auth_header(editor))
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "SLUG_TAKEN"
    bad = await client.post(
        "/api/tags", json={"name_ne": "क", "name_en": "K", "slug": "Not Valid"}, headers=auth_header(editor)
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_SLUG"
    immutable = await client.patch(f"/api/tags/{tag.id}", json={"slug": "other"}, headers=auth_header(editor))
    assert immutable.status_code == 422


async def test_post_tags_create_update_clear_and_keep(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    flood = await make_tag(session)
    rain = await make_tag(session, slug="rain", name_ne="वर्षा", name_en="Rain")

    post = await create_post_via_api(client, editor, cat, tag_ids=[rain.id, flood.id, flood.id])
    assert [t["slug"] for t in post["tags"]] == ["flood", "rain"]  # deduplicated, ordered by id

    url = f"/api/posts/{post['id']}"
    only_rain = await client.patch(
        url, json={"locale": "ne", "tag_ids": [rain.id]}, headers=auth_if_match(editor, post["updated_at"])
    )
    assert [t["slug"] for t in only_rain.json()["tags"]] == ["rain"]

    kept = await client.patch(
        url, json={"locale": "ne", "title": "नयाँ"}, headers=auth_if_match(editor, only_rain.json()["updated_at"])
    )
    assert [t["slug"] for t in kept.json()["tags"]] == ["rain"]

    cleared = await client.patch(
        url, json={"locale": "ne", "tag_ids": []}, headers=auth_if_match(editor, kept.json()["updated_at"])
    )
    assert cleared.json()["tags"] == []


async def test_unknown_tag_ids_are_422_and_change_nothing(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    flood = await make_tag(session)
    r = await client.post(
        "/api/posts",
        json={"locale": "ne", "title": "x", "content_json": {"type": "doc"}, "category_id": cat.id,
              "tag_ids": [flood.id, 999999]},
        headers=auth_header(editor),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "TAG_NOT_FOUND"
    assert r.json()["error"]["details"] == {"missing": [999999]}

    post = await create_post_via_api(client, editor, cat, tag_ids=[flood.id])
    bad = await client.patch(
        f"/api/posts/{post['id']}", json={"locale": "ne", "tag_ids": [999999]},
        headers=auth_if_match(editor, post["updated_at"]),
    )
    assert bad.status_code == 422
    after = await client.get(f"/api/posts/{post['id']}", headers=auth_header(editor))
    assert [t["slug"] for t in after.json()["tags"]] == ["flood"]
    assert after.json()["updated_at"] == post["updated_at"]


async def test_deleting_a_tag_detaches_it_from_posts(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    flood = await make_tag(session)
    await create_post_via_api(client, editor, cat, tag_ids=[flood.id])
    assert (await client.delete(f"/api/tags/{flood.id}", headers=auth_header(editor))).status_code == 204
    assert await session.scalar(select(func.count()).select_from(post_tags)) == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/taxonomy/test_tags.py -v`
Expected: FAIL (ImportError: cannot import `Tag` / `post_tags`).

- [ ] **Step 4: Add the models, register them, and write the migration**

Replace `backend/app/modules/taxonomy/models.py` with:

```python
from sqlalchemy import Column, ForeignKey, Index, Integer, String, Table, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", name="fk_categories_parent_id"))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name_ne: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))
    sort: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    seo_description: Mapped[str | None] = mapped_column(String(320))


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name_ne: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))


post_tags = Table(
    "post_tags",
    Base.metadata,
    Column("post_id", Uuid, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_post_tags_tag_id", "tag_id"),
)
```

In `backend/app/modules/posts/models.py`, add the relationship to `Post`, below `translations`:

```python
    tags: Mapped[list["Tag"]] = relationship(secondary="post_tags", lazy="selectin", order_by="Tag.id")
```

and add this import at the top of the file (it is only needed for the type annotation):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.taxonomy.models import Tag
```

Replace `backend/app/db/models.py` with:

```python
"""Import every model so Base.metadata is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.db.outbox import OutboxEvent
from app.modules.posts.models import Post, PostTranslation
from app.modules.taxonomy.models import Category, Tag, post_tags
from app.modules.users.models import User

__all__ = ["Base", "Category", "OutboxEvent", "Post", "PostTranslation", "Tag", "User", "post_tags"]
```

Create `backend/migrations/versions/5e7a9c1d3f42_tags.py`:

```python
"""tags and post_tags

Revision ID: 5e7a9c1d3f42
Revises: 4d6f8b0c2e31
Create Date: 2026-10-17 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "5e7a9c1d3f42"
down_revision: Union[str, Sequence[str], None] = "4d6f8b0c2e31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name_ne", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "post_tags",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id", "tag_id"),
    )
    op.create_index("ix_post_tags_tag_id", "post_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_post_tags_tag_id", table_name="post_tags")
    op.drop_table("post_tags")
    op.drop_table("tags")
```

- [ ] **Step 5: Add tag schemas, service functions and routes**

Append to `backend/app/modules/taxonomy/schemas.py`:

```python
class TagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_ne: Text120
    name_en: Text120
    slug: SlugIn | None = None  # defaults to make_slug(name_en)


class TagUpdate(BaseModel):
    """The slug is immutable: tag pages (M4) are addressed by it."""

    model_config = ConfigDict(extra="forbid")

    name_ne: Text120 | None = None
    name_en: Text120 | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name_ne: str
    name_en: str
```

In `backend/app/modules/taxonomy/service.py`, change the imports to

```python
from sqlalchemy import func, or_, select
```

```python
from app.modules.taxonomy.models import Category, Tag
from app.modules.taxonomy.schemas import CategoryCreate, CategoryNode, CategoryUpdate, TagCreate, TagUpdate
```

and append:

```python
def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_tags(session: AsyncSession, q: str | None = None) -> list[Tag]:
    stmt = select(Tag).order_by(Tag.name_en, Tag.id).limit(100)
    q = q.strip() if q else None
    if q:
        pattern = f"%{_escape_like(q)}%"
        stmt = stmt.where(or_(
            Tag.name_en.ilike(pattern, escape="\\"),
            Tag.name_ne.ilike(pattern, escape="\\"),
            Tag.slug.ilike(pattern, escape="\\"),
        ))
    return list((await session.scalars(stmt)).all())


async def get_tag(session: AsyncSession, tag_id: int) -> Tag:
    tag = await session.get(Tag, tag_id)
    if tag is None:
        raise AppError(404, "TAG_NOT_FOUND", "Tag not found")
    return tag


async def get_tags(session: AsyncSession, ids: list[int]) -> list[Tag]:
    """Load tags by id for a post. Unknown ids are a client error (422), never silently dropped."""
    wanted = sorted(set(ids))
    if not wanted:
        return []
    tags = list((await session.scalars(select(Tag).where(Tag.id.in_(wanted)).order_by(Tag.id))).all())
    missing = sorted(set(wanted) - {t.id for t in tags})
    if missing:
        raise AppError(422, "TAG_NOT_FOUND", "Unknown tag ids", {"missing": missing})
    return tags


async def create_tag(session: AsyncSession, data: TagCreate) -> Tag:
    slug = data.slug if data.slug is not None else make_slug(data.name_en)
    if not is_valid_slug(slug):
        raise _invalid_slug()
    if await session.scalar(select(Tag.id).where(Tag.slug == slug)) is not None:
        raise _slug_taken()
    tag = Tag(slug=slug, name_ne=data.name_ne, name_en=data.name_en)
    try:
        async with session.begin_nested():
            session.add(tag)
            await session.flush()
    except IntegrityError as exc:
        raise _slug_taken() from exc
    await session.commit()
    return tag


async def update_tag(session: AsyncSession, tag_id: int, data: TagUpdate) -> Tag:
    tag = await get_tag(session, tag_id)
    if data.name_ne is not None:
        tag.name_ne = data.name_ne
    if data.name_en is not None:
        tag.name_en = data.name_en
    await session.commit()
    return tag


async def delete_tag(session: AsyncSession, tag_id: int) -> None:
    tag = await get_tag(session, tag_id)
    await session.delete(tag)  # post_tags rows go with it (ON DELETE CASCADE)
    await session.commit()
```

In `backend/app/modules/taxonomy/router.py`, change the imports to

```python
from fastapi import APIRouter, Depends, Query, Response
```

```python
from app.modules.taxonomy.models import Category, Tag
from app.modules.taxonomy.schemas import CategoryCreate, CategoryOut, CategoryUpdate, TagCreate, TagOut, TagUpdate
```

and append:

```python
@router.get("/tags", response_model=list[TagOut])
async def list_tags(
    q: str | None = Query(default=None, max_length=100),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
) -> list[Tag]:
    return await service.list_tags(session, q)


@router.post("/tags", response_model=TagOut, status_code=201)
async def create_tag(body: TagCreate, user: User = Depends(editors), session: AsyncSession = Depends(get_session)) -> Tag:
    return await service.create_tag(session, body)


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: int, body: TagUpdate, user: User = Depends(editors), session: AsyncSession = Depends(get_session)
) -> Tag:
    return await service.update_tag(session, tag_id, body)


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, user: User = Depends(editors), session: AsyncSession = Depends(get_session)) -> Response:
    await service.delete_tag(session, tag_id)
    return Response(status_code=204)
```

Tags are not shown on any public endpoint yet, so tag changes do not invalidate public caches.

- [ ] **Step 6: Accept `tag_ids` on posts and return `tags`**

In `backend/app/modules/posts/schemas.py`:
1. Add the import:

```python
from app.modules.taxonomy.schemas import TagOut
```

2. Add to `PostCreate`, after `category_id`:

```python
    tag_ids: list[int] = Field(default_factory=list, max_length=20)
```

3. Add to `PostUpdate`, after `seo_description`:

```python
    tag_ids: list[int] | None = Field(default=None, max_length=20)  # None = unchanged, [] = clear
```

4. Add to `PostOut`, after `translations`:

```python
    tags: list[TagOut]
```

In `backend/app/modules/posts/service.py`:
1. Add the import:

```python
from app.modules.taxonomy import service as taxonomy_service
```

2. In `create_post`, load the tags right after the category check:

```python
    tags = await taxonomy_service.get_tags(session, data.tag_ids)
```

and in `assign()` build the post with them:

```python
        post = Post(author_id=author.id, category_id=data.category_id, status=PostStatus.draft, tags=list(tags))
```

3. In `update_post`, validate the tags straight after `_check_version(post, if_match)` (before anything is changed, so a 422 leaves the post untouched):

```python
    tags = await taxonomy_service.get_tags(session, data.tag_ids) if data.tag_ids is not None else None
```

and apply them just before the final `post.updated_at = now` line (the one directly above `if public_changed:`):

```python
    if tags is not None:
        post.tags = tags
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/taxonomy tests/posts tests/db -v`
Expected: all PASS (existing post tests now also see `"tags": []` in `PostOut`).

- [ ] **Step 8: Run the full suite**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add app/modules/taxonomy app/modules/posts app/db/models.py migrations/versions/5e7a9c1d3f42_tags.py tests/factories.py tests/taxonomy/test_tags.py
git commit -m "feat(taxonomy): tags CRUD and post tags

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
```

---

### Task 4: Workflow carry-overs (send back, unpublish, publish dates, negative caching, SEO edge cases)

This task closes the M1/M2a1 workflow follow-ups:
- `POST /api/posts/{id}/send-back` (editor+, `in_review → draft`, optional note in the outbox payload).
- `POST /api/posts/{id}/unpublish` (editor+, If-Match, `published → archived`, outbox `post.unpublished`, invalidates the post and every feed; translation statuses are kept).
- The editor-may-publish-a-draft rule becomes explicit and tested.
- Publishing bumps `tr.updated_at`, so `dateModified ≥ datePublished`.
- Public post 404s are negatively cached for 30 s.
- SEO edge-case unit tests.

**Files:**
- Modify: `backend/app/modules/posts/schemas.py` (`SendBackIn`)
- Modify: `backend/app/modules/posts/service.py` (`send_back_post`, `unpublish_post`, `publish_post`, `publish_translation`)
- Modify: `backend/app/modules/posts/router.py` (two routes)
- Modify: `backend/app/modules/public/service.py` (`NOT_FOUND_MARKER`, `NEGATIVE_TTL_SECONDS`)
- Modify: `backend/app/modules/public/router.py` (`get_public_post` uses the helpers and caches 404s)
- Test: `backend/tests/posts/test_workflow.py`, `backend/tests/seo/test_generator.py`

**Interfaces:**
- Consumes: `invalidate_public`, `cache_get`, `cache_set` (T2); `create_post_via_api`, `publish_via_api`, `auth_if_match` test helpers (T2).
- Produces:
  - `posts.service.send_back_post(session, editor: User, post_id: uuid.UUID, note: str | None) -> Post`
  - `posts.service.unpublish_post(session, post_id: uuid.UUID, if_match: str | None) -> Post`
  - `posts.schemas.SendBackIn(note: str | None, max 1000)`
  - Outbox topics `post.sent_back` (payload `post_id`, `author_id`, `editor_id`, `note`) and `post.unpublished` (same payload as `post.published`)
  - `public.service.NOT_FOUND_MARKER = "__404__"`, `public.service.NEGATIVE_TTL_SECONDS = 30`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/posts/test_workflow.py`:

```python
from datetime import datetime

from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.public.service import FEED_GEN_KEY, NOT_FOUND_MARKER, post_cache_key
from app.modules.users.models import Role
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    doc,
    make_category,
    make_user,
    publish_via_api,
)


async def submit(client, user, post):
    r = await client.post(f"/api/posts/{post['id']}/submit", headers=auth_header(user))
    assert r.status_code == 200
    return r.json()


async def events(session, topic):
    return (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == topic).order_by(OutboxEvent.id))).all()


async def test_editor_may_publish_an_unsubmitted_draft(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    draft = await create_post_via_api(client, reporter, cat)
    assert draft["status"] == "draft"
    live = await publish_via_api(client, editor, draft)
    assert live["status"] == "published"


async def test_editor_sends_back_in_review_post_with_note(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    in_review = await submit(client, reporter, await create_post_via_api(client, reporter, cat))

    r = await client.post(
        f"/api/posts/{in_review['id']}/send-back", json={"note": "  Add a second source  "}, headers=auth_header(editor)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "draft"
    [event] = await events(session, "post.sent_back")
    assert event.payload == {
        "post_id": in_review["id"], "author_id": str(reporter.id), "editor_id": str(editor.id),
        "note": "Add a second source",
    }

    # The reporter owns a draft again and can keep editing it.
    edit = await client.patch(
        f"/api/posts/{in_review['id']}", json={"locale": "ne", "title": "स्रोतसहित"},
        headers=auth_if_match(reporter, r.json()["updated_at"]),
    )
    assert edit.status_code == 200


async def test_send_back_guards(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    draft = await create_post_via_api(client, reporter, cat)

    not_in_review = await client.post(f"/api/posts/{draft['id']}/send-back", headers=auth_header(editor))
    assert not_in_review.status_code == 409
    assert not_in_review.json()["error"]["code"] == "INVALID_TRANSITION"

    await submit(client, reporter, draft)
    assert (await client.post(f"/api/posts/{draft['id']}/send-back", headers=auth_header(reporter))).status_code == 403
    no_body = await client.post(f"/api/posts/{draft['id']}/send-back", headers=auth_header(editor))
    assert no_body.status_code == 200
    [event] = await events(session, "post.sent_back")
    assert event.payload["note"] is None


async def test_unpublish_archives_hides_and_invalidates(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await create_post_via_api(client, editor, cat)
    with_en = (await client.patch(
        f"/api/posts/{post['id']}", json={"locale": "en", "title": "Flood in Biratnagar", "content_json": doc("Rain")},
        headers=auth_if_match(editor, post["updated_at"]),
    )).json()
    live = await publish_via_api(client, editor, with_en)
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 200  # warm cache
    gen_before = await fake_redis.get(FEED_GEN_KEY)

    r = await client.post(f"/api/posts/{live['id']}/unpublish", headers=auth_if_match(editor, live["updated_at"]))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "archived"
    assert {t["status"] for t in body["translations"]} == {"published"}  # translations keep their status

    [event] = await events(session, "post.unpublished")
    assert event.payload["slugs"] == {"ne": "badhi-samachar", "en": "flood-in-biratnagar"}
    assert int(await fake_redis.get(FEED_GEN_KEY)) == int(gen_before) + 1
    for path in ("/api/public/posts/ne/badhi-samachar", "/api/public/posts/en/flood-in-biratnagar"):
        assert (await client.get(path)).status_code == 404


async def test_unpublish_guards(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    draft = await create_post_via_api(client, editor, cat)
    url = f"/api/posts/{draft['id']}/unpublish"

    assert (await client.post(url, headers=auth_if_match(editor, draft["updated_at"]))).status_code == 409
    live = await publish_via_api(client, editor, draft)
    assert (await client.post(url, headers=auth_header(editor))).status_code == 428
    stale = await client.post(url, headers=auth_if_match(editor, draft["updated_at"]))
    assert stale.status_code == 412
    assert (await client.post(url, headers=auth_if_match(reporter, live["updated_at"]))).status_code == 403


async def test_publish_bumps_translation_updated_at(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))

    public = (await client.get("/api/public/posts/ne/badhi-samachar")).json()
    assert public["updated_at"] == public["published_at"]
    article = public["seo"]["json_ld"][0]
    assert datetime.fromisoformat(article["dateModified"]) >= datetime.fromisoformat(article["datePublished"])


async def test_publishing_a_translation_bumps_its_updated_at(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))
    with_en = (await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "en", "title": "Flood in Biratnagar", "content_json": doc("Rain")},
        headers=auth_if_match(editor, live["updated_at"]),
    )).json()
    r = await client.post(
        f"/api/posts/{live['id']}/translations/en/publish", headers=auth_if_match(editor, with_en["updated_at"])
    )
    assert r.status_code == 200

    en = (await client.get("/api/public/posts/en/flood-in-biratnagar")).json()
    assert en["updated_at"] == en["published_at"]
    article = en["seo"]["json_ld"][0]
    assert article["dateModified"] == article["datePublished"]


async def test_public_404_is_negatively_cached_until_publish(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    draft = await create_post_via_api(client, editor, cat)
    key = post_cache_key("ne", "badhi-samachar")

    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 404
    assert await fake_redis.get(key) == NOT_FOUND_MARKER
    assert 0 < await fake_redis.ttl(key) <= 30
    again = await client.get("/api/public/posts/ne/badhi-samachar")  # served from the marker
    assert again.status_code == 404
    assert again.json()["error"]["code"] == "POST_NOT_FOUND"

    await publish_via_api(client, editor, draft)
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 200
```

Append to `backend/tests/seo/test_generator.py`:

```python
def test_missing_published_at_falls_back_to_modified_at():
    later = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    article = build_seo(make_input(published_at=None, modified_at=later), SITE).json_ld[0]
    assert article["datePublished"] == later.isoformat()
    assert article["dateModified"] == later.isoformat()


def test_english_primary_hreflang_keeps_x_default_on_nepali():
    meta = build_seo(
        make_input(locale="en", title="Heavy rain in Biratnagar", slug="heavy-rain-in-biratnagar",
                   category_name="Morang", alternate_slugs={"ne": "biratnagarma-bhari-barsha"}),
        SITE,
    )
    assert meta.canonical == f"{SITE}/en/morang/heavy-rain-in-biratnagar"
    assert meta.hreflang == {
        "en": f"{SITE}/en/morang/heavy-rain-in-biratnagar",
        "ne": f"{SITE}/ne/morang/biratnagarma-bhari-barsha",
        "x-default": f"{SITE}/ne/morang/biratnagarma-bhari-barsha",
    }
    assert meta.json_ld[0]["inLanguage"] == "en"


def test_seo_title_passes_through_verbatim():
    custom = "Election results 2082: every Morang constituency, live and updated through the night"
    meta = build_seo(make_input(locale="en", seo_title=custom), SITE)
    assert meta.title == custom  # no truncation and no brand suffix
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/posts/test_workflow.py tests/seo/test_generator.py -v`
Expected: the workflow module fails on import (`NOT_FOUND_MARKER`). The three SEO tests pass already: they pin existing behaviour.

- [ ] **Step 3: Add the negative-cache constants**

In `backend/app/modules/public/service.py`, add below `CACHE_CONTROL`:

```python
NEGATIVE_TTL_SECONDS = 30
# Stored under a post key when the article does not exist. Every action that can make a slug
# public (publish, translation publish, slug change) deletes that post's keys, marker included.
NOT_FOUND_MARKER = "__404__"
```

- [ ] **Step 4: Cache public 404s**

In `backend/app/modules/public/router.py`, replace both `from app.modules.public.service import ...` lines (the original one and the one T2 added) with this single import:

```python
from app.modules.public.service import (
    CACHE_CONTROL,
    NEGATIVE_TTL_SECONDS,
    NOT_FOUND_MARKER,
    cache_get,
    cache_set,
    categories_cache_key,
    feed_generation,
    post_cache_key,
)
```

(`CACHE_TTL_SECONDS` is no longer imported here, and `RedisError` is no longer used in this file; remove both imports.) Then replace the whole `get_public_post` function with:

```python
def _post_not_found() -> AppError:
    return AppError(404, "POST_NOT_FOUND", "Post not found")


@router.get("/posts/{locale}/{slug}", response_model=PublicPostOut)
async def get_public_post(
    locale: str,
    slug: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> PublicPostOut:
    # An unknown locale is just a page that does not exist: same 404 as a missing slug.
    if locale not in SUPPORTED_LOCALES:
        raise _post_not_found()
    response.headers["Cache-Control"] = CACHE_CONTROL
    key = post_cache_key(locale, slug)
    cached = await cache_get(redis, key)
    if cached == NOT_FOUND_MARKER:
        raise _post_not_found()
    if cached:
        response.headers["X-Cache"] = "HIT"
        return PublicPostOut.model_validate_json(cached)

    row = (await session.execute(
        select(PostTranslation, Post)
        .join(Post, PostTranslation.post_id == Post.id)
        .where(
            PostTranslation.locale == locale,
            PostTranslation.slug == slug,
            PostTranslation.status == TranslationStatus.published,
            Post.status == PostStatus.published,
        )
    )).first()
    if row is None:
        await cache_set(redis, key, NOT_FOUND_MARKER, ttl=NEGATIVE_TTL_SECONDS)
        raise _post_not_found()
    tr, post = row
    category = await session.get(Category, post.category_id)
    author = await session.get(User, post.author_id)

    out = PublicPostOut(
        id=post.id,
        locale=tr.locale,
        title=tr.title,
        slug=tr.slug,
        content_html=tr.content_html,
        category_slug=category.slug,
        author_name=author.name,
        published_at=tr.published_at or post.published_at,
        updated_at=tr.updated_at,
        seo=tr.seo_auto,
        alternates={
            t.locale: t.slug
            for t in post.translations
            if t.locale != tr.locale and t.status == TranslationStatus.published
        },
    )
    await cache_set(redis, key, out.model_dump_json())
    response.headers["X-Cache"] = "MISS"
    return out
```

`logger` and `import logging` are now unused in `public/router.py`; remove them.

- [ ] **Step 5: Add the service transitions and the publish-date bump**

In `backend/app/modules/posts/schemas.py`, add:

```python
class SendBackIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
```

In `backend/app/modules/posts/service.py`:

1. Replace `publish_post` with:

```python
async def publish_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post:
    """Publish a draft or in-review post (editor+; the router enforces the role).

    Editors own publishing, so a draft does not need to be submitted first (decided in M2a part 2).
    Publishing publishes the translations that exist at this moment and bumps their updated_at,
    so dateModified is never earlier than datePublished.
    """
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status not in (PostStatus.draft, PostStatus.in_review):
        raise AppError(409, "INVALID_TRANSITION", f"Cannot publish a post that is {post.status.value}")
    now = utcnow()
    post.status = PostStatus.published
    post.published_at = post.published_at or now
    post.updated_at = now
    for tr in post.translations:  # only the translations that exist right now
        if tr.status != TranslationStatus.published:
            tr.status = TranslationStatus.published
            tr.published_at = now
            tr.updated_at = now
    session.add(_post_event("post.published", post))
    return await _save(session, post)
```

2. In `publish_translation`, add `tr.updated_at = now` directly after `tr.published_at = now`.

3. Add after `publish_translation`:

```python
async def send_back_post(session: AsyncSession, editor: User, post_id: uuid.UUID, note: str | None) -> Post:
    """in_review → draft, so the reporter can edit again. The note travels in the outbox payload."""
    post = await _get_post_for_update(session, post_id)
    if post.status != PostStatus.in_review:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot send back a post that is {post.status.value}")
    post.status = PostStatus.draft
    post.updated_at = utcnow()
    session.add(OutboxEvent(
        topic="post.sent_back",
        payload={
            "post_id": str(post.id),
            "author_id": str(post.author_id),
            "editor_id": str(editor.id),
            "note": (note or "").strip() or None,
        },
    ))
    return await _save(session, post)


async def unpublish_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post:
    """published → archived. Translations keep their status (unarchive is M2b)."""
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status != PostStatus.published:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot unpublish a post that is {post.status.value}")
    post.status = PostStatus.archived
    post.updated_at = utcnow()
    session.add(_post_event("post.unpublished", post))
    return await _save(session, post)
```

- [ ] **Step 6: Add the routes**

In `backend/app/modules/posts/router.py`, add `SendBackIn` to the `app.modules.posts.schemas` import and append:

```python
@router.post("/{post_id}/send-back", response_model=PostOut)
async def send_back_post(
    post_id: uuid.UUID,
    body: SendBackIn | None = None,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
) -> Post:
    return await service.send_back_post(session, user, post_id, body.note if body else None)


@router.post("/{post_id}/unpublish", response_model=PostOut)
async def unpublish_post(
    post_id: uuid.UUID,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.unpublish_post(session, post_id, if_match)
    await invalidate_public(redis, post)
    return post
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/posts tests/public tests/seo -v`
Expected: all PASS.

- [ ] **Step 8: Run the full suite**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add app/modules/posts app/modules/public tests/posts/test_workflow.py tests/seo/test_generator.py
git commit -m "feat(posts): send back, unpublish, publish bumps translation dates, cache public 404s

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
```

---

### Task 5: Card fields (excerpt, is_breaking, body_text) and public search

This task adds the fields the public cards need, plus full-text search:
- `posts.is_breaking`, set by editors through PATCH. On a published post the change counts as a public change: outbox `post.updated` and cache invalidation.
- `post_translations.excerpt`, editor-editable; empty means automatic.
- `post_translations.body_text`, plain text derived in Python on every content write.
- A generated `search_vector` column over title (weight A) and `body_text` (weight B), with a GIN index.
- `pg_trgm` and a trigram GIN index on the title.
- `GET /api/public/search`.

**Files:**
- Create: `backend/migrations/versions/6f8b0d2e4a53_cards_and_search.py`
- Modify: `backend/app/modules/posts/models.py`
- Modify: `backend/app/modules/posts/schemas.py` (`excerpt`, `is_breaking`)
- Modify: `backend/app/modules/posts/service.py` (`create_post`; `update_post` replaced in full)
- Create: `backend/app/modules/public/schemas.py` (`PublicCard`, `CardPage`)
- Create: `backend/app/modules/public/feeds.py` (card query and excerpt rule)
- Create: `backend/app/modules/public/search.py`
- Modify: `backend/app/modules/public/router.py` (`GET /api/public/search`, `_require_locale`)
- Modify: `backend/tests/conftest.py` (create `pg_trgm` before `create_all`)
- Modify: `backend/tests/db/test_migrations.py` (backfill test)
- Test: `backend/tests/posts/test_card_fields.py`, `backend/tests/public/test_search.py`

**Interfaces:**
- Consumes: `plain_text`, `truncate_words` from `app.modules.seo.generator`; `taxonomy_service.get_tags` (T3); `FEED_GEN_KEY` (T2); test helpers (T2).
- Produces:
  - `Post.is_breaking: bool`; `PostTranslation.excerpt: str | None`, `PostTranslation.body_text: str`, `PostTranslation.search_vector` (deferred, generated)
  - `posts.models.SEARCH_VECTOR_SQL: str`
  - `PostUpdate.excerpt: str | None` (≤ 300; `""` clears), `PostUpdate.is_breaking: bool | None` (editor+ only, else 403)
  - `TranslationOut.excerpt: str | None`, `PostOut.is_breaking: bool`
  - `UpdateResult.public_changed` is now also `True` when `is_breaking` changes on a published post
  - `public.schemas.PublicCard(id, title, slug, excerpt, category_slug, author_name, published_at, featured_image=None)`, `public.schemas.CardPage(items, total, limit, offset)`
  - `public.feeds.EXCERPT_LEN = 200`, `public.feeds.PUBLISHED_AT` (SQL expression), `public.feeds.card_excerpt(excerpt: str | None, body_text: str) -> str`, `public.feeds.card_query(locale: str) -> Select`, `public.feeds.to_card(row) -> PublicCard`
  - `public.search.search_posts(session, locale: str, q: str, *, limit: int, offset: int) -> tuple[list[PublicCard], int]`
  - `public.router._require_locale(locale: str) -> None` (404 `LOCALE_NOT_FOUND`)
  - Migration revision `6f8b0d2e4a53` (down: `5e7a9c1d3f42`)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/posts/test_card_fields.py`:

```python
from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.posts.models import PostTranslation
from app.modules.public.service import FEED_GEN_KEY
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, create_post_via_api, make_category, make_user, publish_via_api


async def test_body_text_is_plain_text_without_captions(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    content = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Rain & wind"}]},
        {"type": "image", "attrs": {"src": "https://cdn.mawapress.com/a.webp", "caption": "Photo: AP"}},
        {"type": "paragraph", "content": [{"type": "text", "text": "Roads closed"}]},
    ]}
    r = await client.post(
        "/api/posts",
        json={"locale": "en", "title": "Storm", "content_json": content, "category_id": cat.id},
        headers=auth_header(editor),
    )
    assert r.status_code == 201
    body_text = await session.scalar(select(PostTranslation.body_text).where(PostTranslation.slug == "storm"))
    assert body_text == "Rain & wind Roads closed"


async def test_excerpt_is_editable_and_empty_clears_it(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await create_post_via_api(client, editor, cat)
    assert post["translations"][0]["excerpt"] is None

    url = f"/api/posts/{post['id']}"
    set_ = await client.patch(
        url, json={"locale": "ne", "excerpt": "  छोटो सार  "}, headers=auth_if_match(editor, post["updated_at"])
    )
    assert set_.json()["translations"][0]["excerpt"] == "छोटो सार"
    cleared = await client.patch(url, json={"locale": "ne", "excerpt": ""}, headers=auth_if_match(editor, set_.json()["updated_at"]))
    assert cleared.json()["translations"][0]["excerpt"] is None
    too_long = await client.patch(
        url, json={"locale": "ne", "excerpt": "x" * 301}, headers=auth_if_match(editor, cleared.json()["updated_at"])
    )
    assert too_long.status_code == 422


async def test_only_editors_set_is_breaking(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await create_post_via_api(client, reporter, cat)
    assert post["is_breaking"] is False

    url = f"/api/posts/{post['id']}"
    denied = await client.patch(url, json={"locale": "ne", "is_breaking": True}, headers=auth_if_match(reporter, post["updated_at"]))
    assert denied.status_code == 403
    ok = await client.patch(url, json={"locale": "ne", "is_breaking": True}, headers=auth_if_match(editor, post["updated_at"]))
    assert ok.status_code == 200
    assert ok.json()["is_breaking"] is True
    # A draft is not public: no event.
    assert (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all() == []


async def test_is_breaking_on_live_post_is_a_public_change(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))
    gen = int(await fake_redis.get(FEED_GEN_KEY))

    r = await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "ne", "is_breaking": True}, headers=auth_if_match(editor, live["updated_at"])
    )
    assert r.status_code == 200
    assert len((await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()) == 1
    assert int(await fake_redis.get(FEED_GEN_KEY)) == gen + 1
```

Create `backend/tests/public/test_search.py`:

```python
from app.modules.users.models import Role
from tests.factories import auth_if_match, create_post_via_api, doc, make_category, make_user, publish_via_api


async def live_post(client, editor, cat, title, body, locale="en"):
    return await publish_via_api(client, editor, await create_post_via_api(client, editor, cat, title=title, body=body, locale=locale))


async def search(client, q, locale="en", **params):
    return await client.get("/api/public/search", params={"q": q, "locale": locale, **params})


async def test_search_ranks_title_matches_above_body_matches(client, session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    cat = await make_category(session)
    await live_post(client, editor, cat, "Market prices", "A flood of buyers at the haat")
    await live_post(client, editor, cat, "Flood relief in Biratnagar", "Water is rising")

    r = await search(client, "flood")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    body = r.json()
    assert body["total"] == 2
    assert [i["slug"] for i in body["items"]] == ["flood-relief-in-biratnagar", "market-prices"]
    first = body["items"][0]
    assert first["title"] == "Flood relief in Biratnagar"
    assert first["excerpt"] == "Water is rising"
    assert first["category_slug"] == "morang"
    assert first["author_name"] == "Sita Rai"
    assert first["published_at"] is not None
    assert first["featured_image"] is None


async def test_search_nepali_and_typo_tolerant_title(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await live_post(client, editor, cat, "बाढी पीडितलाई राहत", "विराटनगरमा राहत वितरण", locale="ne")
    await live_post(client, editor, cat, "Flood relief in Biratnagar", "Water is rising")

    ne = await search(client, "बाढी", locale="ne")
    assert [i["slug"] for i in ne.json()["items"]] == ["badhi-piditlai-rahat"]
    typo = await search(client, "biratnagr")  # no exact lexeme; trigram word similarity on the title
    assert [i["slug"] for i in typo.json()["items"]] == ["flood-relief-in-biratnagar"]


async def test_search_only_returns_public_translations_in_that_locale(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await create_post_via_api(client, editor, cat, title="Flood draft", body="flood", locale="en")  # never published
    live_ne = await live_post(client, editor, cat, "बाढी", "पानी", locale="ne")
    r = await client.patch(  # English translation added to a live post stays a draft
        f"/api/posts/{live_ne['id']}", json={"locale": "en", "title": "Flood warning", "content_json": doc("flood")},
        headers=auth_if_match(editor, live_ne["updated_at"]),
    )
    assert r.status_code == 200
    archived = await live_post(client, editor, cat, "Flood archive", "old flood")
    await client.post(f"/api/posts/{archived['id']}/unpublish", headers=auth_if_match(editor, archived["updated_at"]))

    assert (await search(client, "flood")).json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
    assert (await search(client, "बाढी", locale="ne")).json()["total"] == 1


async def test_search_paginates_with_total(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    for title in ("Flood one", "Flood two", "Flood three"):
        await live_post(client, editor, cat, title, "water")
    page1 = (await search(client, "flood", limit=2)).json()
    page2 = (await search(client, "flood", limit=2, offset=2)).json()
    assert (page1["total"], len(page1["items"]), page2["total"], len(page2["items"])) == (3, 2, 3, 1)
    assert not {i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]}


async def test_search_validates_q_and_locale(client, session):
    assert (await search(client, "a")).status_code == 422
    short = await search(client, "  a  ")
    assert short.status_code == 422
    assert short.json()["error"]["code"] == "QUERY_TOO_SHORT"
    assert (await search(client, "x" * 201)).status_code == 422
    bad_locale = await search(client, "flood", locale="fr")
    assert bad_locale.status_code == 404
    assert bad_locale.json()["error"]["code"] == "LOCALE_NOT_FOUND"


async def test_search_punctuation_and_operators_never_500(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await live_post(client, editor, cat, "Flood relief in Biratnagar", "Water is rising")
    for q in ("!!", "a & (b", "' OR 1=1 --", "flood:*", "\\\\", "<script>"):
        r = await search(client, q)
        assert r.status_code == 200, q
        assert isinstance(r.json()["items"], list)


async def test_card_excerpt_is_auto_until_an_editor_sets_one(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await live_post(client, editor, cat, "Flood relief", ("word " * 80).strip())

    auto = (await search(client, "flood")).json()["items"][0]["excerpt"]
    assert len(auto) <= 200 and auto.endswith("…")

    r = await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "en", "excerpt": "Custom summary"},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    assert r.status_code == 200
    assert (await search(client, "flood")).json()["items"][0]["excerpt"] == "Custom summary"
```

Append to `backend/tests/db/test_migrations.py`:

```python
async def test_upgrade_backfills_body_text_and_search_vector():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        env = {**os.environ, "MAWA_DATABASE_URL": url}
        before = _alembic(env, "upgrade", "5e7a9c1d3f42")
        assert before.returncode == 0, before.stderr

        eng = create_async_engine(url)
        try:
            async with eng.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO users (id, email, password_hash, name, role) "
                    "VALUES ('00000000-0000-0000-0000-000000000001', 'e@mawapress.com', 'x', 'E', 'editor')"
                ))
                await conn.execute(text("INSERT INTO categories (id, slug, name_ne, name_en) VALUES (1, 'morang', 'मोरङ', 'Morang')"))
                await conn.execute(text(
                    "INSERT INTO posts (id, author_id, category_id) VALUES "
                    "('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000001', 1)"
                ))
                await conn.execute(text(
                    "INSERT INTO post_translations (post_id, locale, title, slug, content_json, content_html) VALUES "
                    "('00000000-0000-0000-0000-0000000000a1', 'en', 'Storm', 'storm', '{}', "
                    "'<p>Rain &amp; wind</p><figure><img src=\"https://x/a.webp\"><figcaption>Photo</figcaption></figure>')"
                ))

            after = _alembic(env, "upgrade", "head")
            assert after.returncode == 0, after.stderr

            async with eng.begin() as conn:
                row = (await conn.execute(text(
                    "SELECT body_text, excerpt, search_vector @@ to_tsquery('simple', 'wind'), "
                    "search_vector @@ to_tsquery('simple', 'photo') FROM post_translations WHERE slug = 'storm'"
                ))).one()
                breaking = await conn.scalar(text("SELECT is_breaking FROM posts"))
        finally:
            await eng.dispose()

    assert tuple(row) == ("Rain & wind", None, True, False)
    assert breaking is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/posts/test_card_fields.py tests/public/test_search.py -v`
Expected: FAIL (`PostTranslation` has no `body_text`; `/api/public/search` is 404).

- [ ] **Step 3: Write the migration**

Create `backend/migrations/versions/6f8b0d2e4a53_cards_and_search.py`:

```python
"""card fields (is_breaking, excerpt, body_text) and full-text search

Revision ID: 6f8b0d2e4a53
Revises: 5e7a9c1d3f42
Create Date: 2026-10-17 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.modules.seo.generator import plain_text

# revision identifiers, used by Alembic.
revision: str = "6f8b0d2e4a53"
down_revision: Union[str, Sequence[str], None] = "5e7a9c1d3f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of posts.models.SEARCH_VECTOR_SQL as of this revision.
SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('simple'::regconfig, title), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, body_text), 'B')"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("posts", sa.Column("is_breaking", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("post_translations", sa.Column("excerpt", sa.String(length=300), nullable=True))
    op.add_column("post_translations", sa.Column("body_text", sa.Text(), nullable=False, server_default=sa.text("''")))

    # body_text is derived in Python (captions dropped, entities unescaped), so backfill row by row.
    bind = op.get_bind()
    for row_id, html in bind.execute(sa.text("SELECT id, content_html FROM post_translations")).all():
        bind.execute(
            sa.text("UPDATE post_translations SET body_text = :body WHERE id = :id"),
            {"body": plain_text(html), "id": row_id},
        )

    # pg_trgm is a trusted extension (PG 13+), so the database owner may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column(
        "post_translations",
        sa.Column("search_vector", postgresql.TSVECTOR(), sa.Computed(SEARCH_VECTOR_SQL, persisted=True), nullable=True),
    )
    op.create_index(
        "ix_post_translations_search_vector", "post_translations", ["search_vector"],
        unique=False, postgresql_using="gin",
    )
    op.create_index(
        "ix_post_translations_title_trgm", "post_translations", ["title"],
        unique=False, postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema.

    pg_trgm is deliberately left installed: other schemas or a DBA may rely on it, and
    upgrade() uses CREATE EXTENSION IF NOT EXISTS, so a downgrade/upgrade round trip is safe.
    """
    op.drop_index("ix_post_translations_title_trgm", table_name="post_translations")
    op.drop_index("ix_post_translations_search_vector", table_name="post_translations")
    op.drop_column("post_translations", "search_vector")
    op.drop_column("post_translations", "body_text")
    op.drop_column("post_translations", "excerpt")
    op.drop_column("posts", "is_breaking")
```

- [ ] **Step 4: Update the models and the test database bootstrap**

In `backend/app/modules/posts/models.py`:
1. Change the imports to:

```python
from sqlalchemy import (
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
```

2. Add above `class Post`:

```python
# Title outranks body. 'simple' (no stemming) works for both Nepali and English.
SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('simple'::regconfig, title), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, body_text), 'B')"
)
```

3. Add to `Post`, after `status`:

```python
    is_breaking: Mapped[bool] = mapped_column(default=False, server_default=false())
```

4. Replace `PostTranslation.__table_args__` with:

```python
    __table_args__ = (
        UniqueConstraint("locale", "slug", name="uq_translation_locale_slug"),
        UniqueConstraint("post_id", "locale", name="uq_translation_post_locale"),
        Index("ix_post_translations_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_post_translations_title_trgm", "title",
            postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )
```

5. Add to `PostTranslation`, after `seo_auto`:

```python
    excerpt: Mapped[str | None] = mapped_column(String(300))  # editor override; cards fall back to body_text
    body_text: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))  # plain text of content_html
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR_SQL, persisted=True), deferred=True
    )
```

In `backend/tests/conftest.py`, add `text` to the sqlalchemy import (`from sqlalchemy import text`) and create the extension before the tables (the trigram index needs it):

```python
@pytest_asyncio.fixture(scope="session")
async def engine(pg_url):
    eng = create_async_engine(pg_url)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()
```

- [ ] **Step 5: Extend the post schemas**

In `backend/app/modules/posts/schemas.py`:
1. Add to `PostUpdate`, after `tag_ids`:

```python
    excerpt: str | None = Field(default=None, max_length=300)  # "" clears the override
    is_breaking: bool | None = None  # editor+ only
```

2. Add to `TranslationOut`, after `seo_description`:

```python
    excerpt: str | None
```

3. Add to `PostOut`, after `status`:

```python
    is_breaking: bool
```

- [ ] **Step 6: Write `body_text` on every content write, and replace `update_post`**

In `backend/app/modules/posts/service.py`:
1. Add the import:

```python
from app.modules.seo.generator import plain_text
```

2. In `create_post`, after `content_html = render_html(data.content_json)`, add

```python
    body_text = plain_text(content_html)
```

and pass `body_text=body_text,` to the `PostTranslation(...)` constructor inside `assign()`, after `content_html=content_html,`.

3. Add above `class UpdateResult`:

```python
def _set_content(tr: PostTranslation, content_json: dict) -> None:
    tr.content_json = content_json
    tr.content_html = render_html(content_json)
    tr.body_text = plain_text(tr.content_html)
```

4. Replace `UpdateResult` and the whole `update_post` function with:

```python
class UpdateResult(NamedTuple):
    post: Post
    public_changed: bool  # True when readers can see the change (live translation edited, or breaking flag on a live post)


async def update_post(
    session: AsyncSession, user: User, post_id: uuid.UUID, if_match: str | None, data: PostUpdate
) -> UpdateResult:
    post = await _get_post_for_update(session, post_id)
    own_draft = post.author_id == user.id and post.status == PostStatus.draft
    if not (_is_editor(user) or own_draft):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot edit this post")
    if data.is_breaking is not None and not _is_editor(user):
        raise AppError(403, "FORBIDDEN_ROLE", "Only editors can mark breaking news")
    _check_version(post, if_match)
    # Validate before changing anything, so a 422 leaves the post untouched.
    tags = await taxonomy_service.get_tags(session, data.tag_ids) if data.tag_ids is not None else None

    now = utcnow()
    tr = next((t for t in post.translations if t.locale == data.locale), None)
    public_changed = False
    if tr is None:
        if data.title is None or data.content_json is None:
            raise AppError(422, "TRANSLATION_INCOMPLETE", "A new translation needs title and content_json")
        title, content_json = data.title, data.content_json
        content_html = render_html(content_json)
        new_tr: PostTranslation

        async def assign_new() -> None:
            nonlocal new_tr
            # Attached by post_id (not through post.translations) so a rolled-back attempt
            # leaves the post's collection untouched.
            new_tr = PostTranslation(
                post_id=post.id,
                locale=data.locale,
                title=title,
                slug=await unique_slug(session, data.locale, make_slug(title)),
                content_json=content_json,
                content_html=content_html,
                body_text=plain_text(content_html),
            )
            session.add(new_tr)

        post.updated_at = now
        await _flush_with_slug_retry(session, assign_new)
        tr = new_tr
        post.translations.append(tr)
    else:
        # Only an already-published translation of a live post is visible to readers.
        public_changed = post.status == PostStatus.published and tr.status == TranslationStatus.published
        changed = False
        retitle_draft = False
        if data.title is not None and data.title != tr.title:
            tr.title = data.title
            changed = True
            retitle_draft = tr.status != TranslationStatus.published
        if data.content_json is not None and data.content_json != tr.content_json:
            _set_content(tr, data.content_json)
            changed = True
        if changed:
            tr.updated_at = now
        post.updated_at = now
        await session.flush()
        if retitle_draft:
            tr_id, locale, title = tr.id, tr.locale, tr.title

            async def assign_retitle() -> None:
                tr.slug = await unique_slug(session, locale, make_slug(title), exclude_id=tr_id)

            await _flush_with_slug_retry(session, assign_retitle, refresh_on_conflict=[tr])

    meta_changed = False
    if "seo_title" in data.model_fields_set and (data.seo_title or None) != tr.seo_title:
        tr.seo_title = data.seo_title or None
        meta_changed = True
    if "seo_description" in data.model_fields_set and (data.seo_description or None) != tr.seo_description:
        tr.seo_description = data.seo_description or None
        meta_changed = True
    if "excerpt" in data.model_fields_set:
        excerpt = (data.excerpt or "").strip() or None
        if excerpt != tr.excerpt:
            tr.excerpt = excerpt
            meta_changed = True
    if meta_changed:
        tr.updated_at = now

    if data.is_breaking is not None and data.is_breaking != post.is_breaking:
        post.is_breaking = data.is_breaking
        if post.status == PostStatus.published:
            public_changed = True  # the home page's breaking strip changes
    if tags is not None:
        post.tags = tags
    post.updated_at = now

    if public_changed:
        session.add(_post_event("post.updated", post))
    return UpdateResult(await _save(session, post), public_changed)
```

The router already calls `invalidate_public` when `public_changed` is true (T2), so toggling `is_breaking` on a live post also clears the feeds.

- [ ] **Step 7: Write the card helpers, the search query and the endpoint**

Create `backend/app/modules/public/schemas.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel


class PublicCard(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    excerpt: str
    category_slug: str
    author_name: str
    published_at: datetime | None
    featured_image: str | None = None  # media and featured images arrive in M2b


class CardPage(BaseModel):
    items: list[PublicCard]
    total: int
    limit: int
    offset: int
```

Create `backend/app/modules/public/feeds.py`:

```python
"""Read-side queries for public cards. A card is a published translation of a published post."""

from sqlalchemy import Select, func, select

from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
from app.modules.public.schemas import PublicCard
from app.modules.seo.generator import truncate_words
from app.modules.taxonomy.models import Category
from app.modules.users.models import User

EXCERPT_LEN = 200
PUBLISHED_AT = func.coalesce(PostTranslation.published_at, Post.published_at)


def card_excerpt(excerpt: str | None, body_text: str) -> str:
    return excerpt or truncate_words(body_text, EXCERPT_LEN)


def card_query(locale: str) -> Select:
    return (
        select(
            Post.id,
            PostTranslation.title,
            PostTranslation.slug,
            PostTranslation.excerpt,
            # Twice the excerpt length is plenty to cut a word-boundary excerpt from.
            func.left(PostTranslation.body_text, 2 * EXCERPT_LEN).label("body_head"),
            Category.slug.label("category_slug"),
            User.name.label("author_name"),
            PUBLISHED_AT.label("published_at"),
        )
        .select_from(PostTranslation)
        .join(Post, Post.id == PostTranslation.post_id)
        .join(Category, Category.id == Post.category_id)
        .join(User, User.id == Post.author_id)
        .where(
            PostTranslation.locale == locale,
            PostTranslation.status == TranslationStatus.published,
            Post.status == PostStatus.published,
        )
    )


def to_card(row) -> PublicCard:
    return PublicCard(
        id=row.id,
        title=row.title,
        slug=row.slug,
        excerpt=card_excerpt(row.excerpt, row.body_head),
        category_slug=row.category_slug,
        author_name=row.author_name,
        published_at=row.published_at,
    )
```

Create `backend/app/modules/public/search.py`:

```python
from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.posts.models import Post, PostTranslation
from app.modules.public.feeds import PUBLISHED_AT, card_query, to_card
from app.modules.public.schemas import PublicCard

SIMPLE = literal_column("'simple'::regconfig")


async def search_posts(
    session: AsyncSession, locale: str, q: str, *, limit: int, offset: int
) -> tuple[list[PublicCard], int]:
    """Full-text match on title+body, or a fuzzy (trigram word-similarity) match on the title.

    websearch_to_tsquery never raises on user input; punctuation-only input becomes an empty
    query that matches nothing.
    """
    tsquery = func.websearch_to_tsquery(SIMPLE, q)
    match = or_(
        PostTranslation.search_vector.bool_op("@@")(tsquery),
        PostTranslation.title.bool_op("%>")(q),  # title %> q  ==  word_similarity(q, title) >= 0.6
    )
    rank = (func.ts_rank(PostTranslation.search_vector, tsquery) + func.word_similarity(q, PostTranslation.title)).label("rank")
    base = card_query(locale).where(match)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.add_columns(rank).order_by(rank.desc(), PUBLISHED_AT.desc(), Post.id.desc()).limit(limit).offset(offset)
    )
    return [to_card(row) for row in rows], total or 0
```

In `backend/app/modules/public/router.py`:
1. Change `from fastapi import APIRouter, Depends, Response` to `from fastapi import APIRouter, Depends, Query, Response` and add:

```python
from app.modules.public.schemas import CardPage
from app.modules.public.search import search_posts
```

2. Add below `_category_tree = ...`:

```python
def _require_locale(locale: str) -> None:
    # Public routes treat an unknown locale as a page that does not exist (M2a1 ruling).
    if locale not in SUPPORTED_LOCALES:
        raise AppError(404, "LOCALE_NOT_FOUND", "Unknown locale")
```

3. Append the route:

```python
@router.get("/search", response_model=CardPage)
async def public_search(
    response: Response,
    q: str = Query(max_length=200),
    locale: str = Query(),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> CardPage:
    _require_locale(locale)
    q = q.strip()
    if len(q) < 2:
        raise AppError(422, "QUERY_TOO_SHORT", "Search needs at least 2 characters")
    response.headers["Cache-Control"] = CACHE_CONTROL
    items, total = await search_posts(session, locale, q, limit=limit, offset=offset)
    return CardPage(items=items, total=total, limit=limit, offset=offset)
```

Search results are not stored in Redis: the key space is unbounded and Cloudflare caches the response for 60 s.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/posts tests/public tests/db -v`
Expected: all PASS, including `test_models_match_migrations` (the generated column and both GIN indexes match) and the round trip. Alembic may print a "Computed default ... cannot be modified" warning in the subprocess output when comparing the generated column. That is informational: it is not a diff and does not fail `alembic check`.

- [ ] **Step 9: Run the full suite**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add app/modules/posts app/modules/public migrations/versions/6f8b0d2e4a53_cards_and_search.py tests/conftest.py tests/db/test_migrations.py tests/posts/test_card_fields.py tests/public/test_search.py
git commit -m "feat(search): card fields, body_text, tsvector + pg_trgm search endpoint

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
```

---

### Task 6: Home and category feeds

This task adds the two feeds the M4 site renders:
- `GET /api/public/home?locale=` returns `{breaking: [cards], categories: [{category, posts: [latest 6 cards]}]}`, one block per top-level category that has posts, ordered by `sort`. A block includes posts from the category's children.
- `GET /api/public/category/{slug}?locale=&limit=&offset=` returns a paginated card list for the category and its descendants.

Both are cached in Redis under the feed generation counter, sent with the article `Cache-Control`, and invalidated by every public change. T2/T4/T5 already wired the invalidation; this task adds the readers and the tests that prove the wiring.

**Files:**
- Modify: `backend/app/modules/public/schemas.py` (`PublicCategory`, `HomeCategoryBlock`, `HomeOut`, `CategoryFeedOut`)
- Modify: `backend/app/modules/public/feeds.py` (`home_feed`, `category_feed`)
- Modify: `backend/app/modules/public/service.py` (`home_cache_key`, `category_feed_cache_key`)
- Modify: `backend/app/modules/public/router.py` (`_cached_feed` helper, two routes)
- Test: `backend/tests/public/test_feeds.py`

**Interfaces:**
- Consumes: `card_query`, `to_card`, `PUBLISHED_AT`, `PublicCard` (T5); `taxonomy.service.all_categories`, `descendant_ids` (T2); `feed_generation`, `cache_get`, `cache_set`, `CACHE_CONTROL` (T2); `_require_locale` (T5); test helpers (T2).
- Produces:
  - `public.feeds.HOME_BREAKING_LIMIT = 10`, `public.feeds.HOME_CATEGORY_POSTS = 6`
  - `public.feeds.home_feed(session, locale: str) -> HomeOut`
  - `public.feeds.category_feed(session, slug: str, locale: str, *, limit: int, offset: int) -> CategoryFeedOut` (404 `CATEGORY_NOT_FOUND`)
  - `public.service.home_cache_key(gen: str, locale: str) -> str`, `public.service.category_feed_cache_key(gen: str, slug: str, locale: str, limit: int, offset: int) -> str`
  - `public.schemas.PublicCategory(id, slug, name, seo_description)`; the name is in the requested locale

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/public/test_feeds.py`:

```python
from app.modules.users.models import Role
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    down_client,
    make_category,
    make_user,
    publish_via_api,
)


async def newsroom(session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    province = await make_category(session, slug="province-1", name_ne="प्रदेश १", name_en="Province 1", sort=1)
    morang = await make_category(session, slug="morang", parent_id=province.id)
    sports = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports", sort=2)
    await make_category(session, slug="weather", name_ne="मौसम", name_en="Weather", sort=3)  # stays empty
    return editor, province, morang, sports


async def live(client, editor, cat, title, locale="ne"):
    return await publish_via_api(client, editor, await create_post_via_api(client, editor, cat, title=title, locale=locale))


def slugs(cards):
    return [c["slug"] for c in cards]


async def test_home_groups_latest_posts_by_top_level_category(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, morang, "Alpha")
    await live(client, editor, province, "Bravo")
    await live(client, editor, sports, "Charlie")
    await create_post_via_api(client, editor, sports, title="Delta")  # draft: never on the home page

    r = await client.get("/api/public/home", params={"locale": "ne"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    body = r.json()
    assert body["breaking"] == []
    blocks = body["categories"]
    assert [b["category"]["slug"] for b in blocks] == ["province-1", "sports"]  # sorted; empty "weather" omitted
    assert blocks[0]["category"] == {"id": province.id, "slug": "province-1", "name": "प्रदेश १", "seo_description": None}
    assert slugs(blocks[0]["posts"]) == ["bravo", "alpha"]  # newest first, children included
    assert blocks[0]["posts"][1]["category_slug"] == "morang"
    assert slugs(blocks[1]["posts"]) == ["charlie"]
    card = blocks[1]["posts"][0]
    assert set(card) == {"id", "title", "slug", "excerpt", "category_slug", "author_name", "published_at", "featured_image"}
    assert card["author_name"] == "Sita Rai"


async def test_home_breaking_strip(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, morang, "Alpha")
    charlie = await live(client, editor, sports, "Charlie")
    r = await client.patch(
        f"/api/posts/{charlie['id']}", json={"locale": "ne", "is_breaking": True},
        headers=auth_if_match(editor, charlie["updated_at"]),
    )
    assert r.status_code == 200
    home = (await client.get("/api/public/home", params={"locale": "ne"})).json()
    assert slugs(home["breaking"]) == ["charlie"]


async def test_home_shows_latest_six_per_category(client, session):
    editor, province, morang, sports = await newsroom(session)
    for n in range(1, 8):
        await live(client, editor, sports, f"Sport {n}")
    home = (await client.get("/api/public/home", params={"locale": "ne"})).json()
    [block] = home["categories"]
    assert slugs(block["posts"]) == ["sport-7", "sport-6", "sport-5", "sport-4", "sport-3", "sport-2"]


async def test_home_cache_follows_public_changes_only(client, session):
    editor, province, morang, sports = await newsroom(session)
    alpha = await live(client, editor, morang, "Alpha")

    async def home():
        return await client.get("/api/public/home", params={"locale": "ne"})

    assert (await home()).headers["x-cache"] == "MISS"
    assert (await home()).headers["x-cache"] == "HIT"

    draft = await create_post_via_api(client, editor, sports, title="Bravo")
    edited = await client.patch(  # editing a draft is invisible to readers
        f"/api/posts/{draft['id']}", json={"locale": "ne", "title": "Bravo two"},
        headers=auth_if_match(editor, draft["updated_at"]),
    )
    assert (await home()).headers["x-cache"] == "HIT"

    await publish_via_api(client, editor, edited.json())
    after_publish = await home()
    assert after_publish.headers["x-cache"] == "MISS"
    assert [b["category"]["slug"] for b in after_publish.json()["categories"]] == ["province-1", "sports"]

    r = await client.post(f"/api/posts/{alpha['id']}/unpublish", headers=auth_if_match(editor, alpha["updated_at"]))
    assert r.status_code == 200
    after_unpublish = await home()
    assert after_unpublish.headers["x-cache"] == "MISS"
    assert [b["category"]["slug"] for b in after_unpublish.json()["categories"]] == ["sports"]


async def test_category_feed_includes_children_and_paginates(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, morang, "Alpha")
    await live(client, editor, province, "Bravo")
    await live(client, editor, sports, "Charlie")

    page1 = (await client.get("/api/public/category/province-1", params={"locale": "ne", "limit": 1})).json()
    assert page1["category"] == {"id": province.id, "slug": "province-1", "name": "प्रदेश १", "seo_description": None}
    assert (page1["total"], page1["limit"], page1["offset"], slugs(page1["items"])) == (2, 1, 0, ["bravo"])
    page2 = (await client.get("/api/public/category/province-1", params={"locale": "ne", "limit": 1, "offset": 1})).json()
    assert slugs(page2["items"]) == ["alpha"]

    child = (await client.get("/api/public/category/morang", params={"locale": "ne"})).json()
    assert (child["total"], slugs(child["items"])) == (1, ["alpha"])


async def test_category_feed_is_per_locale(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, morang, "Alpha")
    await live(client, editor, morang, "Flood in Biratnagar", locale="en")
    en = (await client.get("/api/public/category/province-1", params={"locale": "en"})).json()
    assert slugs(en["items"]) == ["flood-in-biratnagar"]
    assert en["category"]["name"] == "Province 1"


async def test_unknown_category_or_locale_is_404(client, session):
    await newsroom(session)
    missing = await client.get("/api/public/category/nope", params={"locale": "ne"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CATEGORY_NOT_FOUND"
    for url in ("/api/public/home", "/api/public/category/sports"):
        r = await client.get(url, params={"locale": "fr"})
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LOCALE_NOT_FOUND"


async def test_category_feed_cache_is_cleared_by_category_edit(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, sports, "Charlie")
    url, params = "/api/public/category/sports", {"locale": "en"}
    assert (await client.get(url, params=params)).headers["x-cache"] == "MISS"
    assert (await client.get(url, params=params)).headers["x-cache"] == "HIT"

    r = await client.patch(f"/api/categories/{sports.id}", json={"name_en": "Sport"}, headers=auth_header(editor))
    assert r.status_code == 200
    after = await client.get(url, params=params)
    assert after.headers["x-cache"] == "MISS"
    assert after.json()["category"]["name"] == "Sport"


async def test_feeds_survive_redis_outage(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, sports, "Charlie")
    async with await down_client(session) as down:
        home = await down.get("/api/public/home", params={"locale": "ne"})
        feed = await down.get("/api/public/category/sports", params={"locale": "ne"})
    assert home.status_code == 200 and home.headers["x-cache"] == "MISS"
    assert slugs(home.json()["categories"][0]["posts"]) == ["charlie"]
    assert feed.status_code == 200
    assert slugs(feed.json()["items"]) == ["charlie"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/public/test_feeds.py -v`
Expected: FAIL (`/api/public/home` and `/api/public/category/...` are 404).

- [ ] **Step 3: Add the response models**

Append to `backend/app/modules/public/schemas.py`:

```python
class PublicCategory(BaseModel):
    id: int
    slug: str
    name: str  # in the requested locale
    seo_description: str | None


class HomeCategoryBlock(BaseModel):
    category: PublicCategory
    posts: list[PublicCard]


class HomeOut(BaseModel):
    breaking: list[PublicCard]
    categories: list[HomeCategoryBlock]


class CategoryFeedOut(BaseModel):
    category: PublicCategory
    items: list[PublicCard]
    total: int
    limit: int
    offset: int
```

- [ ] **Step 4: Add the feed queries**

In `backend/app/modules/public/feeds.py`, change the imports to:

```python
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
from app.modules.public.schemas import CategoryFeedOut, HomeCategoryBlock, HomeOut, PublicCard, PublicCategory
from app.modules.seo.generator import truncate_words
from app.modules.taxonomy import service as taxonomy_service
from app.modules.taxonomy.models import Category
from app.modules.users.models import User
```

and append:

```python
HOME_BREAKING_LIMIT = 10
HOME_CATEGORY_POSTS = 6
NEWEST_FIRST = (PUBLISHED_AT.desc(), Post.id.desc())


def _public_category(cat: Category, locale: str) -> PublicCategory:
    return PublicCategory(
        id=cat.id,
        slug=cat.slug,
        name=cat.name_ne if locale == "ne" else cat.name_en,
        seo_description=cat.seo_description,
    )


async def _cards(session: AsyncSession, stmt: Select) -> list[PublicCard]:
    return [to_card(row) for row in await session.execute(stmt)]


async def home_feed(session: AsyncSession, locale: str) -> HomeOut:
    breaking = await _cards(
        session,
        card_query(locale).where(Post.is_breaking.is_(True)).order_by(*NEWEST_FIRST).limit(HOME_BREAKING_LIMIT),
    )
    cats = await taxonomy_service.all_categories(session)  # ordered by sort, id
    blocks: list[HomeCategoryBlock] = []
    # One small query per top-level category: a newsroom has about ten, and the result is cached.
    for root in (c for c in cats.values() if c.parent_id is None):
        ids = taxonomy_service.descendant_ids(cats, root.id)
        posts = await _cards(
            session,
            card_query(locale).where(Post.category_id.in_(ids)).order_by(*NEWEST_FIRST).limit(HOME_CATEGORY_POSTS),
        )
        if posts:
            blocks.append(HomeCategoryBlock(category=_public_category(root, locale), posts=posts))
    return HomeOut(breaking=breaking, categories=blocks)


async def category_feed(
    session: AsyncSession, slug: str, locale: str, *, limit: int, offset: int
) -> CategoryFeedOut:
    cats = await taxonomy_service.all_categories(session)
    cat = next((c for c in cats.values() if c.slug == slug), None)
    if cat is None:
        raise AppError(404, "CATEGORY_NOT_FOUND", "Category not found")
    base = card_query(locale).where(Post.category_id.in_(taxonomy_service.descendant_ids(cats, cat.id)))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    items = await _cards(session, base.order_by(*NEWEST_FIRST).limit(limit).offset(offset))
    return CategoryFeedOut(
        category=_public_category(cat, locale), items=items, total=total or 0, limit=limit, offset=offset
    )
```

- [ ] **Step 5: Add the cache keys**

In `backend/app/modules/public/service.py`, add below `categories_cache_key`:

```python
def home_cache_key(gen: str, locale: str) -> str:
    return f"public:home:{gen}:{locale}"


def category_feed_cache_key(gen: str, slug: str, locale: str, limit: int, offset: int) -> str:
    return f"public:category:{gen}:{slug}:{locale}:{limit}:{offset}"
```

- [ ] **Step 6: Add the routes**

In `backend/app/modules/public/router.py`:
1. Add the imports:

```python
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.modules.public.feeds import category_feed, home_feed
from app.modules.public.schemas import CategoryFeedOut, HomeOut
from app.modules.public.service import category_feed_cache_key, home_cache_key
```

2. Add below `_require_locale`:

```python
M = TypeVar("M", bound=BaseModel)


async def _cached_feed(
    response: Response,
    redis: Redis,
    make_key: Callable[[str], str],
    model: type[M],
    build: Callable[[], Awaitable[M]],
) -> M:
    """Serve a feed from Redis under the current feed generation, or build and store it."""
    response.headers["Cache-Control"] = CACHE_CONTROL
    gen = await feed_generation(redis)
    key = make_key(gen) if gen is not None else None
    cached = await cache_get(redis, key) if key else None
    if cached:
        response.headers["X-Cache"] = "HIT"
        return model.model_validate_json(cached)
    out = await build()
    if key:
        await cache_set(redis, key, out.model_dump_json())
    response.headers["X-Cache"] = "MISS"
    return out
```

3. Append the routes:

```python
@router.get("/home", response_model=HomeOut)
async def public_home(
    response: Response,
    locale: str = Query(),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> HomeOut:
    _require_locale(locale)
    return await _cached_feed(
        response, redis, lambda gen: home_cache_key(gen, locale), HomeOut, lambda: home_feed(session, locale)
    )


@router.get("/category/{slug}", response_model=CategoryFeedOut)
async def public_category(
    slug: str,
    response: Response,
    locale: str = Query(),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> CategoryFeedOut:
    _require_locale(locale)
    return await _cached_feed(
        response,
        redis,
        lambda gen: category_feed_cache_key(gen, slug, locale, limit, offset),
        CategoryFeedOut,
        lambda: category_feed(session, slug, locale, limit=limit, offset=offset),
    )
```

The feed invalidation points, all already in place from T2/T4/T5, are listed here so the reviewer can check them in one spot:
- `invalidate_public` runs on publish, translation publish, a PATCH with `public_changed` (a live translation edit or `is_breaking` on a live post), and unpublish.
- `invalidate_feeds` runs on category create, update and delete.
- T8 adds slug changes; they set `public_changed`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/public -v`
Expected: all PASS.

- [ ] **Step 8: Run the full suite**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add app/modules/public tests/public/test_feeds.py
git commit -m "feat(public): cached home and category feeds

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
```

---

### Task 7: Revisions and restore

Every save that actually changes a **published** translation stores that translation's prior state in `post_revisions`: title, slug, content_json, seo_title, seo_description, excerpt, editor_id and created_at. `editor_id` is the user whose save replaced that state. Edits to draft translations and no-op saves record nothing.
- `GET /api/posts/{id}/revisions` (the author or editor+) lists revisions newest first.
- `POST /api/posts/{id}/revisions/{rev_id}/restore` (editor+, If-Match) is a normal versioned save through `update_post`: it records its own revision and follows the `public_changed` rules. It does not restore the slug (see Decisions).

**Files:**
- Modify: `backend/app/modules/posts/models.py` (`PostRevision`)
- Modify: `backend/app/db/models.py` (register `PostRevision`)
- Create: `backend/migrations/versions/7a9c1e3f5b64_post_revisions.py`
- Modify: `backend/app/modules/posts/schemas.py` (`RevisionOut`)
- Modify: `backend/app/modules/posts/service.py` (`_snapshot`, recording in `update_post`, `list_revisions`, `restore_revision`)
- Modify: `backend/app/modules/posts/router.py` (two routes)
- Test: `backend/tests/posts/test_revisions.py`

**Interfaces:**
- Consumes: `update_post` and `UpdateResult` (T5 version); `invalidate_public` (T2); test helpers (T2).
- Produces:
  - `posts.models.PostRevision` (`id` bigint, `post_id`, `locale`, `title`, `slug`, `content_json`, `seo_title`, `seo_description`, `excerpt`, `editor_id`, `created_at`; index `ix_post_revisions_post_id_created_at`)
  - `posts.service.REVISION_FIELDS = ("title", "slug", "content_json", "seo_title", "seo_description", "excerpt")`
  - `posts.service.list_revisions(session, user: User, post_id: uuid.UUID, locale: str | None = None) -> list[PostRevision]`
  - `posts.service.restore_revision(session, user: User, post_id: uuid.UUID, rev_id: int, if_match: str | None) -> UpdateResult` (404 `REVISION_NOT_FOUND`)
  - `posts.schemas.RevisionOut`
  - Migration revision `7a9c1e3f5b64` (down: `6f8b0d2e4a53`)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/posts/test_revisions.py`:

```python
from sqlalchemy import func, select

from app.db.outbox import OutboxEvent
from app.modules.users.models import Role
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    doc,
    make_category,
    make_user,
    publish_via_api,
)


async def patch(client, user, post, **body):
    r = await client.patch(
        f"/api/posts/{post['id']}", json={"locale": "ne", **body}, headers=auth_if_match(user, post["updated_at"])
    )
    assert r.status_code == 200, r.text
    return r.json()


async def revisions(client, user, post):
    return await client.get(f"/api/posts/{post['id']}/revisions", headers=auth_header(user))


async def live_post(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    return editor, await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))


async def test_editing_a_published_translation_records_its_prior_state(client, session):
    editor, live = await live_post(client, session)
    await patch(client, editor, live, title="विराटनगरमा बाढी", seo_title="Custom")

    r = await revisions(client, editor, live)
    assert r.status_code == 200
    [rev] = r.json()
    assert (rev["locale"], rev["title"], rev["slug"]) == ("ne", "बाढी समाचार", "badhi-samachar")
    assert rev["content_json"] == doc("पानी परिरहेको छ")
    assert (rev["seo_title"], rev["seo_description"], rev["excerpt"]) == (None, None, None)
    assert rev["editor_id"] == str(editor.id)
    assert rev["created_at"]


async def test_no_revision_for_drafts_or_no_op_saves(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    draft = await create_post_via_api(client, editor, cat)
    draft = await patch(client, editor, draft, title="मस्यौदा")  # draft edit
    live = await publish_via_api(client, editor, draft)
    live = await patch(client, editor, live, title="मस्यौदा")  # same title: nothing changed
    with_en = await patch(client, editor, live, locale="en", title="Draft English", content_json=doc("x"))
    await patch(client, editor, with_en, locale="en", title="Draft English 2")  # draft translation edit
    assert (await revisions(client, editor, live)).json() == []


async def test_revisions_newest_first_and_visible_to_author_and_editors(client, session):
    reporter = await make_user(session)
    other = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish_via_api(client, editor, await create_post_via_api(client, reporter, cat))
    first = await patch(client, editor, live, title="पहिलो सम्पादन")
    await patch(client, editor, first, title="दोस्रो सम्पादन")

    r = await revisions(client, reporter, live)
    assert r.status_code == 200
    assert [rev["title"] for rev in r.json()] == ["पहिलो सम्पादन", "बाढी समाचार"]
    assert (await revisions(client, other, live)).status_code == 403
    only_en = await client.get(f"/api/posts/{live['id']}/revisions", params={"locale": "en"}, headers=auth_header(editor))
    assert only_en.json() == []


async def test_restore_is_a_versioned_save(client, session):
    editor, live = await live_post(client, session)
    edited = await patch(client, editor, live, title="गलत शीर्षक", content_json=doc("गलत"))
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).json()["title"] == "गलत शीर्षक"  # warm cache
    [rev] = (await revisions(client, editor, live)).json()

    r = await client.post(
        f"/api/posts/{live['id']}/revisions/{rev['id']}/restore", headers=auth_if_match(editor, edited["updated_at"])
    )
    assert r.status_code == 200
    tr = r.json()["translations"][0]
    assert (tr["title"], tr["slug"], tr["content_html"]) == ("बाढी समाचार", "badhi-samachar", "<p>पानी परिरहेको छ</p>")
    assert r.json()["updated_at"] != edited["updated_at"]

    # The restore recorded the state it replaced, emitted post.updated and cleared the public cache.
    assert [x["title"] for x in (await revisions(client, editor, live)).json()] == ["गलत शीर्षक", "बाढी समाचार"]
    updates = await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.topic == "post.updated"))
    assert updates == 2
    public = await client.get("/api/public/posts/ne/badhi-samachar")
    assert public.headers["x-cache"] == "MISS"
    assert public.json()["title"] == "बाढी समाचार"


async def test_restore_guards(client, session):
    reporter = await make_user(session)
    editor, live = await live_post(client, session)
    edited = await patch(client, editor, live, title="नयाँ")
    [rev] = (await revisions(client, editor, live)).json()
    url = f"/api/posts/{live['id']}/revisions/{rev['id']}/restore"

    assert (await client.post(url, headers=auth_header(editor))).status_code == 428
    assert (await client.post(url, headers=auth_if_match(editor, live["updated_at"]))).status_code == 412
    assert (await client.post(url, headers=auth_if_match(reporter, edited["updated_at"]))).status_code == 403

    other = await publish_via_api(
        client, editor, await create_post_via_api(client, editor, await make_category(session, slug="sports"), title="अर्को")
    )
    wrong_post = await client.post(
        f"/api/posts/{other['id']}/revisions/{rev['id']}/restore", headers=auth_if_match(editor, other["updated_at"])
    )
    assert wrong_post.status_code == 404
    assert wrong_post.json()["error"]["code"] == "REVISION_NOT_FOUND"
    missing = await client.post(
        f"/api/posts/{live['id']}/revisions/999999/restore", headers=auth_if_match(editor, edited["updated_at"])
    )
    assert missing.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/posts/test_revisions.py -v`
Expected: FAIL (`/revisions` routes are 404/405).

- [ ] **Step 3: Add the model, register it, and write the migration**

In `backend/app/modules/posts/models.py`, add `BigInteger` to the `sqlalchemy` import and append:

```python
class PostRevision(Base):
    """Prior state of a published translation, saved before an edit replaced it."""

    __tablename__ = "post_revisions"
    __table_args__ = (Index("ix_post_revisions_post_id_created_at", "post_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(String(2))
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(100))
    content_json: Mapped[dict] = mapped_column(JSONB)
    seo_title: Mapped[str | None] = mapped_column(String(120))
    seo_description: Mapped[str | None] = mapped_column(String(320))
    excerpt: Mapped[str | None] = mapped_column(String(300))
    editor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))  # whose save replaced this state
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
```

In `backend/app/db/models.py`, change the posts import to `from app.modules.posts.models import Post, PostRevision, PostTranslation` and add `"PostRevision"` to `__all__`.

Create `backend/migrations/versions/7a9c1e3f5b64_post_revisions.py`:

```python
"""post_revisions

Revision ID: 7a9c1e3f5b64
Revises: 6f8b0d2e4a53
Create Date: 2026-10-17 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7a9c1e3f5b64"
down_revision: Union[str, Sequence[str], None] = "6f8b0d2e4a53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "post_revisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=2), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("seo_title", sa.String(length=120), nullable=True),
        sa.Column("seo_description", sa.String(length=320), nullable=True),
        sa.Column("excerpt", sa.String(length=300), nullable=True),
        sa.Column("editor_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["editor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_post_revisions_post_id_created_at", "post_revisions", ["post_id", "created_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_post_revisions_post_id_created_at", table_name="post_revisions")
    op.drop_table("post_revisions")
```

- [ ] **Step 4: Add the response schema**

Append to `backend/app/modules/posts/schemas.py`:

```python
class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    locale: str
    title: str
    slug: str
    content_json: dict
    seo_title: str | None
    seo_description: str | None
    excerpt: str | None
    editor_id: uuid.UUID
    created_at: datetime
```

- [ ] **Step 5: Record revisions in `update_post` and add list/restore**

In `backend/app/modules/posts/service.py`:
1. Import `PostRevision`:

```python
from app.modules.posts.models import Post, PostRevision, PostStatus, PostTranslation, TranslationStatus
```

2. Add above `class UpdateResult`:

```python
REVISION_FIELDS = ("title", "slug", "content_json", "seo_title", "seo_description", "excerpt")


def _snapshot(tr: PostTranslation) -> dict:
    return {field: getattr(tr, field) for field in REVISION_FIELDS}
```

3. In `update_post`, directly after the line `public_changed = False` (the one right after `tr = next(...)`), add:

```python
    # Readers have seen a published translation, so keep its current state before changing it.
    before = _snapshot(tr) if tr is not None and tr.status == TranslationStatus.published else None
```

4. In `update_post`, directly before the final `if public_changed:` block, add:

```python
    if before is not None and _snapshot(tr) != before:
        session.add(PostRevision(post_id=post.id, locale=tr.locale, editor_id=user.id, **before))
```

5. Append:

```python
async def list_revisions(
    session: AsyncSession, user: User, post_id: uuid.UUID, locale: str | None = None
) -> list[PostRevision]:
    post = await get_post(session, post_id)
    if post.author_id != user.id and not _is_editor(user):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot view this post's revisions")
    stmt = select(PostRevision).where(PostRevision.post_id == post_id)
    if locale is not None:
        stmt = stmt.where(PostRevision.locale == locale)
    stmt = stmt.order_by(PostRevision.created_at.desc(), PostRevision.id.desc())
    return list((await session.scalars(stmt)).all())


async def restore_revision(
    session: AsyncSession, user: User, post_id: uuid.UUID, rev_id: int, if_match: str | None
) -> UpdateResult:
    """Write a revision's content back as an ordinary versioned save.

    update_post records the state being replaced as a new revision and emits post.updated if the
    translation is live. The slug is not restored: it changes only through the explicit slug field,
    which also writes redirects.
    """
    rev = await session.get(PostRevision, rev_id)
    if rev is None or rev.post_id != post_id:
        raise AppError(404, "REVISION_NOT_FOUND", "Revision not found")
    data = PostUpdate(
        locale=rev.locale,
        title=rev.title,
        content_json=rev.content_json,
        seo_title=rev.seo_title or "",
        seo_description=rev.seo_description or "",
        excerpt=rev.excerpt or "",
    )
    return await update_post(session, user, post_id, if_match, data)
```

- [ ] **Step 6: Add the routes**

In `backend/app/modules/posts/router.py`, add `RevisionOut` to the schemas import and append:

```python
@router.get("/{post_id}/revisions", response_model=list[RevisionOut])
async def list_revisions(
    post_id: uuid.UUID,
    locale: Locale | None = None,
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_revisions(session, user, post_id, locale)


@router.post("/{post_id}/revisions/{rev_id}/restore", response_model=PostOut)
async def restore_revision(
    post_id: uuid.UUID,
    rev_id: int,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post, public_changed = await service.restore_revision(session, user, post_id, rev_id, if_match)
    if public_changed:
        await invalidate_public(redis, post)
    return post
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/posts tests/db -v`
Expected: all PASS.

- [ ] **Step 8: Run the full suite**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add app/modules/posts app/db/models.py migrations/versions/7a9c1e3f5b64_post_revisions.py tests/posts/test_revisions.py
git commit -m "feat(posts): revisions of published translations and versioned restore

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
```

---

### Task 8: Explicit slug change, 301 redirects and redirect resolution

Editors may change a **published** translation's slug through an explicit `slug` field on `PATCH /api/posts/{id}`. The value must pass `is_valid_slug` (≤ 80), be unique per locale, and is never auto-suffixed: a clash is 409. The old public path `/{locale}/{category}/{old_slug}` gets a 301 row in `redirects`:
- Chains collapse: A→B then B→C rewrites A→C.
- A path that becomes live again loses its outgoing redirect, so there is never a self-redirect.

`GET /api/public/redirects/resolve?path=` returns `{to_path, code}` or 404. It is Redis-cached, including 404s, degrades on `RedisError`, and is invalidated for every path a change touches. Changing a category slug is out of scope; category slugs are immutable since T2.

**Files:**
- Create: `backend/app/modules/seo/models.py` (`Redirect`), `backend/app/modules/seo/service.py`
- Modify: `backend/app/db/models.py` (register `Redirect`)
- Create: `backend/migrations/versions/8b0d2f4a6c75_redirects.py`
- Modify: `backend/app/modules/posts/schemas.py` (`PostUpdate.slug`)
- Modify: `backend/app/modules/posts/service.py` (`UpdateResult.slug_change`, `_requested_slug`, slug branch in `update_post`)
- Modify: `backend/app/modules/posts/router.py` (`update_post` and `restore_revision` use `UpdateResult` fields)
- Modify: `backend/app/modules/public/service.py` (`redirect_cache_key`, `invalidate_slug_change`)
- Modify: `backend/app/modules/public/router.py` (`GET /api/public/redirects/resolve`)
- Test: `backend/tests/seo/test_redirects.py`

**Interfaces:**
- Consumes: `is_valid_slug` (T2); `_slug_taken`, `_is_slug_conflict`, `_post_event`, `update_post` (T5/T7 version); `REVISION_FIELDS` (T7, already contains `slug`); `cache_get`, `cache_set`, `NOT_FOUND_MARKER`, `CACHE_CONTROL`, `CACHE_TTL_SECONDS` (T2/T4); test helpers (T2).
- Produces:
  - `seo.models.Redirect(from_path PK str ≤300, to_path str ≤300 indexed, code smallint default 301, created_at)`
  - `seo.service.article_path(locale: str, category_slug: str, slug: str) -> str`
  - `seo.service.record_slug_change(session, old_path: str, new_path: str) -> list[str]` (sorted paths whose resolution changed)
  - `seo.service.resolve_redirect(session, path: str) -> Redirect | None`
  - `seo.service.SlugChange(locale: str, old_slug: str, redirect_paths: list[str])`
  - `posts.service.UpdateResult(post, public_changed, slug_change: SlugChange | None = None)`
  - `PostUpdate.slug: str | None` (≤ 80; editor+; published translations only)
  - `public.service.redirect_cache_key(path: str) -> str`, `public.service.invalidate_slug_change(redis, change: SlugChange) -> None`
  - Error codes: 403 `FORBIDDEN_ROLE`, 422 `SLUG_NOT_EDITABLE`, 422 `INVALID_SLUG`, 409 `SLUG_TAKEN`, 404 `REDIRECT_NOT_FOUND`, 422 `INVALID_PATH`
  - Migration revision `8b0d2f4a6c75` (down: `7a9c1e3f5b64`)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/seo/test_redirects.py`:

```python
from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.public.service import NOT_FOUND_MARKER, post_cache_key, redirect_cache_key
from app.modules.seo.models import Redirect
from app.modules.users.models import Role
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    down_client,
    make_category,
    make_user,
    publish_via_api,
)

OLD = "/ne/morang/badhi-samachar"


async def live_post(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    return editor, cat, await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))


async def change_slug(client, user, post, slug, locale="ne"):
    return await client.patch(
        f"/api/posts/{post['id']}", json={"locale": locale, "slug": slug}, headers=auth_if_match(user, post["updated_at"])
    )


async def redirect_rows(session):
    rows = (await session.scalars(select(Redirect).order_by(Redirect.from_path))).all()
    return [(r.from_path, r.to_path, r.code) for r in rows]


async def resolve(client, path):
    return await client.get("/api/public/redirects/resolve", params={"path": path})


async def test_slug_change_moves_the_article_and_writes_a_301(client, session):
    editor, cat, live = await live_post(client, session)
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 200  # warm cache

    r = await change_slug(client, editor, live, "flood-news")
    assert r.status_code == 200
    tr = r.json()["translations"][0]
    assert tr["slug"] == "flood-news"
    assert tr["seo_auto"]["canonical"].endswith("/ne/morang/flood-news")
    assert await redirect_rows(session) == [(OLD, "/ne/morang/flood-news", 301)]

    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 404
    assert (await client.get("/api/public/posts/ne/flood-news")).status_code == 200

    [event] = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()
    assert event.payload["slugs"] == {"ne": "flood-news"}
    assert event.payload["redirect"] == {"from": OLD, "to": "/ne/morang/flood-news"}

    [rev] = (await client.get(f"/api/posts/{live['id']}/revisions", headers=auth_header(editor))).json()
    assert rev["slug"] == "badhi-samachar"


async def test_redirect_chains_collapse(client, session):
    editor, cat, live = await live_post(client, session)
    b = (await change_slug(client, editor, live, "flood-news")).json()
    c = await change_slug(client, editor, b, "flood-update")
    assert c.status_code == 200
    assert await redirect_rows(session) == [
        (OLD, "/ne/morang/flood-update", 301),
        ("/ne/morang/flood-news", "/ne/morang/flood-update", 301),
    ]


async def test_slug_change_back_never_leaves_a_self_redirect(client, session):
    editor, cat, live = await live_post(client, session)
    b = (await change_slug(client, editor, live, "flood-news")).json()
    back = await change_slug(client, editor, b, "badhi-samachar")
    assert back.status_code == 200
    assert await redirect_rows(session) == [("/ne/morang/flood-news", OLD, 301)]
    assert (await resolve(client, OLD)).status_code == 404  # the article itself lives there again


async def test_same_slug_is_a_no_op(client, session):
    editor, cat, live = await live_post(client, session)
    r = await change_slug(client, editor, live, "badhi-samachar")
    assert r.status_code == 200
    assert await redirect_rows(session) == []


async def test_slug_change_guards(client, session):
    reporter = await make_user(session)
    editor, cat, live = await live_post(client, session)
    other = await publish_via_api(client, editor, await create_post_via_api(client, editor, cat, title="Flood news"))
    assert other["translations"][0]["slug"] == "flood-news"

    taken = await change_slug(client, editor, live, "flood-news")
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "SLUG_TAKEN"
    for bad in ("Flood News", "flood--news", "बाढी"):
        r = await change_slug(client, editor, live, bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "INVALID_SLUG"
    assert (await change_slug(client, editor, live, "a" * 81)).status_code == 422

    own_draft = await create_post_via_api(client, reporter, cat, title="Reporter draft")
    denied = await change_slug(client, reporter, own_draft, "my-slug")
    assert denied.status_code == 403
    draft_slug = await change_slug(client, editor, own_draft, "my-slug")
    assert draft_slug.status_code == 422
    assert draft_slug.json()["error"]["code"] == "SLUG_NOT_EDITABLE"
    assert await redirect_rows(session) == []


async def test_resolve_returns_target_and_is_cached(client, session, fake_redis):
    editor, cat, live = await live_post(client, session)
    b = (await change_slug(client, editor, live, "flood-news")).json()

    first = await resolve(client, OLD)
    assert first.status_code == 200
    assert first.json() == {"to_path": "/ne/morang/flood-news", "code": 301}
    assert first.headers["x-cache"] == "MISS"
    assert first.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    assert (await resolve(client, OLD)).headers["x-cache"] == "HIT"

    await change_slug(client, editor, b, "flood-update")  # repoints OLD, so its cached answer must go
    assert (await resolve(client, OLD)).json() == {"to_path": "/ne/morang/flood-update", "code": 301}


async def test_resolve_404_is_cached_then_cleared_when_a_redirect_appears(client, session, fake_redis):
    editor, cat, live = await live_post(client, session)
    missing = await resolve(client, OLD)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "REDIRECT_NOT_FOUND"
    assert await fake_redis.get(redirect_cache_key(OLD)) == NOT_FOUND_MARKER

    await change_slug(client, editor, live, "flood-news")
    assert await fake_redis.get(redirect_cache_key(OLD)) is None
    assert await fake_redis.get(post_cache_key("ne", "badhi-samachar")) is None
    assert (await resolve(client, OLD)).status_code == 200


async def test_resolve_validates_path(client):
    bad = await resolve(client, "ne/morang/x")
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_PATH"
    assert (await resolve(client, "/" + "a" * 300)).status_code == 422


async def test_resolve_survives_redis_outage(client, session):
    editor, cat, live = await live_post(client, session)
    await change_slug(client, editor, live, "flood-news")
    async with await down_client(session) as down:
        r = await down.get("/api/public/redirects/resolve", params={"path": OLD})
    assert r.status_code == 200
    assert r.json()["to_path"] == "/ne/morang/flood-news"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/seo/test_redirects.py -v`
Expected: FAIL (`app.modules.seo.models` does not exist).

- [ ] **Step 3: Add the model, register it, and write the migration**

Create `backend/app/modules/seo/models.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Redirect(Base):
    __tablename__ = "redirects"

    from_path: Mapped[str] = mapped_column(String(300), primary_key=True)
    to_path: Mapped[str] = mapped_column(String(300), index=True)  # indexed for chain collapsing
    code: Mapped[int] = mapped_column(SmallInteger, default=301, server_default=text("301"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
```

In `backend/app/db/models.py`, add `from app.modules.seo.models import Redirect` and add `"Redirect"` to `__all__`.

Create `backend/migrations/versions/8b0d2f4a6c75_redirects.py`:

```python
"""redirects

Revision ID: 8b0d2f4a6c75
Revises: 7a9c1e3f5b64
Create Date: 2026-10-17 15:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8b0d2f4a6c75"
down_revision: Union[str, Sequence[str], None] = "7a9c1e3f5b64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "redirects",
        sa.Column("from_path", sa.String(length=300), nullable=False),
        sa.Column("to_path", sa.String(length=300), nullable=False),
        sa.Column("code", sa.SmallInteger(), nullable=False, server_default=sa.text("301")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("from_path"),
    )
    op.create_index(op.f("ix_redirects_to_path"), "redirects", ["to_path"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_redirects_to_path"), table_name="redirects")
    op.drop_table("redirects")
```

- [ ] **Step 4: Write the redirect service**

Create `backend/app/modules/seo/service.py`:

```python
from typing import NamedTuple

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.seo.models import Redirect

PERMANENT = 301


class SlugChange(NamedTuple):
    locale: str
    old_slug: str
    redirect_paths: list[str]  # every path whose redirect resolution changed


def article_path(locale: str, category_slug: str, slug: str) -> str:
    """Public article path; the canonical URL is site_url + this (spec §7)."""
    return f"/{locale}/{category_slug}/{slug}"


async def record_slug_change(session: AsyncSession, old_path: str, new_path: str) -> list[str]:
    """Point old_path at new_path with a 301, collapsing chains. Returns the affected from_paths.

    1. new_path is a live article now, so any redirect *from* it would shadow it: delete it.
       This is also what prevents a self-redirect when a slug goes back to an earlier value.
    2. Every redirect that pointed at old_path now points straight at new_path (A→B, B→C ⇒ A→C).
    3. Upsert old_path → new_path. An older row from old_path can exist when another article later
       took that slug; the newest move wins.
    """
    if old_path == new_path:
        return []
    await session.execute(delete(Redirect).where(Redirect.from_path == new_path))
    repointed = (await session.scalars(
        update(Redirect).where(Redirect.to_path == old_path).values(to_path=new_path).returning(Redirect.from_path)
    )).all()
    await session.execute(
        pg_insert(Redirect)
        .values(from_path=old_path, to_path=new_path, code=PERMANENT)
        .on_conflict_do_update(index_elements=[Redirect.from_path], set_={"to_path": new_path, "code": PERMANENT})
    )
    return sorted({old_path, new_path, *repointed})


async def resolve_redirect(session: AsyncSession, path: str) -> Redirect | None:
    return await session.get(Redirect, path)
```

Because a live article always wins over a redirect (spec §9: 404s check `redirects`), `unique_slug` does not need to avoid redirect sources.

- [ ] **Step 5: Add `slug` to `PostUpdate`**

In `backend/app/modules/posts/schemas.py`, add to `PostUpdate`, after `is_breaking`:

```python
    slug: str | None = Field(default=None, max_length=80)  # editor+, published translations only; writes a 301
```

- [ ] **Step 6: Handle the slug in `update_post`**

In `backend/app/modules/posts/service.py`:
1. Add the imports:

```python
from app.modules.seo import service as seo_service
from app.modules.seo.service import SlugChange
from app.modules.seo.slug import is_valid_slug, make_slug
```

(the second replaces the existing `from app.modules.seo.slug import make_slug`).

2. Replace `class UpdateResult` with:

```python
class UpdateResult(NamedTuple):
    post: Post
    public_changed: bool  # True when readers can see the change (live translation edited, or breaking flag on a live post)
    slug_change: SlugChange | None = None  # set when an explicit slug change wrote a redirect
```

3. Add below `UpdateResult`:

```python
def _requested_slug(user: User, tr: PostTranslation | None, slug: str) -> str | None:
    """Validate an explicit slug change before anything is modified. None means 'no change'."""
    if tr is not None and slug == tr.slug:
        return None
    if not _is_editor(user):
        raise AppError(403, "FORBIDDEN_ROLE", "Only editors can change a slug")
    if tr is None or tr.status != TranslationStatus.published:
        raise AppError(422, "SLUG_NOT_EDITABLE", "Only a published translation's slug can be changed; a draft's slug follows its title")
    if not is_valid_slug(slug):
        raise AppError(422, "INVALID_SLUG", "Slug must be lower-case letters, digits and single hyphens, at most 80 chars")
    return slug
```

4. In `update_post`, replace the lines

```python
    now = utcnow()
    tr = next((t for t in post.translations if t.locale == data.locale), None)
```

with

```python
    tr = next((t for t in post.translations if t.locale == data.locale), None)
    new_slug = _requested_slug(user, tr, data.slug) if data.slug is not None else None
    if new_slug is not None and await _slug_taken(session, tr.locale, new_slug, tr.id):
        raise AppError(409, "SLUG_TAKEN", "That slug is already used by another article in this language")

    now = utcnow()
```

5. In `update_post`, directly after the `if meta_changed: tr.updated_at = now` block and before the `if data.is_breaking ...` block, add:

```python
    slug_change: SlugChange | None = None
    redirect: dict[str, str] | None = None
    if new_slug is not None:
        category = await session.get(Category, post.category_id)
        old_slug = tr.slug
        old_path = seo_service.article_path(tr.locale, category.slug, old_slug)
        new_path = seo_service.article_path(tr.locale, category.slug, new_slug)
        try:
            async with session.begin_nested():  # a concurrent save can still take the slug
                tr.slug = new_slug
                await session.flush()
        except IntegrityError as exc:
            if not _is_slug_conflict(exc):
                raise
            raise AppError(409, "SLUG_TAKEN", "That slug is already used by another article in this language") from exc
        tr.updated_at = now
        paths = await seo_service.record_slug_change(session, old_path, new_path)
        slug_change = SlugChange(tr.locale, old_slug, paths)
        redirect = {"from": old_path, "to": new_path}
```

6. Replace the final block of `update_post`

```python
    if public_changed:
        session.add(_post_event("post.updated", post))
    return UpdateResult(await _save(session, post), public_changed)
```

with

```python
    if public_changed:
        event = _post_event("post.updated", post)
        if redirect is not None:
            event.payload = {**event.payload, "redirect": redirect}  # lets the worker purge the old URL
        session.add(event)
    return UpdateResult(await _save(session, post), public_changed, slug_change)
```

A slug can only change on a published translation, so on a published post `public_changed` is already `True`. The revision recorded by T7's snapshot includes the old slug, because `slug` is in `REVISION_FIELDS`. `_refresh_all_seo` (inside `_save`) recomputes the canonical URL and the siblings' hreflang from the new slug.

- [ ] **Step 7: Add redirect cache helpers and the resolve endpoint, and update the post routes**

In `backend/app/modules/public/service.py`, add the import and functions:

```python
from app.modules.seo.service import SlugChange
```

```python
def redirect_cache_key(path: str) -> str:
    return f"public:redirect:{path}"


async def invalidate_slug_change(redis: Redis, change: SlugChange) -> None:
    """Drop the old article key and every redirect answer the change touched (404 markers included)."""
    keys = [post_cache_key(change.locale, change.old_slug), *(redirect_cache_key(p) for p in change.redirect_paths)]
    try:
        await redis.delete(*keys)
    except RedisError:
        logger.warning("Cache invalidation failed; stale entries expire via TTL", exc_info=True)
```

In `backend/app/modules/posts/router.py`, import `invalidate_slug_change` next to `invalidate_public`:

```python
from app.modules.public.service import invalidate_public, invalidate_slug_change
```

and replace the bodies of `update_post` and `restore_revision` (a three-field `UpdateResult` can no longer be unpacked into two names):

```python
    result = await service.update_post(session, user, post_id, if_match, body)
    if result.public_changed:
        await invalidate_public(redis, result.post)
    if result.slug_change is not None:
        await invalidate_slug_change(redis, result.slug_change)
    return result.post
```

```python
    result = await service.restore_revision(session, user, post_id, rev_id, if_match)
    if result.public_changed:
        await invalidate_public(redis, result.post)
    return result.post
```

In `backend/app/modules/public/router.py`:
1. Add the imports:

```python
from app.modules.public.service import CACHE_TTL_SECONDS, redirect_cache_key
from app.modules.seo import service as seo_service
```

2. Add the response model below `PublicPostOut`:

```python
class RedirectOut(BaseModel):
    to_path: str
    code: int
```

3. Append the route:

```python
def _redirect_not_found() -> AppError:
    return AppError(404, "REDIRECT_NOT_FOUND", "No redirect for this path")


@router.get("/redirects/resolve", response_model=RedirectOut)
async def resolve_redirect(
    response: Response,
    path: str = Query(min_length=1, max_length=300),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> RedirectOut:
    """Used by the Next.js middleware before it renders a 404."""
    if not path.startswith("/"):
        raise AppError(422, "INVALID_PATH", "path must start with '/'")
    response.headers["Cache-Control"] = CACHE_CONTROL
    key = redirect_cache_key(path)
    cached = await cache_get(redis, key)
    if cached == NOT_FOUND_MARKER:
        raise _redirect_not_found()
    if cached:
        response.headers["X-Cache"] = "HIT"
        return RedirectOut.model_validate_json(cached)
    row = await seo_service.resolve_redirect(session, path)
    if row is None:
        await cache_set(redis, key, NOT_FOUND_MARKER, ttl=CACHE_TTL_SECONDS)
        raise _redirect_not_found()
    out = RedirectOut(to_path=row.to_path, code=row.code)
    await cache_set(redis, key, out.model_dump_json())
    response.headers["X-Cache"] = "MISS"
    return out
```

Redirect 404s are cached for the full 60 s, not the 30 s used for articles: `record_slug_change` returns every path it touched, and the router deletes exactly those keys.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest tests/seo tests/posts tests/public tests/db -v`
Expected: all PASS.

- [ ] **Step 9: Run the full suite**

Run: `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add app/modules/seo app/modules/posts app/modules/public app/db/models.py migrations/versions/8b0d2f4a6c75_redirects.py tests/seo/test_redirects.py
git commit -m "feat(seo): explicit slug change with collapsed 301 redirects and cached resolve

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
```

---

## Final verification (after Task 8)

- [ ] Run `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest -W error -q`. Expected: all PASS. The count should be well above M2a1's 118.
- [ ] Run `UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run ruff check app tests`. Expected: no new findings in files this plan touched.
- [ ] Hand the branch to the Opus whole-branch review, then write `docs/superpowers/plans/2026-10-17-m2a2-outcome-and-followups.md` in the same style as the M2a1 outcome note.

## Carry into M2b (not in this plan)

- Refresh tokens, logout, CSRF; revoking access tokens after a password change or deactivation (today they live until expiry, at most 15 min).
- Login rate limit; unarchive (it must also handle translation status); scheduler.
- Worker: process `post.published`, `post.updated` (incl. `redirect`), `post.unpublished`, `post.sent_back`; re-run SEO for a category's posts after a category rename.
- Media/R2 and `featured_image` on cards; `avatar_media_id`; `users.name_ne`.
- Sitemaps/RSS, view stats/trending, scheduled publishing, docx import.
- Home blocks driven by `site_settings` (themes module) instead of "every top-level category".
