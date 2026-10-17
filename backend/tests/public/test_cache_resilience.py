from app.modules.public.service import (
    FEED_GEN_KEY,
    categories_cache_key,
    home_cache_key,
    post_cache_key,
    redirect_cache_key,
)
from app.modules.users.models import Role
from tests.factories import create_post_via_api, make_category, make_user, publish_via_api

OLD_SHAPE = '{"title": "from an older deploy"}'


async def test_old_shape_post_entry_is_a_cache_miss(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))
    await fake_redis.set(post_cache_key("ne", "badhi-samachar"), OLD_SHAPE)
    r = await client.get("/api/public/posts/ne/badhi-samachar")
    assert r.status_code == 200
    assert r.json()["title"] == "बाढी समाचार"
    assert r.headers["X-Cache"] == "MISS"
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).headers["X-Cache"] == "HIT"


async def test_old_shape_feed_entries_are_cache_misses(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))
    gen = await fake_redis.get(FEED_GEN_KEY) or "0"
    await fake_redis.set(home_cache_key(gen, "ne"), OLD_SHAPE)
    await fake_redis.set(categories_cache_key(gen), "not json at all")
    home = await client.get("/api/public/home", params={"locale": "ne"})
    assert home.status_code == 200
    assert home.headers["X-Cache"] == "MISS"
    tree = await client.get("/api/public/categories")
    assert tree.status_code == 200
    assert [c["slug"] for c in tree.json()] == ["morang"]


async def test_old_shape_redirect_entry_is_a_cache_miss(client, fake_redis):
    await fake_redis.set(redirect_cache_key("/ne/a/b"), OLD_SHAPE)
    r = await client.get("/api/public/redirects/resolve", params={"path": "/ne/a/b"})
    assert r.status_code == 404  # no redirect row: answered from the database, not a 500


async def test_offset_is_capped_on_search_and_category_feed(client, session):
    assert (await client.get("/api/public/search", params={"q": "flood", "locale": "ne", "offset": 1001})).status_code == 422
    assert (await client.get("/api/public/category/morang", params={"locale": "ne", "offset": 1001})).status_code == 422
    ok = await client.get("/api/public/search", params={"q": "flood", "locale": "ne", "offset": 1000})
    assert ok.status_code == 200
