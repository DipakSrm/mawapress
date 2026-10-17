import os
import subprocess
import sys
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic(env, *args):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


def test_alembic_upgrade_head_on_empty_database():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        env = {**os.environ, "MAWA_DATABASE_URL": pg.get_connection_url()}
        result = _alembic(env, "upgrade", "head")
    assert result.returncode == 0, result.stderr


def test_models_match_migrations():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        env = {**os.environ, "MAWA_DATABASE_URL": pg.get_connection_url()}
        upgrade = _alembic(env, "upgrade", "head")
        check = _alembic(env, "check")
    assert upgrade.returncode == 0, upgrade.stderr
    assert check.returncode == 0, check.stdout + check.stderr


def test_alembic_downgrade_then_upgrade_round_trip():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        env = {**os.environ, "MAWA_DATABASE_URL": pg.get_connection_url()}
        results = [
            _alembic(env, "upgrade", "head"),
            _alembic(env, "downgrade", "base"),
            _alembic(env, "upgrade", "head"),
        ]
    for result in results:
        assert result.returncode == 0, result.stderr


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
