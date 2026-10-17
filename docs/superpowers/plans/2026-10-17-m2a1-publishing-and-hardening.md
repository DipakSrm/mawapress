# M2a part 1 — Per-language Publishing, Posts List and M1 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Model routing:** implementer = Sonnet, per-task reviewer = Sonnet, final branch review = Opus.
> Tasks run strictly in order (1 → 7). Task 3 changes the publish signature that Tasks 4–6 rely on; Task 4 needs Tasks 1 and 3; Task 5 needs Task 4; Task 6 needs Tasks 3 and 4 (`auth_if_match`, translation `status`); Task 7 is tests-only.

**Goal:** Each translation of a post gets its own publish state so half-written translations never go public; editors and reporters get a filtered, paginated posts list; and the M1 security/robustness follow-ups are closed with tests.

**Architecture:** One Alembic migration adds `post_translations.status`/`published_at` (backfilled) and the missing `server_default`s. The posts service gains `publish_translation` and `list_posts`; `publish_post` publishes the translations present at that moment and now requires `If-Match`. The public router filters on post **and** translation status and returns 404 envelopes for unknown locales. Auth hardens JWT claim validation and equalises login timing.

**Tech Stack:** Python 3.13, FastAPI 0.143, Pydantic v2, SQLAlchemy 2.1 async (asyncpg), Alembic 1.20, PyJWT 2.15, argon2-cffi, redis-py asyncio, pytest + pytest-asyncio, httpx, testcontainers, fakeredis.

**Spec:** `docs/superpowers/specs/2026-10-16-mawapress-design.md` — §3 "Roles and permissions", "Post workflow", **"Per-language publishing"**; §4 `post_translations`; §7 hreflang row; §9 error envelope. Follow-ups source: `docs/superpowers/plans/2026-10-16-m1-outcome-and-followups.md` (M2 section).

**Prerequisites:** Docker Desktop running (testcontainers). Branch `feat/m2a-content-api` checked out. All commands run from `backend/` in Git Bash:

```bash
UV_PYTHON_INSTALL_DIR='C:\Users\dipak\uv-python' python -m uv run pytest <args>
```

Abbreviated below as `uvpytest <args>` — always expand it to the full command above.

## Global Constraints

- Locales are exactly `"ne"` and `"en"`.
- Translation status values are exactly `draft` and `published` (Postgres enum `translation_status`, server default `'draft'`).
- "A post is public in a locale only when the post is published **and** that translation is published." (spec §3)
- "Publishing a post publishes the translations that exist at that moment; a translation added later to a live post stays a draft until an editor publishes it (`POST /posts/{id}/translations/{locale}/publish`)." (spec §3)
- "hreflang and `alternates` list only published translations." (spec §3)
- Roles rank `reporter < editor < admin`; publish and publish-translation are editor+ only.
- Error envelope for every handled error: `{"error": {"code": str, "message": str, "details": dict}}`.
- Mutations that change a post's version (`PATCH`, `publish`, `publish translation`) require `If-Match: <updated_at ISO>`: missing → 428 `PRECONDITION_REQUIRED`, stale or malformed → 412 `VERSION_CONFLICT`.
- Slugs: produced by `make_slug`, ≤ 80 chars, unique per locale (`-2`, `-3` …). A slug is frozen once **its translation** is published.
- Posts list: `limit` 1–100 (default 20), `offset` ≥ 0 (default 0), ordered `updated_at DESC, id DESC`, response `{items, total, limit, offset}`.
- Public post cache TTL 60 s; `Cache-Control: public, s-maxage=60, stale-while-revalidate=86400`. Any mutation of a published post invalidates its cache keys.
- All timestamps timezone-aware UTC (`app.db.base.utcnow()`).
- Every schema change ships in an Alembic migration with a working `downgrade()`; `tests/db/test_migrations.py` (upgrade, `alembic check`, down/up round trip) must stay green.
- Commits end with a blank line then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A reporter's autosaved half English translation on a live Nepali story** must stay 404 on the public API and must not appear in the Nepali page's `alternates` or `seo.hreflang`. Tested in Task 5 (`test_draft_translation_on_live_post_is_hidden`).
2. **Search text containing `%` or `_`** (e.g. a reporter typing "100%") must match literally, not act as a wildcard. Tested in Task 6 (`test_q_escapes_like_wildcards`).
3. **A reporter passing someone else's `author_id`** to the list must still only see their own posts (empty result), never another reporter's drafts. Tested in Task 6 (`test_reporter_sees_only_own_posts`).
4. **Two reporters saving the same headline at the same moment** must get `…-2`, never a 500; if retries run out the API answers 409 `SLUG_TAKEN`. Tested in Task 3.
5. **A crafted or legacy JWT** (integer `sub`, non-UUID `sub`, no `exp`) must give 401 `INVALID_TOKEN`, never a 500. Tested in Task 2.

---

## File Structure

```
backend/
├── migrations/versions/
│   └── a1d3e5f7b9c2_translation_status_and_defaults.py   # NEW (Task 1)
├── app/
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── security.py      # MODIFY: required JWT claims, DUMMY_PASSWORD_HASH (Task 2)
│   │   │   ├── deps.py          # MODIFY: strict sub validation (Task 2)
│   │   │   └── router.py        # MODIFY: dummy verify on unknown/inactive user (Task 2)
│   │   ├── users/models.py      # MODIFY: server defaults (Task 1)
│   │   ├── posts/
│   │   │   ├── models.py        # MODIFY: TranslationStatus, status/published_at, server defaults (Task 1)
│   │   │   ├── schemas.py       # MODIFY: TranslationOut status fields (Task 4); list schemas (Task 6)
│   │   │   ├── service.py       # MODIFY: slug retry, publish If-Match (Task 3); per-translation publish,
│   │   │   │                    #         SEO alternates, slug freeze per translation (Task 4); list_posts (Task 6)
│   │   │   └── router.py        # MODIFY: publish If-Match (Task 3); translation publish route (Task 4); GET list (Task 6)
│   │   └── public/router.py     # MODIFY: translation gating, alternates, locale 404 (Task 5)
└── tests/
    ├── factories.py             # MODIFY: auth_if_match helper (Task 3)
    ├── db/test_migrations.py    # MODIFY: backfill + server-default test (Task 1)
    ├── auth/test_auth.py        # MODIFY: token + timing tests (Task 2)
    ├── posts/test_posts_api.py  # MODIFY: publish If-Match, slug retry (Task 3); hreflang test rewrite (Task 4); perms tests (Task 7)
    ├── posts/test_translation_publish.py   # NEW (Task 4)
    ├── posts/test_posts_list.py            # NEW (Task 6)
    ├── posts/test_render.py     # MODIFY: quote-breaking tests (Task 7)
    └── public/test_public_api.py # MODIFY: publish If-Match helper (Task 3); visibility/cache/locale tests (Task 5)
```

No new modules; every change follows the existing module layout (`router.py` → `service.py` → models).

---

### Task 1: Migration — translation status, published_at, server defaults

**Files:**
- Create: `backend/migrations/versions/a1d3e5f7b9c2_translation_status_and_defaults.py`
- Modify: `backend/app/modules/posts/models.py` (whole file shown)
- Modify: `backend/app/modules/users/models.py` (whole file shown)
- Test: `backend/tests/db/test_migrations.py`, `backend/tests/db/test_models.py`

**Interfaces:**
- Consumes: existing revision `c70c350a139d` (content core).
- Produces:
  - `app.modules.posts.models.TranslationStatus(StrEnum)` with members `draft = "draft"`, `published = "published"`.
  - `PostTranslation.status: Mapped[TranslationStatus]` (Python default `TranslationStatus.draft`, server default `'draft'`, Postgres enum `translation_status`).
  - `PostTranslation.published_at: Mapped[datetime | None]`.
  - Alembic revision `a1d3e5f7b9c2` (down_revision `c70c350a139d`).
  - Server defaults: `posts.status='draft'`, `posts.created_at=now()`, `posts.updated_at=now()`, `post_translations.seo_auto='{}'::jsonb`, `post_translations.status='draft'`, `users.created_at=now()`, `users.is_active=true`.

