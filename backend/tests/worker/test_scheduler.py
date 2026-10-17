import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.posts import service
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
from app.modules.public.service import FEED_GEN_KEY, post_cache_key
from app.modules.taxonomy.models import Category
from app.modules.users.models import Role, User
from app.worker.scheduler import SCHEDULER_TIMEOUT_SECONDS, publish_due_posts
from app.worker.settings import WorkerSettings
from tests.factories import auth_if_match, create_post_via_api, doc, make_category, make_user


def make_ctx(session, redis) -> dict:
    @asynccontextmanager
    async def factory():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

    return {"session_factory": factory, "cache_redis": redis}


async def scheduled_post(client, session, *, due: bool, title="बाढी समाचार", cat=None, extra_locale=False):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = cat or await make_category(session, slug=f"c-{uuid.uuid4().hex[:6]}")
    post = await create_post_via_api(client, reporter, cat, title=title)
    if extra_locale:
        r = await client.patch(
            f"/api/posts/{post['id']}", json={"locale": "en", "title": "Flood news", "content_json": doc("It is raining")},
            headers=auth_if_match(editor, post["updated_at"]),
        )
        assert r.status_code == 200, r.text
        post = r.json()
    r = await client.post(
        f"/api/posts/{post['id']}/schedule",
        json={"scheduled_at": (utcnow() + timedelta(hours=1)).isoformat()},
        headers=auth_if_match(editor, post["updated_at"]),
    )
    assert r.status_code == 200, r.text
    row = await session.get(Post, uuid.UUID(post["id"]))
    when = utcnow() - timedelta(minutes=5 if due else -30)
    row.scheduled_at = when
    await session.commit()
    return row, when


async def test_publishes_only_due_posts_and_their_translations(client, session, fake_redis):
    due, when = await scheduled_post(client, session, due=True, extra_locale=True)
    later, later_when = await scheduled_post(client, session, due=False)
    draft_reporter = await make_user(session)
    draft = await create_post_via_api(client, draft_reporter, await make_category(session, slug="other"))

    key = post_cache_key("ne", due.translations[0].slug)
    await fake_redis.set(key, "stale")
    gen_before = int(await fake_redis.get(FEED_GEN_KEY) or 0)

    assert await publish_due_posts(make_ctx(session, fake_redis)) == 1

    await session.refresh(due)
    assert due.status == PostStatus.published
    assert due.published_at == when
    assert due.scheduled_at is None
    assert {t.locale for t in due.translations} == {"ne", "en"}
    for t in due.translations:
        assert t.status == TranslationStatus.published
        assert t.published_at == when
        assert t.updated_at >= when
    assert due.updated_at >= when

    await session.refresh(later)
    assert later.status == PostStatus.scheduled and later.scheduled_at == later_when
    assert all(t.status == TranslationStatus.draft for t in later.translations)
    assert (await session.get(Post, uuid.UUID(draft["id"]))).status == PostStatus.draft

    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.published"))).all()
    assert len(events) == 1
    assert events[0].payload["post_id"] == str(due.id)
    assert events[0].payload["slugs"].keys() == {"ne", "en"}

    assert await fake_redis.get(key) is None
    assert int(await fake_redis.get(FEED_GEN_KEY)) == gen_before + 1


async def test_idempotent_when_run_twice(client, session, fake_redis):
    await scheduled_post(client, session, due=True)
    ctx = make_ctx(session, fake_redis)
    assert await publish_due_posts(ctx) == 1
    assert await publish_due_posts(ctx) == 0
    assert len((await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.published"))).all()) == 1


async def test_one_failing_post_does_not_block_others(client, session, fake_redis, monkeypatch):
    bad, _ = await scheduled_post(client, session, due=True)
    good, _ = await scheduled_post(client, session, due=True)
    bad_id = bad.id
    real = service.publish_due_post

    async def flaky(s, post_id):
        if post_id == bad_id:
            raise RuntimeError("boom")
        return await real(s, post_id)

    monkeypatch.setattr(service, "publish_due_post", flaky)
    assert await publish_due_posts(make_ctx(session, fake_redis)) == 1
    await session.refresh(good)
    await session.refresh(bad)
    assert good.status == PostStatus.published
    assert bad.status == PostStatus.scheduled


async def test_skip_locked_under_concurrency(engine, fake_redis):
    """A post whose row another transaction holds is skipped, then published on the next run."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        user = await make_user(s, role=Role.editor)
        cat = await make_category(s, slug=f"lock-{uuid.uuid4().hex[:6]}")
        post = Post(author_id=user.id, category_id=cat.id, status=PostStatus.scheduled,
                    scheduled_at=utcnow() - timedelta(minutes=1))
        s.add(post)
        await s.flush()
        s.add(PostTranslation(post_id=post.id, locale="ne", title="t", slug=f"lock-{uuid.uuid4().hex[:8]}",
                              content_json={"type": "doc", "content": []}, content_html="<p>x</p>"))
        await s.commit()
        post_id, user_id, cat_id = post.id, user.id, cat.id

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as fresh:
            yield fresh

    ctx = {"session_factory": factory, "cache_redis": fake_redis}
    try:
        holder = AsyncSession(engine)
        await holder.execute(select(Post).where(Post.id == post_id).with_for_update())
        try:
            assert await publish_due_posts(ctx) == 0
        finally:
            await holder.rollback()
            await holder.close()
        async with factory() as check:
            assert (await check.get(Post, post_id)).status == PostStatus.scheduled
        assert await publish_due_posts(ctx) == 1
        assert await publish_due_posts(ctx) == 0
        async with factory() as check:
            assert (await check.get(Post, post_id)).status == PostStatus.published
    finally:
        async with AsyncSession(engine) as clean:
            await clean.execute(delete(OutboxEvent).where(OutboxEvent.payload["post_id"].astext == str(post_id)))
            await clean.execute(delete(Post).where(Post.id == post_id))
            await clean.execute(delete(Category).where(Category.id == cat_id))
            await clean.execute(delete(User).where(User.id == user_id))
            await clean.commit()


def test_cron_registered_with_explicit_timeout():
    jobs = {c.coroutine: c for c in WorkerSettings.cron_jobs}
    job = jobs[publish_due_posts]
    assert job.second == {0, 30}
    assert job.timeout_s == SCHEDULER_TIMEOUT_SECONDS < 30
