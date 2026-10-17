import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import update

from app.core.cache import get_redis
from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import get_session
from app.main import create_app
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
from app.modules.public.stats import hour_bucket_key, pending_key
from app.modules.users.models import Role
from app.worker.settings import WorkerSettings
from app.worker.views import flush_views
from tests.factories import auth_header, auth_if_match, doc, make_category, make_user


async def live_post(client, session, *, title="बाढी समाचार", cat=None, en_title=None, en_published=True):
    """A published post; optionally with an English translation (published, or left as a draft)."""
    editor = await make_user(session, role=Role.editor)
    cat = cat or await make_category(session, slug=f"c-{uuid.uuid4().hex[:6]}")
    post = (await client.post(
        "/api/posts",
        json={"locale": "ne", "title": title, "content_json": doc("पानी"), "category_id": cat.id},
        headers=auth_header(editor),
    )).json()
    if en_title:
        r = await client.patch(
            f"/api/posts/{post['id']}",
            json={"locale": "en", "title": en_title, "content_json": doc("water")},
            headers=auth_if_match(editor, post["updated_at"]),
        )
        assert r.status_code == 200, r.text
        post = r.json()
    r = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 200, r.text
    post = r.json()
    if en_title and not en_published:
        await session.execute(
            update(PostTranslation)
            .where(PostTranslation.post_id == uuid.UUID(post["id"]), PostTranslation.locale == "en")
            .values(status=TranslationStatus.draft)
        )
        await session.flush()
    return uuid.UUID(post["id"])


async def view(client, post_id, locale="ne", ip=None):
    headers = {"x-forwarded-for": ip} if ip else {}
    return await client.post("/api/public/stats/view", json={"post_id": str(post_id), "locale": locale}, headers=headers)


@pytest.fixture
def proxied(monkeypatch):
    monkeypatch.setattr(get_settings(), "trust_proxy", True)


async def pending(redis, post_id) -> int:
    return int(await redis.get(pending_key(post_id)) or 0)


async def test_view_is_counted_once_per_client(client, session, fake_redis, proxied):
    pid = await live_post(client, session)
    assert (await view(client, pid, ip="1.1.1.1")).status_code == 204
    assert (await view(client, pid, ip="1.1.1.1")).status_code == 204
    assert await pending(fake_redis, pid) == 1
    assert (await view(client, pid, ip="2.2.2.2")).status_code == 204
    assert await pending(fake_redis, pid) == 2
    keys = [k async for k in fake_redis.scan_iter(match=f"view:{pid}:*")]
    assert len(keys) == 2
    assert all("1.1.1.1" not in k and "2.2.2.2" not in k for k in keys)  # raw IPs are never stored
    assert 0 < await fake_redis.ttl(keys[0]) <= 1800


async def test_dedup_lapses_with_its_ttl(client, session, fake_redis, proxied):
    pid = await live_post(client, session)
    await view(client, pid, ip="1.1.1.1")
    key = [k async for k in fake_redis.scan_iter(match=f"view:{pid}:*")][0]
    await fake_redis.delete(key)  # what TTL expiry does
    await view(client, pid, ip="1.1.1.1")
    assert await pending(fake_redis, pid) == 2


async def test_view_also_scores_the_hourly_trending_bucket(client, session, fake_redis):
    pid = await live_post(client, session)
    await view(client, pid)
    key = hour_bucket_key("ne", utcnow())
    assert await fake_redis.zscore(key, str(pid)) == 1
    assert 24 * 3600 < await fake_redis.ttl(key) <= 25 * 3600


async def test_uncountable_posts_return_204_without_counting(client, session, fake_redis):
    reporter = await make_user(session)
    cat = await make_category(session)
    draft = (await client.post(
        "/api/posts", json={"locale": "ne", "title": "मस्यौदा", "content_json": doc("x"), "category_id": cat.id},
        headers=auth_header(reporter),
    )).json()
    draft_id = uuid.UUID(draft["id"])
    assert (await view(client, draft_id)).status_code == 204
    assert (await view(client, uuid.uuid4())).status_code == 204
    mixed = await live_post(client, session, en_title="Flood", en_published=False)
    assert (await view(client, mixed, "en")).status_code == 204
    assert await pending(fake_redis, mixed) == 0
    assert (await view(client, mixed, "ne")).status_code == 204  # the published locale does count
    assert await pending(fake_redis, mixed) == 1
    assert await pending(fake_redis, draft_id) == 0
    assert [k async for k in fake_redis.scan_iter(match="trending:en:*")] == []


async def test_bad_body_is_rejected(client):
    r = await client.post("/api/public/stats/view", json={"post_id": str(uuid.uuid4()), "locale": "fr"})
    assert r.status_code == 422


class FailingPipeline:
    def __getattr__(self, name):
        return lambda *args, **kwargs: self  # commands queue up, as on a real pipeline

    async def execute(self):
        raise RedisConnectionError("redis down")


class FailingRedis:
    """Every call raises like a dropped connection."""

    def pipeline(self, *args, **kwargs):
        return FailingPipeline()

    def __getattr__(self, name):
        async def fail(*args, **kwargs):
            raise RedisConnectionError("redis down")

        return fail


async def down_app_client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: FailingRedis()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_view_survives_redis_down(client, session):
    pid = await live_post(client, session)
    async with await down_app_client(session) as down:
        assert (await view(down, pid)).status_code == 204


async def test_view_rate_limit_is_60_per_minute(client):
    pid = uuid.uuid4()
    codes = [(await view(client, pid)).status_code for _ in range(61)]
    assert codes[:60] == [204] * 60
    assert codes[60] == 429