Note: `alembic check` does not compare server defaults (Alembic's `compare_server_default` is off by default), so the drift test only checks the new columns and their types; the backfill/defaults test below is what pins the defaults.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/db/test_models.py`, change the posts import line to:

```python
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
```

and append:

```python
async def test_new_translation_defaults_to_draft(session):
    user, cat = await _author_and_category(session)
    post = _post(user, cat, "ne", "naya")
    session.add(post)
    await session.flush()
    session.expunge_all()

    loaded = await session.get(Post, post.id)
    assert loaded.translations[0].status == TranslationStatus.draft
    assert loaded.translations[0].published_at is None
```

In `backend/tests/db/test_migrations.py`, add these imports below the existing `from testcontainers...` import:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
```

and append:

```python
SEED_M1_ROWS = [
    "INSERT INTO users (id, email, password_hash, name, role, is_active, created_at) "
    "VALUES ('00000000-0000-0000-0000-000000000001', 'e@mawapress.com', 'x', 'E', 'editor', true, now())",
    "INSERT INTO categories (id, slug, name_ne, name_en) VALUES (1, 'morang', 'मोरङ', 'Morang')",
    "INSERT INTO posts (id, author_id, category_id, status, published_at, created_at, updated_at) VALUES "
    "('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000001', 1, 'published', "
    "'2026-10-16T05:00:00+00:00', now(), now()), "
    "('00000000-0000-0000-0000-0000000000a2', '00000000-0000-0000-0000-000000000001', 1, 'draft', NULL, now(), now())",
    "INSERT INTO post_translations (post_id, locale, title, slug, content_json, content_html, seo_auto) VALUES "
    "('00000000-0000-0000-0000-0000000000a1', 'ne', 'Live', 'live-post', '{}', '', '{}'), "
    "('00000000-0000-0000-0000-0000000000a1', 'en', 'Live', 'live-post', '{}', '', '{}'), "
    "('00000000-0000-0000-0000-0000000000a2', 'ne', 'Draft', 'draft-post', '{}', '', '{}')",
]


async def test_upgrade_backfills_translation_status_and_sets_server_defaults():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        env = {**os.environ, "MAWA_DATABASE_URL": url}
        to_m1 = _alembic(env, "upgrade", "c70c350a139d")
        assert to_m1.returncode == 0, to_m1.stderr

        eng = create_async_engine(url)
        try:
            async with eng.begin() as conn:
                for stmt in SEED_M1_ROWS:
                    await conn.execute(text(stmt))

            to_head = _alembic(env, "upgrade", "head")
            assert to_head.returncode == 0, to_head.stderr

            async with eng.begin() as conn:
                backfilled = (await conn.execute(text(
                    "SELECT locale, slug, status::text, published_at FROM post_translations ORDER BY slug, locale"
                ))).all()
                await conn.execute(text(
                    "INSERT INTO users (id, email, password_hash, name, role) "
                    "VALUES ('00000000-0000-0000-0000-000000000002', 'r@mawapress.com', 'x', 'R', 'reporter')"
                ))
                await conn.execute(text(
                    "INSERT INTO posts (id, author_id, category_id) VALUES "
                    "('00000000-0000-0000-0000-0000000000a3', '00000000-0000-0000-0000-000000000002', 1)"
                ))
                await conn.execute(text(
                    "INSERT INTO post_translations (post_id, locale, title, slug, content_json, content_html) "
                    "VALUES ('00000000-0000-0000-0000-0000000000a3', 'ne', 'N', 'new-post', '{}', '')"
                ))
                user = (await conn.execute(text(
                    "SELECT is_active, created_at IS NOT NULL FROM users WHERE email = 'r@mawapress.com'"
                ))).one()
                post = (await conn.execute(text(
                    "SELECT status::text, created_at IS NOT NULL, updated_at IS NOT NULL FROM posts "
                    "WHERE id = '00000000-0000-0000-0000-0000000000a3'"
                ))).one()
                tr = (await conn.execute(text(
                    "SELECT status::text, published_at, seo_auto FROM post_translations WHERE slug = 'new-post'"
                ))).one()
        finally:
            await eng.dispose()

    # ORDER BY slug, locale → draft-post/ne, live-post/en, live-post/ne
    assert [(loc, slug, status) for loc, slug, status, _ in backfilled] == [
        ("ne", "draft-post", "draft"),
        ("en", "live-post", "published"),
        ("ne", "live-post", "published"),
    ]
    assert backfilled[0][3] is None
    live_at = backfilled[1][3]
    assert live_at is not None and live_at.isoformat() == "2026-10-16T05:00:00+00:00"
    assert backfilled[2][3] == live_at
    assert tuple(user) == (True, True)
    assert tuple(post) == ("draft", True, True)
    assert tuple(tr) == ("draft", None, {})
```

(The test container's session time zone is UTC, so asyncpg returns `published_at` as a UTC-aware datetime and `isoformat()` matches exactly.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvpytest tests/db -v`
Expected: `tests/db/test_models.py` errors at collection with `ImportError: cannot import name 'TranslationStatus'`; `test_upgrade_backfills_translation_status_and_sets_server_defaults` FAILS on the `SELECT ... status::text` query with `UndefinedColumnError` (column "status" does not exist).

- [ ] **Step 3: Update the models**

Replace `backend/app/modules/posts/models.py` with:

```python
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow


class PostStatus(StrEnum):
    draft = "draft"
    in_review = "in_review"
    scheduled = "scheduled"
    published = "published"
    archived = "archived"


class TranslationStatus(StrEnum):
    draft = "draft"
    published = "published"


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_status_published_at", "status", "published_at"),
        Index("ix_posts_category_published_at", "category_id", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, name="post_status"), default=PostStatus.draft, server_default=PostStatus.draft.value
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    translations: Mapped[list["PostTranslation"]] = relationship(
        back_populates="post", lazy="selectin", cascade="all, delete-orphan", order_by="PostTranslation.id"
    )


class PostTranslation(Base):
    __tablename__ = "post_translations"
    __table_args__ = (
        UniqueConstraint("locale", "slug", name="uq_translation_locale_slug"),
        UniqueConstraint("post_id", "locale", name="uq_translation_post_locale"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(String(2))
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(100))
    content_json: Mapped[dict] = mapped_column(JSONB)
    content_html: Mapped[str] = mapped_column(Text)
    seo_title: Mapped[str | None] = mapped_column(String(120))
    seo_description: Mapped[str | None] = mapped_column(String(320))
    seo_auto: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[TranslationStatus] = mapped_column(
        Enum(TranslationStatus, name="translation_status"),
        default=TranslationStatus.draft,
        server_default=TranslationStatus.draft.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    post: Mapped[Post] = relationship(back_populates="translations")
```

Replace `backend/app/modules/users/models.py` with:

```python
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, String, Uuid, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Role(StrEnum):
    reporter = "reporter"
    editor = "editor"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
```

- [ ] **Step 4: Write the migration**

Create `backend/migrations/versions/a1d3e5f7b9c2_translation_status_and_defaults.py`:

```python
"""translation status and server defaults

Revision ID: a1d3e5f7b9c2
Revises: c70c350a139d
Create Date: 2026-10-17 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1d3e5f7b9c2"
down_revision: Union[str, Sequence[str], None] = "c70c350a139d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

translation_status = postgresql.ENUM("draft", "published", name="translation_status", create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    # op.add_column does not emit CREATE TYPE, so create the enum explicitly.
    postgresql.ENUM("draft", "published", name="translation_status").create(op.get_bind(), checkfirst=True)
    op.add_column(
        "post_translations",
        sa.Column("status", translation_status, nullable=False, server_default="draft"),
    )
    op.add_column(
        "post_translations",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Translations of posts that are already live were public under M1 rules: keep them public.
    op.execute(
        """
        UPDATE post_translations AS t
        SET status = 'published', published_at = p.published_at
        FROM posts AS p
        WHERE p.id = t.post_id AND p.status = 'published'
        """
    )

    op.alter_column("posts", "status", server_default="draft")
    op.alter_column("posts", "created_at", server_default=sa.func.now())
    op.alter_column("posts", "updated_at", server_default=sa.func.now())
    op.alter_column("post_translations", "seo_auto", server_default=sa.text("'{}'::jsonb"))
    op.alter_column("users", "created_at", server_default=sa.func.now())
    op.alter_column("users", "is_active", server_default=sa.true())


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("users", "is_active", server_default=None)
    op.alter_column("users", "created_at", server_default=None)
    op.alter_column("post_translations", "seo_auto", server_default=None)
    op.alter_column("posts", "updated_at", server_default=None)
    op.alter_column("posts", "created_at", server_default=None)
    op.alter_column("posts", "status", server_default=None)

    op.drop_column("post_translations", "published_at")
    op.drop_column("post_translations", "status")
    sa.Enum(name="translation_status").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 5: Run the DB tests to verify they pass**

Run: `uvpytest tests/db -v`
Expected: all PASS, including the existing `test_alembic_upgrade_head_on_empty_database`, `test_models_match_migrations` (no drift) and `test_alembic_downgrade_then_upgrade_round_trip`.

- [ ] **Step 6: Run the full suite (no behaviour change yet)**

Run: `uvpytest -q`
Expected: all PASS (the existing suite plus the 2 new tests).

- [ ] **Step 7: Commit**

```bash
git add migrations/versions/a1d3e5f7b9c2_translation_status_and_defaults.py app/modules/posts/models.py app/modules/users/models.py tests/db/test_migrations.py tests/db/test_models.py
git commit -m "feat(db): per-translation status and server defaults

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Auth hardening — strict JWT claims and login timing

**Files:**
- Modify: `backend/app/modules/auth/security.py` (whole file shown)
- Modify: `backend/app/modules/auth/deps.py` (`current_user` only; whole file shown)
- Modify: `backend/app/modules/auth/router.py:42-47` (`login` only)
- Test: `backend/tests/auth/test_auth.py`

**Interfaces:**
- Consumes: `app.core.config.get_settings()`, `app.modules.users.models.User` (with `is_active`).
- Produces:
  - `app.modules.auth.security.DUMMY_PASSWORD_HASH: str` — an argon2 hash computed once at import.
  - `app.modules.auth.security.REQUIRED_CLAIMS = ["exp", "sub", "iat"]`.
  - `decode_access_token(token: str) -> dict` now raises `jwt.MissingRequiredClaimError` when `exp`, `sub` or `iat` is absent, and `jwt.InvalidSubjectError` when `sub` is not a string (both subclasses of `jwt.PyJWTError`).
  - `current_user` returns 401 `INVALID_TOKEN` (never 500) for: expired, bad signature, missing required claim, non-string `sub`, non-UUID `sub`, unknown or inactive user.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/auth/test_auth.py` (add the new imports to the top of the file, merging with the existing ones):

```python
from datetime import timedelta

import jwt

from app.core.config import get_settings
from app.db.base import utcnow
from app.modules.auth import router as auth_router
from app.modules.auth.security import ALGORITHM, DUMMY_PASSWORD_HASH
```

```python
def forged(claims: dict, secret: str | None = None) -> dict[str, str]:
    token = jwt.encode(claims, secret or get_settings().jwt_secret, algorithm=ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


async def assert_invalid_token(client, headers):
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_expired_token_is_401(client, session):
    user = await make_user(session)
    past = utcnow() - timedelta(hours=1)
    await assert_invalid_token(client, forged({"sub": str(user.id), "iat": past, "exp": past + timedelta(minutes=15)}))


async def test_wrong_signature_is_401(client, session):
    user = await make_user(session)
    now = utcnow()
    claims = {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=15)}
    await assert_invalid_token(client, forged(claims, secret="another-secret-that-is-at-least-32-chars"))


async def test_deactivated_user_with_valid_token_is_401(client, session):
    user = await make_user(session, is_active=False)
    await assert_invalid_token(client, auth_header(user))


async def test_token_missing_required_claims_is_401(client, session):
    user = await make_user(session)
    now = utcnow()
    full = {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=15)}
    for missing in ("exp", "sub", "iat"):
        claims = {k: v for k, v in full.items() if k != missing}
        await assert_invalid_token(client, forged(claims))


