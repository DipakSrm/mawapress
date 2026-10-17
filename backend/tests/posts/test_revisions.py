from sqlalchemy import func, select

from app.db.outbox import OutboxEvent
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


async def patch(client, user, post, **body):
    r = await client.patch(
        f"/api/posts/{post['id']}", json={"locale": "ne", **body}, headers=auth_if_match(user, post["updated_at"])
    )
    assert r.status_code == 200, r.text
    return r.json()


async def revisions(client, user, post):
    return await client.get(f"/api/posts/{post['id']}/revisions", headers=auth_header(user))


async def live_post(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    return editor, await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))


async def test_editing_a_published_translation_records_its_prior_state(client, session):
    editor, live = await live_post(client, session)
    await patch(client, editor, live, title="विराटनगरमा बाढी", seo_title="Custom")

    r = await revisions(client, editor, live)
    assert r.status_code == 200
    [rev] = r.json()
    assert (rev["locale"], rev["title"], rev["slug"]) == ("ne", "बाढी समाचार", "badhi-samachar")
    assert rev["content_json"] == doc("पानी परिरहेको छ")
    assert (rev["seo_title"], rev["seo_description"], rev["excerpt"]) == (None, None, None)
    assert rev["editor_id"] == str(editor.id)
    assert rev["created_at"]


async def test_no_revision_for_drafts_or_no_op_saves(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    draft = await create_post_via_api(client, editor, cat)
    draft = await patch(client, editor, draft, title="मस्यौदा")  # draft edit
    live = await publish_via_api(client, editor, draft)
    live = await patch(client, editor, live, title="मस्यौदा")  # same title: nothing changed
    with_en = await patch(client, editor, live, locale="en", title="Draft English", content_json=doc("x"))
    await patch(client, editor, with_en, locale="en", title="Draft English 2")  # draft translation edit
    assert (await revisions(client, editor, live)).json() == []


async def test_revisions_newest_first_and_visible_to_author_and_editors(client, session):
    reporter = await make_user(session)
    other = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish_via_api(client, editor, await create_post_via_api(client, reporter, cat))
    first = await patch(client, editor, live, title="पहिलो सम्पादन")
    await patch(client, editor, first, title="दोस्रो सम्पादन")

    r = await revisions(client, reporter, live)
    assert r.status_code == 200
    assert [rev["title"] for rev in r.json()] == ["पहिलो सम्पादन", "बाढी समाचार"]
    assert (await revisions(client, other, live)).status_code == 403
    only_en = await client.get(f"/api/posts/{live['id']}/revisions", params={"locale": "en"}, headers=auth_header(editor))
    assert only_en.json() == []


async def test_restore_is_a_versioned_save(client, session):
    editor, live = await live_post(client, session)
    edited = await patch(client, editor, live, title="गलत शीर्षक", content_json=doc("गलत"))
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).json()["title"] == "गलत शीर्षक"  # warm cache
    [rev] = (await revisions(client, editor, live)).json()

    r = await client.post(
        f"/api/posts/{live['id']}/revisions/{rev['id']}/restore", headers=auth_if_match(editor, edited["updated_at"])
    )
    assert r.status_code == 200
    tr = r.json()["translations"][0]
    assert (tr["title"], tr["slug"], tr["content_html"]) == ("बाढी समाचार", "badhi-samachar", "<p>पानी परिरहेको छ</p>")
    assert r.json()["updated_at"] != edited["updated_at"]

    # The restore recorded the state it replaced, emitted post.updated and cleared the public cache.
    assert [x["title"] for x in (await revisions(client, editor, live)).json()] == ["गलत शीर्षक", "बाढी समाचार"]
    updates = await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.topic == "post.updated"))
    assert updates == 2
    public = await client.get("/api/public/posts/ne/badhi-samachar")
    assert public.headers["x-cache"] == "MISS"
    assert public.json()["title"] == "बाढी समाचार"


async def test_restore_guards(client, session):
    reporter = await make_user(session)
    editor, live = await live_post(client, session)
    edited = await patch(client, editor, live, title="नयाँ")
    [rev] = (await revisions(client, editor, live)).json()
    url = f"/api/posts/{live['id']}/revisions/{rev['id']}/restore"

    assert (await client.post(url, headers=auth_header(editor))).status_code == 428
    assert (await client.post(url, headers=auth_if_match(editor, live["updated_at"]))).status_code == 412
    assert (await client.post(url, headers=auth_if_match(reporter, edited["updated_at"]))).status_code == 403

    other = await publish_via_api(
        client, editor, await create_post_via_api(client, editor, await make_category(session, slug="sports"), title="अर्को")
    )
    wrong_post = await client.post(
        f"/api/posts/{other['id']}/revisions/{rev['id']}/restore", headers=auth_if_match(editor, other["updated_at"])
    )
    assert wrong_post.status_code == 404
    assert wrong_post.json()["error"]["code"] == "REVISION_NOT_FOUND"
    missing = await client.post(
        f"/api/posts/{live['id']}/revisions/999999/restore", headers=auth_if_match(editor, edited["updated_at"])
    )
    assert missing.status_code == 404
