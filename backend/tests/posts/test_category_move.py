from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.public.service import FEED_GEN_KEY
from app.modules.seo.models import Redirect
from app.modules.users.models import Role
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    make_category,
    make_user,
    publish_via_api,
)

OLD = "/ne/morang/badhi-samachar"
NEW = "/ne/sports/badhi-samachar"


async def move(client, user, post, category_id):
    return await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "ne", "category_id": category_id},
        headers=auth_if_match(user, post["updated_at"]),
    )


async def test_editor_moves_a_live_post(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    old_cat = await make_category(session)
    new_cat = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports")
    live = await publish_via_api(client, editor, await create_post_via_api(client, editor, old_cat))
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).json()["category_slug"] == "morang"  # warm
    assert (await client.get(f"/api/public/redirects/resolve", params={"path": OLD})).status_code == 404  # warm marker
    gen_before = int(await fake_redis.get(FEED_GEN_KEY) or 0)

    r = await move(client, editor, live, new_cat.id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category_id"] == new_cat.id
    assert body["translations"][0]["seo_auto"]["canonical"].endswith(NEW)

    assert (await client.get("/api/public/posts/ne/badhi-samachar")).json()["category_slug"] == "sports"
    resolved = await client.get("/api/public/redirects/resolve", params={"path": OLD})
    assert resolved.status_code == 200
    assert resolved.json() == {"to_path": NEW, "code": 301}
    rows = (await session.scalars(select(Redirect))).all()
    assert [(x.from_path, x.to_path) for x in rows] == [(OLD, NEW)]
    assert int(await fake_redis.get(FEED_GEN_KEY)) == gen_before + 1

    [event] = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()
    assert event.payload["category_id"] == new_cat.id
    assert event.payload["redirects"] == [{"from": OLD, "to": NEW}]


async def test_move_redirects_every_published_translation(client, session):
    editor = await make_user(session, role=Role.editor)
    old_cat = await make_category(session)
    new_cat = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports")
    live = await publish_via_api(client, editor, await create_post_via_api(client, editor, old_cat))
    r = await client.patch(
        f"/api/posts/{live['id']}",
        json={"locale": "en", "title": "Flood news", "content_json": live["translations"][0]["content_json"]},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    en = (await client.post(
        f"/api/posts/{live['id']}/translations/en/publish", headers=auth_if_match(editor, r.json()["updated_at"])
    )).json()
    assert (await move(client, editor, en, new_cat.id)).status_code == 200
    rows = sorted((x.from_path, x.to_path) for x in (await session.scalars(select(Redirect))).all())
    assert rows == [("/en/morang/flood-news", "/en/sports/flood-news"), (OLD, NEW)]


async def test_unknown_category_is_422_and_changes_nothing(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))
    r = await client.patch(
        f"/api/posts/{live['id']}",
        json={"locale": "ne", "category_id": 999999, "title": "बदलिएको"},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CATEGORY_NOT_FOUND"
    again = (await client.get(f"/api/posts/{live['id']}", headers=auth_header(editor))).json()
    assert again["translations"][0]["title"] == "बाढी समाचार"
    assert again["category_id"] == cat.id


async def test_reporter_can_move_only_their_own_draft(client, session):
    reporter = await make_user(session)
    other = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    new_cat = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports")

    mine = await create_post_via_api(client, reporter, cat)
    moved = await move(client, reporter, mine, new_cat.id)
    assert moved.status_code == 200
    assert moved.json()["category_id"] == new_cat.id
    assert (await session.scalars(select(Redirect))).all() == []  # a draft was never public

    theirs = await create_post_via_api(client, other, cat)
    assert (await move(client, reporter, theirs, new_cat.id)).status_code == 403

    live = await publish_via_api(client, editor, await create_post_via_api(client, reporter, cat))
    assert (await move(client, reporter, live, new_cat.id)).status_code == 403


async def test_category_can_be_deleted_once_its_posts_moved_out(client, session):
    editor = await make_user(session, role=Role.editor)
    old_cat = await make_category(session)
    new_cat = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports")
    live = await publish_via_api(client, editor, await create_post_via_api(client, editor, old_cat))
    blocked = await client.delete(f"/api/categories/{old_cat.id}", headers=auth_header(editor))
    assert blocked.status_code == 409
    assert "another category" in blocked.json()["error"]["message"]
    assert (await move(client, editor, live, new_cat.id)).status_code == 200
    assert (await client.delete(f"/api/categories/{old_cat.id}", headers=auth_header(editor))).status_code == 204


async def test_slug_and_category_changed_together(client, session):
    editor = await make_user(session, role=Role.editor)
    old_cat = await make_category(session)
    new_cat = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports")
    live = await publish_via_api(client, editor, await create_post_via_api(client, editor, old_cat))
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 200  # warm cache

    r = await client.patch(
        f"/api/posts/{live['id']}",
        json={"locale": "ne", "slug": "flood-news", "category_id": new_cat.id},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    assert r.status_code == 200, r.text
    final = "/ne/sports/flood-news"
    assert r.json()["translations"][0]["seo_auto"]["canonical"].endswith(final)

    rows = (await session.scalars(select(Redirect))).all()
    assert {(x.from_path, x.to_path) for x in rows} == {(OLD, final), ("/ne/morang/flood-news", final)}
    assert all(x.from_path != x.to_path for x in rows)

    public = await client.get("/api/public/posts/ne/flood-news")
    assert public.status_code == 200
    assert public.json()["category_slug"] == "sports"
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 404
    for old in (OLD, "/ne/morang/flood-news"):
        resolved = await client.get("/api/public/redirects/resolve", params={"path": old})
        assert resolved.json() == {"to_path": final, "code": 301}