async def test_non_string_or_malformed_sub_is_401_not_500(client, session):
    now = utcnow()
    for sub in (12345, ["x"], "not-a-uuid"):
        await assert_invalid_token(client, forged({"sub": sub, "iat": now, "exp": now + timedelta(minutes=15)}))


async def test_login_runs_password_hash_even_for_unknown_or_inactive_user(client, session, monkeypatch):
    await make_user(session, email="off2@mawapress.com", password="right-pass-1", is_active=False)
    seen: list[str] = []
    real_verify = auth_router.verify_password

    def spy(password: str, password_hash: str) -> bool:
        seen.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_router, "verify_password", spy)
    for email in ("ghost2@mawapress.com", "off2@mawapress.com"):
        r = await client.post("/api/auth/login", json={"email": email, "password": "right-pass-1"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert seen == [DUMMY_PASSWORD_HASH, DUMMY_PASSWORD_HASH]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvpytest tests/auth -v`
Expected: collection error `ImportError: cannot import name 'DUMMY_PASSWORD_HASH'`. (Before the import exists, `test_token_missing_required_claims_is_401` would also fail with 200 for the missing-`iat` case, and the integer-`sub` case of `test_non_string_or_malformed_sub_is_401_not_500` is the one that used to risk a 500.)

- [ ] **Step 3: Implement `security.py`**

Replace `backend/app/modules/auth/security.py` with:

```python
import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.db.base import utcnow

_hasher = PasswordHasher()
ALGORITHM = "HS256"
REQUIRED_CLAIMS = ["exp", "sub", "iat"]

# Verified against when the email is unknown or the user is inactive, so a failed
# login costs one argon2 verify either way and response time does not leak which
# emails exist.
DUMMY_PASSWORD_HASH = _hasher.hash("mawapress-timing-equaliser")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = utcnow()
    claims = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(minutes=settings.jwt_access_minutes)}
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate. Raises jwt.PyJWTError on any problem, including a missing
    exp/sub/iat claim or a non-string sub (PyJWT >= 2.10 validates sub's type)."""
    return jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=[ALGORITHM],
        options={"require": REQUIRED_CLAIMS},
    )
```

- [ ] **Step 4: Implement strict `sub` handling in `deps.py`**

Replace `backend/app/modules/auth/deps.py` with:

```python
import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.security import decode_access_token
from app.modules.users.models import Role, User

ROLE_RANK = {Role.reporter: 1, Role.editor: 2, Role.admin: 3}
_bearer = HTTPBearer(auto_error=False)


def _user_id_from_token(token: str) -> uuid.UUID | None:
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    sub = claims.get("sub")
    if not isinstance(sub, str):
        return None
    try:
        return uuid.UUID(sub)
    except ValueError:
        return None


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None:
        raise AppError(401, "NOT_AUTHENTICATED", "Login required")
    user_id = _user_id_from_token(creds.credentials)
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise AppError(401, "INVALID_TOKEN", "Token is invalid or expired")
    return user


def require_role(min_role: Role):
    async def dependency(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[min_role]:
            raise AppError(403, "FORBIDDEN_ROLE", f"Requires {min_role.value} role or higher")
        return user

    return dependency
```

- [ ] **Step 5: Equalise login timing in `router.py`**

In `backend/app/modules/auth/router.py`, change the security import to:

```python
from app.modules.auth.security import DUMMY_PASSWORD_HASH, create_access_token, verify_password
```

and replace the `login` function with:

```python
@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active:
        verify_password(body.password, DUMMY_PASSWORD_HASH)  # same cost as a real check
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
    if not verify_password(body.password, user.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
    return TokenOut(access_token=create_access_token(user.id, user.role.value))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uvpytest tests/auth -v`
Expected: all PASS (4 existing + 6 new).

- [ ] **Step 7: Run the full suite**

Run: `uvpytest -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/modules/auth/security.py app/modules/auth/deps.py app/modules/auth/router.py tests/auth/test_auth.py
git commit -m "fix(auth): require exp/sub/iat, reject bad sub with 401, equalise login timing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Posts hardening — publish requires If-Match, slug-collision retry

**Files:**
- Modify: `backend/app/modules/posts/service.py` (imports; `create_post` at lines 116-130; `publish_post` at lines 194-203)
- Modify: `backend/app/modules/posts/router.py` (`publish_post` at lines 54-63)
- Modify: `backend/tests/factories.py` (add `auth_if_match`)
- Test: `backend/tests/posts/test_posts_api.py`, `backend/tests/public/test_public_api.py` (existing publish calls updated)

**Interfaces:**
- Consumes: `service._check_version(post: Post, if_match: str | None) -> None` (existing: 428 when `None`, 412 when stale or unparsable), `service.unique_slug(session, locale, base, exclude_id=None) -> str` (existing).
- Produces:
  - `service.publish_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post` (new third parameter, required).
  - `service.SLUG_RETRY_ATTEMPTS = 3`, `service.SLUG_CONSTRAINT = "uq_translation_locale_slug"`.
  - `create_post` retries on an `IntegrityError` naming `uq_translation_locale_slug` (up to 3 attempts, each in a SAVEPOINT); after 3 failures it raises `AppError(409, "SLUG_TAKEN", ...)`.
  - `tests.factories.auth_if_match(user: User, updated_at: str) -> dict[str, str]` — auth header plus `If-Match`.

- [ ] **Step 1: Add the test helper**

Append to `backend/tests/factories.py`:

```python
def auth_if_match(user: User, updated_at: str) -> dict[str, str]:
    return {**auth_header(user), "If-Match": updated_at}
```

- [ ] **Step 2: Write the failing tests**

In `backend/tests/posts/test_posts_api.py`, change the imports at the top to:

```python
from datetime import datetime

from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.posts import service
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, make_category, make_user
```

Append:

```python
async def test_publish_requires_if_match(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    url = f"/api/posts/{post['id']}/publish"

    missing = await client.post(url, headers=auth_header(editor))
    assert missing.status_code == 428
    assert missing.json()["error"]["code"] == "PRECONDITION_REQUIRED"

    stale = await client.post(url, headers=auth_if_match(editor, "2020-01-01T00:00:00+00:00"))
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    # Pydantic emits "...Z", isoformat() emits "+00:00": compare as datetimes.
    current = datetime.fromisoformat(stale.json()["error"]["details"]["current_updated_at"])
    assert current == datetime.fromisoformat(post["updated_at"])

    ok = await client.post(url, headers=auth_if_match(editor, post["updated_at"]))
    assert ok.status_code == 200
    assert ok.json()["status"] == "published"


async def test_malformed_if_match_is_412(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    for bad in ("not-a-date", "", '"'):
        r = await client.patch(
            f"/api/posts/{post['id']}",
            json={"locale": "ne", "title": "मोरङ समाचार"},
            headers=auth_if_match(reporter, bad),
        )
        assert r.status_code == 412, bad
        assert r.json()["error"]["code"] == "VERSION_CONFLICT"


async def test_concurrent_slug_collision_retries_with_next_suffix(client, session, monkeypatch):
    reporter = await make_user(session)
    cat = await make_category(session)
    await create(client, reporter, cat)  # takes "badhi-samachar"
    real_unique_slug = service.unique_slug
    calls: list[str] = []

    async def racing_unique_slug(session_, locale, base, exclude_id=None):
        calls.append(base)
        if len(calls) == 1:
            return base  # simulate: the check ran before the other request's insert committed
        return await real_unique_slug(session_, locale, base, exclude_id)

    monkeypatch.setattr(service, "unique_slug", racing_unique_slug)
    r = await create(client, reporter, cat)
    assert r.status_code == 201
    assert r.json()["translations"][0]["slug"] == "badhi-samachar-2"
    assert calls == ["badhi-samachar", "badhi-samachar"]


async def test_slug_collision_gives_409_after_three_attempts(client, session, monkeypatch):
    reporter = await make_user(session)
    cat = await make_category(session)
    await create(client, reporter, cat)
    calls: list[str] = []

    async def always_taken(session_, locale, base, exclude_id=None):
        calls.append(base)
        return base

    monkeypatch.setattr(service, "unique_slug", always_taken)
    r = await create(client, reporter, cat)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SLUG_TAKEN"
    assert len(calls) == 3
```

Update the three existing publish calls in `backend/tests/posts/test_posts_api.py` so they send `If-Match`:

In `test_submit_then_editor_publishes_and_outbox_written`, replace

```python
    published = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))
```

with

```python
    published = await client.post(
        f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, submitted.json()["updated_at"])
    )
```

In both `test_slug_is_frozen_after_publish` and `test_editing_published_post_writes_post_updated_event`, replace

```python
    published = (await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))).json()
```

with

```python
    published = (await client.post(
        f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"])
    )).json()
```

In `backend/tests/public/test_public_api.py`, change the factories import to

```python
from tests.factories import auth_header, auth_if_match, make_category, make_user
```

and in `published_post`, replace

```python
    published = (await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))).json()
```

with

```python
    published = (await client.post(
        f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"])
    )).json()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uvpytest tests/posts/test_posts_api.py -v`
Expected: `test_publish_requires_if_match` FAILS (`missing.status_code` is 200, not 428); `test_concurrent_slug_collision_retries_with_next_suffix` FAILS with a 500 (`IntegrityError` on `uq_translation_locale_slug`); `test_slug_collision_gives_409_after_three_attempts` FAILS (500). `test_malformed_if_match_is_412` already PASSES (it pins existing behaviour). The updated existing tests PASS (the header is ignored today).

- [ ] **Step 4: Implement the service changes**

In `backend/app/modules/posts/service.py`, add to the imports:

```python
from sqlalchemy.exc import IntegrityError
```

Add below `MAX_SLUG_LEN = 80`:

```python
SLUG_RETRY_ATTEMPTS = 3
SLUG_CONSTRAINT = "uq_translation_locale_slug"


def _is_slug_conflict(exc: IntegrityError) -> bool:
    return SLUG_CONSTRAINT in str(exc.orig)
```

Replace `create_post` with:

```python
async def create_post(session: AsyncSession, author: User, data: PostCreate) -> Post:
    if await session.get(Category, data.category_id) is None:
        raise AppError(422, "CATEGORY_NOT_FOUND", "Category does not exist")
    base = make_slug(data.title)
    content_html = render_html(data.content_json)
    for _ in range(SLUG_RETRY_ATTEMPTS):
        # unique_slug checks committed rows; a concurrent create can still win the race
        # between our check and our INSERT. The SAVEPOINT lets us retry with a fresh check.
        slug = await unique_slug(session, data.locale, base)
        post = Post(author_id=author.id, category_id=data.category_id, status=PostStatus.draft)
        post.translations.append(
            PostTranslation(
                locale=data.locale,
                title=data.title,
                slug=slug,
                content_json=data.content_json,
                content_html=content_html,
            )
        )
        try:
            async with session.begin_nested():
                session.add(post)
                await session.flush()
        except IntegrityError as exc:
            if not _is_slug_conflict(exc):
                raise
            continue
        return await _save(session, post)
    raise AppError(409, "SLUG_TAKEN", "Could not allocate a unique slug; please retry")
```

Replace `publish_post` with:

```python
async def publish_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post:
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status not in (PostStatus.draft, PostStatus.in_review):
        raise AppError(409, "INVALID_TRANSITION", f"Cannot publish a post that is {post.status.value}")
    now = utcnow()
    post.status = PostStatus.published
    post.published_at = post.published_at or now
    post.updated_at = now
    session.add(_post_event("post.published", post))
    return await _save(session, post)
```

- [ ] **Step 5: Pass If-Match through the router**

In `backend/app/modules/posts/router.py`, replace the `publish_post` route with:

```python
@router.post("/{post_id}/publish", response_model=PostOut)
async def publish_post(
    post_id: uuid.UUID,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.publish_post(session, post_id, if_match)
    await invalidate_post_cache(redis, post)
    return post
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uvpytest tests/posts tests/public -v`
Expected: all PASS.

- [ ] **Step 7: Run the full suite**

Run: `uvpytest -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/modules/posts/service.py app/modules/posts/router.py tests/factories.py tests/posts/test_posts_api.py tests/public/test_public_api.py
git commit -m "fix(posts): require If-Match on publish, retry slug collisions on create

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Per-translation publishing — service, endpoint, SEO alternates

**Files:**
- Modify: `backend/app/modules/posts/schemas.py` (`TranslationOut`)
- Modify: `backend/app/modules/posts/service.py` (`_refresh_all_seo`, `update_post` slug-freeze line, `publish_post`, new `publish_translation`)
- Modify: `backend/app/modules/posts/router.py` (new route)
- Create: `backend/tests/posts/test_translation_publish.py`
- Modify: `backend/tests/posts/test_posts_api.py` (rewrite `test_adding_english_translation_links_hreflang`)

**Interfaces:**
- Consumes: `TranslationStatus` and `PostTranslation.status/published_at` (Task 1); `publish_post(session, post_id, if_match)` and `tests.factories.auth_if_match` (Task 3); `_check_version`, `_get_post_for_update`, `_post_event`, `_save` (existing).
- Produces:
  - `TranslationOut` gains `status: TranslationStatus` and `published_at: datetime | None`.
  - `publish_post` sets every translation present at that moment to `published` with `published_at = now` (translations already published keep their `published_at`).
  - `service.publish_translation(session: AsyncSession, post_id: uuid.UUID, locale: str, if_match: str | None) -> Post`. Errors, in check order: 404 `POST_NOT_FOUND`; 428/412 (If-Match); 409 `INVALID_TRANSITION` if the post is not published; 404 `TRANSLATION_NOT_FOUND` if the post has no translation in `locale`; 409 `INVALID_TRANSITION` if that translation is already published. On success: translation → published, `post.updated_at = now`, outbox `post.updated`, SEO refreshed for all translations.
  - Route `POST /api/posts/{post_id}/translations/{locale}/publish` (editor+, `If-Match` header, `locale: Literal["ne","en"]`), response `PostOut`, invalidates the post's public cache keys.
  - SEO rule: a translation's `seo_auto.hreflang` lists only the **other published** translations (plus itself and `x-default` when there is at least one). Draft-only posts have `hreflang == {}`.
  - Slug rule: a translation's slug can change on title edit while **that translation** is a draft, even if the post is live; once the translation is published the slug is frozen.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/posts/test_translation_publish.py`:

```python
from datetime import datetime

from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, make_category, make_user


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def create_ne(client, user, category, title="बाढी समाचार"):
    r = await client.post(
        "/api/posts",
        json={"locale": "ne", "title": title, "content_json": doc("पानी"), "category_id": category.id},
        headers=auth_header(user),
    )
    assert r.status_code == 201
    return r.json()


async def add_en(client, user, post, title="Flood in Biratnagar"):
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": title, "content_json": doc("It is raining")},
        headers=auth_if_match(user, post["updated_at"]),
    )
    assert r.status_code == 200
    return r.json()


async def publish(client, editor, post):
    r = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 200
    return r.json()


def by_locale(post: dict) -> dict[str, dict]:
    return {t["locale"]: t for t in post["translations"]}


async def test_publish_publishes_translations_present_at_that_moment(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await add_en(client, editor, await create_ne(client, editor, cat))
    assert {t["status"] for t in post["translations"]} == {"draft"}
    assert all(t["published_at"] is None for t in post["translations"])

    live = await publish(client, editor, post)
    trs = by_locale(live)
    assert trs["ne"]["status"] == trs["en"]["status"] == "published"
    published_at = datetime.fromisoformat(live["published_at"])
    assert datetime.fromisoformat(trs["ne"]["published_at"]) == published_at
    assert datetime.fromisoformat(trs["en"]["published_at"]) == published_at


async def test_translation_added_to_live_post_stays_draft_until_published(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish(client, editor, await create_ne(client, editor, cat))

    with_en = await add_en(client, editor, live)
    trs = by_locale(with_en)
    assert trs["en"]["status"] == "draft" and trs["en"]["published_at"] is None
    assert trs["ne"]["seo_auto"]["hreflang"] == {}  # draft English is not advertised

    r = await client.post(
        f"/api/posts/{live['id']}/translations/en/publish",
        headers=auth_if_match(editor, with_en["updated_at"]),
    )
    assert r.status_code == 200
    body = r.json()
    trs = by_locale(body)
    assert trs["en"]["status"] == "published" and trs["en"]["published_at"] is not None
    assert body["updated_at"] != with_en["updated_at"]
    assert set(trs["ne"]["seo_auto"]["hreflang"]) == {"ne", "en", "x-default"}
    assert trs["ne"]["seo_auto"]["hreflang"]["en"].endswith("/en/morang/flood-in-biratnagar")
    assert trs["en"]["seo_auto"]["hreflang"]["ne"].endswith("/ne/morang/badhi-samachar")

    events = (await session.scalars(
        select(OutboxEvent).where(OutboxEvent.topic == "post.updated").order_by(OutboxEvent.id)
    )).all()
    assert len(events) == 2  # one for the PATCH on the live post, one for the translation publish
    assert events[-1].payload["slugs"] == {"ne": "badhi-samachar", "en": "flood-in-biratnagar"}


async def test_translation_publish_guards(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)

    draft = await add_en(client, editor, await create_ne(client, editor, cat))
    not_live = await client.post(
        f"/api/posts/{draft['id']}/translations/en/publish", headers=auth_if_match(editor, draft["updated_at"])
    )
    assert not_live.status_code == 409
    assert not_live.json()["error"]["code"] == "INVALID_TRANSITION"

    live = await publish(client, editor, await create_ne(client, editor, cat, title="मोरङ समाचार"))
    url_en = f"/api/posts/{live['id']}/translations/en/publish"
    url_ne = f"/api/posts/{live['id']}/translations/ne/publish"

    denied = await client.post(url_en, headers=auth_if_match(reporter, live["updated_at"]))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN_ROLE"

    missing = await client.post(url_en, headers=auth_header(editor))
    assert missing.status_code == 428

    stale = await client.post(url_en, headers=auth_if_match(editor, "2020-01-01T00:00:00+00:00"))
    assert stale.status_code == 412

    no_en = await client.post(url_en, headers=auth_if_match(editor, live["updated_at"]))
    assert no_en.status_code == 404
    assert no_en.json()["error"]["code"] == "TRANSLATION_NOT_FOUND"

    already = await client.post(url_ne, headers=auth_if_match(editor, live["updated_at"]))
    assert already.status_code == 409
    assert already.json()["error"]["code"] == "INVALID_TRANSITION"

    bad_locale = await client.post(
        f"/api/posts/{live['id']}/translations/fr/publish", headers=auth_if_match(editor, live["updated_at"])
    )
    assert bad_locale.status_code == 422


async def test_draft_translation_slug_follows_title_while_published_one_is_frozen(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish(client, editor, await create_ne(client, editor, cat))
    with_en = await add_en(client, editor, live, title="Draft English")
    assert by_locale(with_en)["en"]["slug"] == "draft-english"

    retitled = await client.patch(
        f"/api/posts/{live['id']}",
        json={"locale": "en", "title": "Late English"},
        headers=auth_if_match(editor, with_en["updated_at"]),
    )
    assert by_locale(retitled.json())["en"]["slug"] == "late-english"

    ne_retitled = await client.patch(
        f"/api/posts/{live['id']}",
        json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers=auth_if_match(editor, retitled.json()["updated_at"]),
    )
    ne = by_locale(ne_retitled.json())["ne"]
    assert ne["title"] == "नयाँ शीर्षक"
    assert ne["slug"] == "badhi-samachar"
```

In `backend/tests/posts/test_posts_api.py`, replace the whole `test_adding_english_translation_links_hreflang` function with:

```python
async def test_adding_english_translation_links_hreflang(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": "Flood in Biratnagar", "content_json": doc("It is raining")},
        headers={**auth_header(reporter), "If-Match": post["updated_at"]},
    )
    assert r.status_code == 200
    ne, en = r.json()["translations"]
    assert en["slug"] == "flood-in-biratnagar"
    assert ne["seo_auto"]["hreflang"] == {} and en["seo_auto"]["hreflang"] == {}  # nothing published yet

    published = await client.post(
        f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, r.json()["updated_at"])
    )
    ne, en = published.json()["translations"]
    assert set(ne["seo_auto"]["hreflang"]) == {"ne", "en", "x-default"}
    assert en["seo_auto"]["hreflang"]["ne"].endswith("/ne/morang/badhi-samachar")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvpytest tests/posts/test_translation_publish.py tests/posts/test_posts_api.py -v`
Expected: `test_publish_publishes_translations_present_at_that_moment` FAILS with `KeyError: 'status'` (field not in `TranslationOut`); the translation-publish tests FAIL with 404 `NOT_FOUND` (route missing); `test_adding_english_translation_links_hreflang` FAILS (hreflang is populated for drafts today).

- [ ] **Step 3: Expose translation status in the schema**

In `backend/app/modules/posts/schemas.py`, change the models import to

```python
from app.modules.posts.models import PostStatus, TranslationStatus
```

and replace `TranslationOut` with:

```python
class TranslationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    title: str
    slug: str
    status: TranslationStatus
    published_at: datetime | None
    content_json: dict
    content_html: str
    seo_title: str | None
    seo_description: str | None
    seo_auto: dict
```

- [ ] **Step 4: Implement the service changes**

In `backend/app/modules/posts/service.py`, change the models import to

```python
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
```

In `_refresh_all_seo`, replace the `alternates = ...` line with:

```python
        alternates = {
            t.locale: t.slug
            for t in post.translations
            if t.locale != tr.locale and t.status == TranslationStatus.published
        }
```

In `update_post`, replace

```python
            if post.status != PostStatus.published:
                tr.slug = await unique_slug(session, tr.locale, make_slug(data.title), exclude_id=tr.id)
```

with

```python
            if tr.status != TranslationStatus.published:
                tr.slug = await unique_slug(session, tr.locale, make_slug(data.title), exclude_id=tr.id)
```

Replace `publish_post` with:

```python
async def publish_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post:
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
    session.add(_post_event("post.published", post))
    return await _save(session, post)
```

Append `publish_translation`:

```python
async def publish_translation(session: AsyncSession, post_id: uuid.UUID, locale: str, if_match: str | None) -> Post:
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status != PostStatus.published:
        raise AppError(409, "INVALID_TRANSITION", "Publish the post before publishing a single translation")
    tr = next((t for t in post.translations if t.locale == locale), None)
    if tr is None:
        raise AppError(404, "TRANSLATION_NOT_FOUND", f"Post has no '{locale}' translation")
    if tr.status == TranslationStatus.published:
        raise AppError(409, "INVALID_TRANSITION", f"The '{locale}' translation is already published")
    now = utcnow()
    tr.status = TranslationStatus.published
    tr.published_at = now
    post.updated_at = now
    session.add(_post_event("post.updated", post))
    return await _save(session, post)
```

- [ ] **Step 5: Add the route**

In `backend/app/modules/posts/router.py`, change the schemas import to

```python
from app.modules.posts.schemas import Locale, PostCreate, PostOut, PostUpdate
```

and append:

```python
@router.post("/{post_id}/translations/{locale}/publish", response_model=PostOut)
async def publish_translation(
    post_id: uuid.UUID,
    locale: Locale,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.publish_translation(session, post_id, locale, if_match)
    await invalidate_post_cache(redis, post)
    return post
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uvpytest tests/posts -v`
Expected: all PASS, including the untouched `test_slug_is_frozen_after_publish` and `test_editing_published_post_writes_post_updated_event`.

- [ ] **Step 7: Run the full suite**

Run: `uvpytest -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/modules/posts/schemas.py app/modules/posts/service.py app/modules/posts/router.py tests/posts/test_translation_publish.py tests/posts/test_posts_api.py
git commit -m "feat(posts): per-translation publishing and published-only hreflang

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Public endpoint — serve only published translations, 404 for unknown locales

**Files:**
- Modify: `backend/app/modules/public/router.py` (imports; `get_public_post`)
- Test: `backend/tests/public/test_public_api.py`

**Interfaces:**
- Consumes: `TranslationStatus` (Task 1); `publish_post` with If-Match and `auth_if_match` (Task 3); `POST /api/posts/{id}/translations/{locale}/publish` (Task 4); `post_cache_key(locale, slug)` and `invalidate_post_cache` (existing, `app.modules.public.service`).
- Produces:
  - `GET /api/public/posts/{locale}/{slug}` returns 200 only when `posts.status = 'published'` **and** `post_translations.status = 'published'`; otherwise 404 `POST_NOT_FOUND`.
  - `alternates` lists only other **published** translations.
  - Any `locale` other than `ne`/`en` → 404 `POST_NOT_FOUND` envelope (was 422 `VALIDATION_ERROR`), checked before the cache is touched.
  - `app.modules.public.router.SUPPORTED_LOCALES = ("ne", "en")`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/public/test_public_api.py`, add to the imports:

```python
from app.modules.public.service import post_cache_key
```

Append:

```python
async def draft_post(client, editor, cat, title="बाढी समाचार"):
    r = await client.post(
        "/api/posts",
        json={"locale": "ne", "title": title, "content_json": doc("पानी"), "category_id": cat.id},
        headers=auth_header(editor),
    )
    assert r.status_code == 201
    return r.json()


async def add_english(client, editor, post, title="Flood in Biratnagar"):
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": title, "content_json": doc("It is raining")},
        headers=auth_if_match(editor, post["updated_at"]),
    )
    assert r.status_code == 200
    return r.json()


async def test_en_locale_and_alternates_when_both_published(client, session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    cat = await make_category(session)
    with_en = await add_english(client, editor, await draft_post(client, editor, cat))
    published = await client.post(
        f"/api/posts/{with_en['id']}/publish", headers=auth_if_match(editor, with_en["updated_at"])
    )
    assert published.status_code == 200

    en = await client.get("/api/public/posts/en/flood-in-biratnagar")
    assert en.status_code == 200
    body = en.json()
    assert body["locale"] == "en"
    assert body["title"] == "Flood in Biratnagar"
    assert body["content_html"] == "<p>It is raining</p>"
    assert body["alternates"] == {"ne": "badhi-samachar"}
    assert body["seo"]["hreflang"]["ne"].endswith("/ne/morang/badhi-samachar")
    assert body["seo"]["hreflang"]["x-default"].endswith("/ne/morang/badhi-samachar")
    assert body["seo"]["json_ld"][0]["inLanguage"] == "en"

    ne = await client.get("/api/public/posts/ne/badhi-samachar")
    assert ne.json()["alternates"] == {"en": "flood-in-biratnagar"}


async def test_draft_translation_on_live_post_is_hidden(client, session):
    editor, published = await published_post(client, session)
    await add_english(client, editor, published)  # autosaved half translation on a live post

    en = await client.get("/api/public/posts/en/flood-in-biratnagar")
    assert en.status_code == 404
    assert en.json()["error"]["code"] == "POST_NOT_FOUND"

    ne = await client.get("/api/public/posts/ne/badhi-samachar")
    assert ne.status_code == 200
    assert ne.json()["alternates"] == {}
    assert ne.json()["seo"]["hreflang"] == {}


async def test_publishing_translation_invalidates_cached_sibling(client, session):
    editor, published = await published_post(client, session)
    with_en = await add_english(client, editor, published)
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).headers["x-cache"] == "MISS"
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).headers["x-cache"] == "HIT"

    r = await client.post(
        f"/api/posts/{published['id']}/translations/en/publish",
        headers=auth_if_match(editor, with_en["updated_at"]),
    )
    assert r.status_code == 200

    ne = await client.get("/api/public/posts/ne/badhi-samachar")
    assert ne.headers["x-cache"] == "MISS"
    assert ne.json()["alternates"] == {"en": "flood-in-biratnagar"}
    en = await client.get("/api/public/posts/en/flood-in-biratnagar")
    assert en.status_code == 200
    assert en.json()["alternates"] == {"ne": "badhi-samachar"}


async def test_publish_invalidates_public_cache(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await draft_post(client, editor, cat)
    key = post_cache_key("ne", "badhi-samachar")
    await fake_redis.set(key, "stale entry from an earlier publication")

    r = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 200
    assert await fake_redis.get(key) is None

    served = await client.get("/api/public/posts/ne/badhi-samachar")
    assert served.headers["x-cache"] == "MISS"
    assert served.json()["title"] == "बाढी समाचार"


async def test_unknown_locale_is_404_envelope(client, session):
    await published_post(client, session)
    for locale in ("fr", "NE", "nep"):
        r = await client.get(f"/api/public/posts/{locale}/badhi-samachar")
        assert r.status_code == 404, locale
        assert r.json()["error"]["code"] == "POST_NOT_FOUND"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvpytest tests/public -v`
Expected: `test_draft_translation_on_live_post_is_hidden` FAILS (the draft `en` page returns 200 and `ne` lists it in `alternates`); `test_unknown_locale_is_404_envelope` FAILS (422 `VALIDATION_ERROR`). `test_en_locale_and_alternates_when_both_published`, `test_publishing_translation_invalidates_cached_sibling` and `test_publish_invalidates_public_cache` already PASS after Tasks 3–4; they are the follow-up tests ("publish invalidates the public cache", "en locale + alternates") and must keep passing after this change.

- [ ] **Step 3: Implement the router changes**

In `backend/app/modules/public/router.py`:

Remove the now-unused `from typing import Literal` import, and change the posts models import to

```python
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
```

Add below `router = APIRouter(...)`:

```python
SUPPORTED_LOCALES = ("ne", "en")
```

Replace `get_public_post` with:

```python
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
        raise AppError(404, "POST_NOT_FOUND", "Post not found")
    response.headers["Cache-Control"] = CACHE_CONTROL
    key = post_cache_key(locale, slug)
    cached = None
    try:
        cached = await redis.get(key)
    except RedisError:
        logger.warning("Cache read failed; serving from database", exc_info=True)
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
        raise AppError(404, "POST_NOT_FOUND", "Post not found")
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
        published_at=post.published_at,
        updated_at=post.updated_at,
        seo=tr.seo_auto,
        alternates={
            t.locale: t.slug
            for t in post.translations
            if t.locale != tr.locale and t.status == TranslationStatus.published
        },
    )
    try:
        await redis.set(key, out.model_dump_json(), ex=CACHE_TTL_SECONDS)
    except RedisError:
        logger.warning("Cache write failed; response not cached", exc_info=True)
    response.headers["X-Cache"] = "MISS"
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uvpytest tests/public -v`
Expected: all PASS (6 existing + 5 new).

- [ ] **Step 5: Run the full suite**

Run: `uvpytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/modules/public/router.py tests/public/test_public_api.py
git commit -m "feat(public): serve only published translations; unknown locale is 404

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Posts list — `GET /api/posts` with filters and pagination

**Files:**
- Modify: `backend/app/modules/posts/schemas.py` (append list schemas)
- Modify: `backend/app/modules/posts/service.py` (append `list_posts`, `_escape_like`; import `exists`, `func`)
- Modify: `backend/app/modules/posts/router.py` (new `GET ""` route; import `Query`, `PostStatus`)
- Create: `backend/tests/posts/test_posts_list.py`

**Interfaces:**
- Consumes: `_is_editor(user)` (existing), `TranslationStatus` (Task 1), `TranslationOut.status` naming (Task 4), `auth_if_match` (Task 3).
- Produces:
  - Schemas: `TranslationSummary(locale: str, title: str, slug: str, status: TranslationStatus)`; `PostSummary(id: uuid.UUID, status: PostStatus, category_id: int, author_id: uuid.UUID, updated_at: datetime, published_at: datetime | None, translations: list[TranslationSummary])`; `PostListOut(items: list[PostSummary], total: int, limit: int, offset: int)`.
  - `service.list_posts(session: AsyncSession, user: User, *, status: PostStatus | None = None, author_id: uuid.UUID | None = None, category_id: int | None = None, locale: str | None = None, q: str | None = None, limit: int = 20, offset: int = 0) -> tuple[list[Post], int]`.
  - Route `GET /api/posts?status=&author_id=&category_id=&locale=&q=&limit=&offset=` (any staff). Reporters are always restricted to `author_id = self` (an `author_id` for someone else therefore returns nothing). `locale` keeps posts that have a translation in that locale; `q` is a case-insensitive substring match on a translation title (within `locale` when both are given), with `%`, `_` and `\` matched literally; blank `q` is ignored. Order `updated_at DESC, id DESC`. `limit` 1–100 (default 20), `offset` ≥ 0, `q` ≤ 200 chars; violations → 422 `VALIDATION_ERROR`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/posts/test_posts_list.py`:

```python
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, make_category, make_user


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def create(client, user, category, title="बाढी समाचार", locale="ne"):
    r = await client.post(
        "/api/posts",
        json={"locale": locale, "title": title, "content_json": doc("x"), "category_id": category.id},
        headers=auth_header(user),
    )
    assert r.status_code == 201
    return r.json()


async def list_posts(client, user, **params):
    r = await client.get("/api/posts", params=params, headers=auth_header(user))
    assert r.status_code == 200, r.text
    return r.json()


def ids(page: dict) -> list[str]:
    return [item["id"] for item in page["items"]]


async def test_reporter_sees_only_own_posts(client, session):
    alice = await make_user(session)
    bob = await make_user(session)
    cat = await make_category(session)
    a1 = await create(client, alice, cat)
    a2 = await create(client, alice, cat, title="मोरङ समाचार")
    b1 = await create(client, bob, cat, title="विराटनगर खबर")

    page = await list_posts(client, alice)
    assert page["total"] == 2
    assert set(ids(page)) == {a1["id"], a2["id"]}
    assert b1["id"] not in ids(page)

    snooping = await list_posts(client, alice, author_id=str(bob.id))
    assert snooping == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_editor_sees_all_newest_updated_first(client, session):
    alice = await make_user(session)
    bob = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    older = await create(client, alice, cat)
    newer = await create(client, bob, cat, title="मोरङ समाचार")

    assert ids(await list_posts(client, editor)) == [newer["id"], older["id"]]

    touched = await client.patch(
        f"/api/posts/{older['id']}",
        json={"locale": "ne", "title": "विराटनगर खबर"},
        headers=auth_if_match(alice, older["updated_at"]),
    )
    assert touched.status_code == 200
    assert ids(await list_posts(client, editor)) == [older["id"], newer["id"]]


async def test_items_are_compact_summaries(client, session):
    alice = await make_user(session)
    cat = await make_category(session)
    await create(client, alice, cat)
    item = (await list_posts(client, alice))["items"][0]
    assert set(item) == {"id", "status", "category_id", "author_id", "updated_at", "published_at", "translations"}
    assert item["translations"] == [
        {"locale": "ne", "title": "बाढी समाचार", "slug": "badhi-samachar", "status": "draft"}
    ]
    assert item["status"] == "draft" and item["published_at"] is None
    assert item["author_id"] == str(alice.id) and item["category_id"] == cat.id


async def test_filters_status_author_category_locale(client, session):
    alice = await make_user(session)
    bob = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    morang = await make_category(session)
    sunsari = await make_category(session, slug="sunsari", name_ne="सुनसरी", name_en="Sunsari")

    p1 = await create(client, alice, morang)
    live = await client.post(f"/api/posts/{p1['id']}/publish", headers=auth_if_match(editor, p1["updated_at"]))
    assert live.status_code == 200
    p2 = await create(client, bob, sunsari, title="मोरङ समाचार")
    with_en = await client.patch(
        f"/api/posts/{p2['id']}",
        json={"locale": "en", "title": "Flood in Biratnagar", "content_json": doc("x")},
        headers=auth_if_match(bob, p2["updated_at"]),
    )
    assert with_en.status_code == 200

    assert ids(await list_posts(client, editor, status="published")) == [p1["id"]]
    assert ids(await list_posts(client, editor, status="draft")) == [p2["id"]]
    assert ids(await list_posts(client, editor, author_id=str(bob.id))) == [p2["id"]]
    assert ids(await list_posts(client, editor, category_id=sunsari.id)) == [p2["id"]]
    assert ids(await list_posts(client, editor, locale="en")) == [p2["id"]]
    assert (await list_posts(client, editor, locale="ne"))["total"] == 2
    assert (await list_posts(client, editor, status="published", author_id=str(bob.id)))["total"] == 0


async def test_q_matches_title_case_insensitively(client, session):
    alice = await make_user(session)
    cat = await make_category(session)
    flood = await create(client, alice, cat, title="Flood in Biratnagar", locale="en")
    await create(client, alice, cat, title="Road news", locale="en")
    badhi = await create(client, alice, cat)  # "बाढी समाचार"

    assert ids(await list_posts(client, alice, q="flood")) == [flood["id"]]
    assert ids(await list_posts(client, alice, q="BIRAT")) == [flood["id"]]
    assert ids(await list_posts(client, alice, q="बाढी")) == [badhi["id"]]
    assert (await list_posts(client, alice, q="flood", locale="ne"))["total"] == 0
    assert (await list_posts(client, alice, q="   "))["total"] == 3  # blank q is ignored


async def test_q_escapes_like_wildcards(client, session):
    alice = await make_user(session)
    cat = await make_category(session)
    await create(client, alice, cat, title="Rain alert", locale="en")
    percent = await create(client, alice, cat, title="100% rain", locale="en")

    assert ids(await list_posts(client, alice, q="%")) == [percent["id"]]
    assert (await list_posts(client, alice, q="_"))["total"] == 0
    assert (await list_posts(client, alice, q="\\"))["total"] == 0


async def test_pagination_and_limits(client, session):
    alice = await make_user(session)
    cat = await make_category(session)
    created = [
        await create(client, alice, cat, title=title, locale="en")
        for title in ("Rain alert", "Road news", "Election result")
    ]

    first = await list_posts(client, alice, limit=2)
    assert (first["total"], first["limit"], first["offset"], len(first["items"])) == (3, 2, 0, 2)
    second = await list_posts(client, alice, limit=2, offset=2)
    assert (second["total"], second["offset"], len(second["items"])) == (3, 2, 1)
    assert ids(first) + ids(second) == [p["id"] for p in reversed(created)]
    assert (await list_posts(client, alice, offset=10))["items"] == []

    for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "bogus"}, {"locale": "fr"}, {"q": "x" * 201}):
        r = await client.get("/api/posts", params=bad, headers=auth_header(alice))
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_list_requires_login(client):
    r = await client.get("/api/posts")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "NOT_AUTHENTICATED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvpytest tests/posts/test_posts_list.py -v`
Expected: every test FAILS with 405 `METHOD_NOT_ALLOWED` (only `POST /api/posts` exists), except `test_list_requires_login`, which also FAILS (405 instead of 401).

- [ ] **Step 3: Add the list schemas**

Append to `backend/app/modules/posts/schemas.py`:

```python
class TranslationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    title: str
    slug: str
    status: TranslationStatus


class PostSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: PostStatus
    category_id: int
    author_id: uuid.UUID
    updated_at: datetime
    published_at: datetime | None
    translations: list[TranslationSummary]


class PostListOut(BaseModel):
    items: list[PostSummary]
    total: int
    limit: int
    offset: int
```

- [ ] **Step 4: Implement `list_posts` in the service**

In `backend/app/modules/posts/service.py`, change `from sqlalchemy import select` to

```python
from sqlalchemy import exists, func, select
```

Append:

```python
def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_posts(
    session: AsyncSession,
    user: User,
    *,
    status: PostStatus | None = None,
    author_id: uuid.UUID | None = None,
    category_id: int | None = None,
    locale: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Post], int]:
    conditions = []
    if not _is_editor(user):
        conditions.append(Post.author_id == user.id)  # reporters only ever see their own posts
    if author_id is not None:
        conditions.append(Post.author_id == author_id)
    if status is not None:
        conditions.append(Post.status == status)
    if category_id is not None:
        conditions.append(Post.category_id == category_id)

    translation_conditions = []
    if locale is not None:
        translation_conditions.append(PostTranslation.locale == locale)
    q = q.strip() if q else None
    if q:
        translation_conditions.append(PostTranslation.title.ilike(f"%{_escape_like(q)}%", escape="\\"))
    if translation_conditions:
        conditions.append(exists().where(PostTranslation.post_id == Post.id, *translation_conditions))

    total = await session.scalar(select(func.count()).select_from(Post).where(*conditions))
    posts = await session.scalars(
        select(Post)
        .where(*conditions)
        .order_by(Post.updated_at.desc(), Post.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(posts.all()), total or 0
```

- [ ] **Step 5: Add the route**

In `backend/app/modules/posts/router.py`:

change `from fastapi import APIRouter, Depends, Header` to

```python
from fastapi import APIRouter, Depends, Header, Query
```

change the models and schemas imports to

```python
from app.modules.posts.models import Post, PostStatus
from app.modules.posts.schemas import Locale, PostCreate, PostListOut, PostOut, PostSummary, PostUpdate
```

and add this route directly after `create_post` (before `GET /{post_id}`):

```python
@router.get("", response_model=PostListOut)
async def list_posts(
    status: PostStatus | None = None,
    author_id: uuid.UUID | None = None,
    category_id: int | None = None,
    locale: Locale | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
) -> PostListOut:
    posts, total = await service.list_posts(
        session, user,
        status=status, author_id=author_id, category_id=category_id, locale=locale, q=q,
        limit=limit, offset=offset,
    )
    return PostListOut(
        items=[PostSummary.model_validate(p) for p in posts], total=total, limit=limit, offset=offset
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uvpytest tests/posts/test_posts_list.py -v`
Expected: all 8 PASS.

- [ ] **Step 7: Run the full suite**

Run: `uvpytest -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/modules/posts/schemas.py app/modules/posts/service.py app/modules/posts/router.py tests/posts/test_posts_list.py
git commit -m "feat(posts): GET /api/posts list with filters, search and pagination

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Missing M1 tests — read/submit permissions and renderer quote-breaking

These tests pin behaviour that already exists (they are the "tests to add first" from the M1 follow-ups that no earlier task covers). They are expected to PASS on first run; Step 3 proves each one can fail by temporarily breaking the code it guards.

**Files:**
- Modify: `backend/tests/posts/test_posts_api.py` (append)
- Modify: `backend/tests/posts/test_render.py` (append)

**Interfaces:**
- Consumes: `GET /api/posts/{id}` (403 `FORBIDDEN_ROLE` for a non-author reporter, 404 `POST_NOT_FOUND` for an unknown id), `POST /api/posts/{id}/submit` (403 for a non-author reporter), `render_html(doc: dict) -> str`.
- Produces: tests only; no production code changes.

- [ ] **Step 1: Write the tests**

In `backend/tests/posts/test_posts_api.py`, add `import uuid` as the first import line, then append:

```python
async def test_get_post_permissions(client, session):
    author = await make_user(session)
    other = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = (await create(client, author, cat)).json()
    url = f"/api/posts/{post['id']}"

    own = await client.get(url, headers=auth_header(author))
    assert own.status_code == 200
    assert own.json()["id"] == post["id"]

    denied = await client.get(url, headers=auth_header(other))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN_ROLE"

    assert (await client.get(url, headers=auth_header(editor))).status_code == 200

    unknown = await client.get(f"/api/posts/{uuid.uuid4()}", headers=auth_header(editor))
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "POST_NOT_FOUND"


async def test_non_author_reporter_cannot_submit(client, session):
    author = await make_user(session)
    other = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, author, cat)).json()

    r = await client.post(f"/api/posts/{post['id']}/submit", headers=auth_header(other))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN_ROLE"

    still = await client.get(f"/api/posts/{post['id']}", headers=auth_header(author))
    assert still.json()["status"] == "draft"
```

Append to `backend/tests/posts/test_render.py` (add `from html.parser import HTMLParser` at the top of the file):

```python
class _StartTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def start_tags(markup: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = _StartTags()
    parser.feed(markup)
    parser.close()
    return parser.tags


def test_quote_in_alt_cannot_break_out_of_attribute():
    hostile = '" onerror="alert(1)'
    out = render_html(doc({"type": "image", "attrs": {"src": "https://cdn.mawapress.com/a.webp", "alt": hostile}}))
    img = next(attrs for tag, attrs in start_tags(out) if tag == "img")
    assert set(img) == {"src", "alt", "loading"}
    assert img["alt"] == hostile  # survives as text, inside the attribute


def test_quote_in_href_cannot_add_attributes():
    hostile = 'https://mawapress.com/" onclick="alert(1)'
    out = render_html(doc(para(text("x", {"type": "link", "attrs": {"href": hostile}}))))
    link = next(attrs for tag, attrs in start_tags(out) if tag == "a")
    assert set(link) == {"href", "target", "rel"}
    assert link["href"] == hostile


def test_markup_in_caption_stays_text():
    hostile = "</figcaption><script>alert(1)</script>"
    out = render_html(doc({"type": "image", "attrs": {"src": "https://cdn.mawapress.com/a.webp", "caption": hostile}}))
    assert [tag for tag, _ in start_tags(out)] == ["figure", "img", "figcaption"]
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
```

- [ ] **Step 2: Run the tests**

Run: `uvpytest tests/posts/test_posts_api.py tests/posts/test_render.py -v`
Expected: all PASS.

- [ ] **Step 3: Prove the renderer tests bite (temporary mutation, then revert)**

In `backend/app/modules/posts/render.py`, inside the `case "image":` branch, temporarily change
`alt="{html.escape(_str(attrs.get("alt")) or "")}"` to `alt="{_str(attrs.get("alt")) or ""}"`.

Run: `uvpytest tests/posts/test_render.py::test_quote_in_alt_cannot_break_out_of_attribute -v`
Expected: FAIL (`onerror` appears as a separate attribute, or nh3 drops it and `img["alt"]` no longer equals the hostile string).

Revert the mutation:

```bash
git checkout -- app/modules/posts/render.py
```

Run: `uvpytest tests/posts/test_render.py -v`
Expected: all PASS. `git status` must show `render.py` unmodified.

- [ ] **Step 4: Run the full suite**

Run: `uvpytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/posts/test_posts_api.py tests/posts/test_render.py
git commit -m "test: cover post read/submit permissions and renderer quote-breaking

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Coverage map (scope → task)

| Scope item | Task |
|---|---|
| `post_translations.status` / `published_at` migration, backfill, enum dropped on downgrade | 1 |
| `publish_post` publishes translations present at that moment | 4 |
| `POST /api/posts/{id}/translations/{locale}/publish` (editor, If-Match, outbox `post.updated`, cache invalidation) | 4 |
| Public post served only when post **and** translation published; `alternates` published-only | 5 |
| hreflang (SEO refresh) published-only | 4 |
| `GET /api/posts` filters, pagination, reporter scoping, compact items, newest-updated first | 6 |
| Publish requires If-Match (428/412) | 3 |
| JWT requires exp/sub/iat; bad `sub` → 401 | 2 |
| Login timing oracle (dummy argon2 verify) | 2 |
| Concurrent-create slug collision retry (max 3, then 409 `SLUG_TAKEN`) | 3 |
| Server defaults (posts.status, posts.created_at/updated_at, post_translations.seo_auto, users.created_at, users.is_active) | 1 |
| Invalid public locale → 404 `POST_NOT_FOUND` | 5 |
| Tests: GET permissions (author 200 / other reporter 403 / unknown 404) | 7 |
| Tests: non-author submit 403 | 7 |
| Tests: malformed If-Match → 412 | 3 |
| Tests: expired / wrong-signature / deactivated-user token → 401 | 2 |
| Tests: publish invalidates public cache | 5 (and 4 for translation publish) |
| Tests: en locale + alternates on public endpoint | 5 |
| Tests: renderer quote-breaking in alt / href / caption | 7 |

## Decisions recorded in this plan

- **Slug freeze is per translation.** A draft translation on a live post may still change its slug when its title changes; the slug freezes when that translation is published. This follows from "translation stays a draft until an editor publishes it" and keeps M1's rule for everything already public.
- **`publish_translation` order of checks:** post exists → If-Match → post published → translation exists → translation not already published. Re-publishing an already-published translation is a 409, not a silent no-op, so it never writes a redundant outbox event.
- **Outbox payload unchanged:** `slugs` still lists every translation's slug (draft ones included); the worker (M2b) treats a 404 revalidation as harmless.
- **Exhausted slug retries return 409 `SLUG_TAKEN`** (an error code already named in spec §9) instead of a 500.
- **Invalid locale on the posts editor route** (`/translations/fr/publish`) stays a 422 validation error; only the *public* route maps unknown locales to 404, because only public URLs are crawled.
