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
    too_long = await client.post(
        "/api/tags", json={"name_ne": "क", "name_en": "K", "slug": "a" * 81}, headers=auth_header(editor)
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "INVALID_SLUG"
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