def make_ctx(session, redis) -> dict:
    @asynccontextmanager
    async def factory():
        yield session

    return {"session_factory": factory, "cache_redis": redis}


async def test_flush_moves_counts_into_db_and_clears_pending(client, session, fake_redis, proxied):
    a = await live_post(client, session)
    b = await live_post(client, session)
    for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        await view(client, a, ip=ip)
    await view(client, b, ip="1.1.1.1")
    assert await flush_views(make_ctx(session, fake_redis)) == 4
    assert (await session.get(Post, a, populate_existing=True)).view_count == 3
    assert (await session.get(Post, b, populate_existing=True)).view_count == 1
    assert [k async for k in fake_redis.scan_iter(match="views:pending:*")] == []
    await view(client, a, ip="4.4.4.4")
    await flush_views(make_ctx(session, fake_redis))
    assert (await session.get(Post, a, populate_existing=True)).view_count == 4  # adds, never overwrites


async def test_flush_ignores_garbage_and_unknown_posts(session, fake_redis):
    await fake_redis.set("views:pending:not-a-uuid", 5)
    await fake_redis.set(pending_key(uuid.uuid4()), 2)  # a post deleted since
    assert await flush_views(make_ctx(session, fake_redis)) == 0
    assert [k async for k in fake_redis.scan_iter(match="views:pending:*")] == []


async def test_failed_flush_keeps_counts(client, session, fake_redis):
    pid = await live_post(client, session)
    await fake_redis.set(pending_key(pid), 7)

    @asynccontextmanager
    async def broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    assert await flush_views({"session_factory": broken, "cache_redis": fake_redis}) == 0
    assert await pending(fake_redis, pid) == 7
    await fake_redis.incr(pending_key(pid))  # a view arriving after the failure adds on top
    assert await flush_views(make_ctx(session, fake_redis)) == 8
    assert (await session.get(Post, pid, populate_existing=True)).view_count == 8


async def trending(client, locale="ne", **params):
    return await client.get("/api/public/trending", params={"locale": locale, **params})


async def seed_views(redis, locale, pid, n, when=None):
    await redis.zincrby(hour_bucket_key(locale, when or utcnow()), n, str(pid))


async def test_trending_orders_by_recent_views_and_respects_locale_and_limit(client, session, fake_redis):
    a = await live_post(client, session, title="क", en_title="Alpha")
    b = await live_post(client, session, title="ख", en_title="Beta")
    c = await live_post(client, session, title="ग", en_title="Gamma")
    await seed_views(fake_redis, "ne", a, 2)
    await seed_views(fake_redis, "ne", b, 9, utcnow() - timedelta(hours=5))
    await seed_views(fake_redis, "ne", c, 5, utcnow() - timedelta(hours=23))
    await seed_views(fake_redis, "ne", a, 100, utcnow() - timedelta(hours=30))  # outside the window
    await seed_views(fake_redis, "en", c, 1)
    r = await trending(client)
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [str(b), str(c), str(a)]
    assert r.json()[0]["title"] == "ख"
    assert [x["id"] for x in (await trending(client, limit=2)).json()] == [str(b), str(c)]
    en = (await trending(client, "en")).json()
    assert [x["id"] for x in en] == [str(c)] and en[0]["title"] == "Gamma"
    assert [k async for k in fake_redis.scan_iter(match="trending:tmp:*")] == []


async def test_trending_skips_posts_no_longer_public_and_is_cached(client, session, fake_redis):
    a = await live_post(client, session)
    b = await live_post(client, session)
    await seed_views(fake_redis, "ne", a, 9)
    await seed_views(fake_redis, "ne", b, 1)
    await session.execute(update(Post).where(Post.id == a).values(status=PostStatus.archived))
    await session.flush()
    first = await trending(client)
    assert [x["id"] for x in first.json()] == [str(b)]
    assert first.headers["x-cache"] == "MISS"
    again = await trending(client)
    assert again.headers["x-cache"] == "HIT" and again.json() == first.json()


async def test_trending_validates_input(client):
    assert (await trending(client, limit=0)).status_code == 422
    assert (await trending(client, limit=21)).status_code == 422
    assert (await trending(client, "fr")).status_code == 404


async def test_trending_falls_back_to_view_count_when_redis_is_down(client, session):
    old = await live_post(client, session, title="पुरानो")
    low = await live_post(client, session, title="कम")
    high = await live_post(client, session, title="धेरै")
    await session.execute(
        update(Post).where(Post.id == old).values(view_count=999, published_at=utcnow() - timedelta(days=8))
    )
    await session.execute(update(Post).where(Post.id == low).values(view_count=3))
    await session.execute(update(Post).where(Post.id == high).values(view_count=50))
    await session.flush()
    async with await down_app_client(session) as down:
        r = await trending(down)
        assert r.status_code == 200
        assert [x["id"] for x in r.json()] == [str(high), str(low)]


async def test_admin_outputs_expose_view_count(client, session):
    pid = await live_post(client, session)
    await session.execute(update(Post).where(Post.id == pid).values(view_count=12))
    await session.flush()
    editor = await make_user(session, role=Role.editor)
    one = await client.get(f"/api/posts/{pid}", headers=auth_header(editor))
    assert one.json()["view_count"] == 12
    listing = await client.get("/api/posts", headers=auth_header(editor))
    assert [i["view_count"] for i in listing.json()["items"] if i["id"] == str(pid)] == [12]


def test_flush_views_is_registered_as_a_timed_cron():
    jobs = {c.name: c for c in WorkerSettings.cron_jobs}
    job = jobs["cron:flush_views"]
    assert job.coroutine is flush_views and job.second == 0 and job.timeout_s <= 55
