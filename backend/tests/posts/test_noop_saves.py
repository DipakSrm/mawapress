from sqlalchemy import func, select

from app.db.outbox import OutboxEvent
from app.modules.public.service import FEED_GEN_KEY, post_cache_key
from app.modules.users.models import Role
from tests.factories import (
    auth_if_match,
    create_post_via_api,
    make_category,
    make_tag,
    make_user,
    publish_via_api,
)


async def updated_events(session) -> int:
    return await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.topic == "post.updated"))


async def live_post(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    return editor, await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))


async def assert_public_side_untouched(client, session, fake_redis, editor, live, body):
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 200  # warm the cache
    gen_before = await fake_redis.get(FEED_GEN_KEY)
    events_before = await updated_events(session)

    r = await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "ne", **body}, headers=auth_if_match(editor, live["updated_at"])
    )
    assert r.status_code == 200, r.text

    assert await updated_events(session) == events_before
    assert await fake_redis.get(FEED_GEN_KEY) == gen_before
    assert await fake_redis.get(post_cache_key("ne", "badhi-samachar")) is not None


async def test_patch_that_changes_nothing_leaves_the_public_side_alone(client, session, fake_redis):
    editor, live = await live_post(client, session)
    same = {
        "title": live["translations"][0]["title"],
        "content_json": live["translations"][0]["content_json"],
        "seo_title": "",
        "excerpt": "",
        "is_breaking": False,
    }
    await assert_public_side_untouched(client, session, fake_redis, editor, live, same)


async def test_tags_only_patch_leaves_the_public_side_alone(client, session, fake_redis):
    editor, live = await live_post(client, session)
    tag = await make_tag(session)
    await assert_public_side_untouched(client, session, fake_redis, editor, live, {"tag_ids": [tag.id]})


async def test_real_change_still_emits_and_invalidates(client, session, fake_redis):
    editor, live = await live_post(client, session)
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 200
    gen_before = int(await fake_redis.get(FEED_GEN_KEY) or 0)
    r = await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    assert r.status_code == 200
    assert await updated_events(session) == 1
    assert int(await fake_redis.get(FEED_GEN_KEY)) == gen_before + 1
    assert await fake_redis.get(post_cache_key("ne", "badhi-samachar")) is None
