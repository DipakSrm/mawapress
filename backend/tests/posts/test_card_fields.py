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
