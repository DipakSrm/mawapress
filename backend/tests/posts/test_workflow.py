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
        f"/api/posts/{in_review['id']}/send-back", json={"note": "  Add a second source  "},
        headers=auth_if_match(editor, in_review["updated_at"]),
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

    not_in_review = await client.post(
        f"/api/posts/{draft['id']}/send-back", headers=auth_if_match(editor, draft["updated_at"])
    )
    assert not_in_review.status_code == 409
    assert not_in_review.json()["error"]["code"] == "INVALID_TRANSITION"

    submitted = await submit(client, reporter, draft)
    url = f"/api/posts/{draft['id']}/send-back"
    assert (await client.post(url, headers=auth_if_match(reporter, submitted["updated_at"]))).status_code == 403
    missing = await client.post(url, headers=auth_header(editor))
    assert missing.status_code == 428
    assert (await client.post(url, headers=auth_if_match(editor, draft["updated_at"]))).status_code == 412
    no_body = await client.post(url, headers=auth_if_match(editor, submitted["updated_at"]))
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
