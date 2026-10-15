from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.users.models import Role
from tests.factories import auth_header, make_category, make_user


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def create(client, user, category, title="बाढी समाचार", locale="ne", body="पानी परिरहेको छ"):
    return await client.post(
        "/api/posts",
        json={"locale": locale, "title": title, "content_json": doc(body), "category_id": category.id},
        headers=auth_header(user),
    )


async def test_reporter_creates_draft_with_slug_html_and_seo(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    r = await create(client, reporter, cat)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    tr = body["translations"][0]
    assert tr["slug"] == "badhi-samachar"
    assert tr["content_html"] == "<p>पानी परिरहेको छ</p>"
    assert tr["seo_auto"]["title"] == "बाढी समाचार | मावाप्रेस"
    assert tr["seo_auto"]["canonical"].endswith("/ne/morang/badhi-samachar")


async def test_duplicate_title_gets_numbered_slug(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    await create(client, reporter, cat)
    second = await create(client, reporter, cat)
    assert second.json()["translations"][0]["slug"] == "badhi-samachar-2"


async def test_unknown_category_is_422(client, session):
    reporter = await make_user(session)
    r = await client.post(
        "/api/posts",
        json={"locale": "ne", "title": "x", "content_json": doc("y"), "category_id": 999999},
        headers=auth_header(reporter),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CATEGORY_NOT_FOUND"


async def test_update_requires_current_if_match(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    url = f"/api/posts/{post['id']}"
    patch = {"locale": "ne", "title": "मोरङ समाचार"}

    missing = await client.patch(url, json=patch, headers=auth_header(reporter))
    assert missing.status_code == 428

    stale = await client.patch(url, json=patch, headers={**auth_header(reporter), "If-Match": "2020-01-01T00:00:00Z"})
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

    ok = await client.patch(url, json=patch, headers={**auth_header(reporter), "If-Match": post["updated_at"]})
    assert ok.status_code == 200
    assert ok.json()["translations"][0]["slug"] == "morang-samachar"
    assert ok.json()["updated_at"] != post["updated_at"]


async def test_adding_english_translation_links_hreflang(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": "Flood in Biratnagar", "content_json": doc("It is raining")},
        headers={**auth_header(reporter), "If-Match": post["updated_at"]},
    )
    assert r.status_code == 200
    ne, en = r.json()["translations"]
    assert en["slug"] == "flood-in-biratnagar"
    assert set(ne["seo_auto"]["hreflang"]) == {"ne", "en", "x-default"}
    assert en["seo_auto"]["hreflang"]["ne"].endswith("/ne/morang/badhi-samachar")


async def test_new_translation_needs_title_and_content(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": "Only title"},
        headers={**auth_header(reporter), "If-Match": post["updated_at"]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "TRANSLATION_INCOMPLETE"


async def test_reporter_cannot_edit_someone_elses_post(client, session):
    author = await make_user(session)
    other = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, author, cat)).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "ne", "title": "hack"},
        headers={**auth_header(other), "If-Match": post["updated_at"]},
    )
    assert r.status_code == 403


async def test_submit_then_editor_publishes_and_outbox_written(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()

    submitted = await client.post(f"/api/posts/{post['id']}/submit", headers=auth_header(reporter))
    assert submitted.json()["status"] == "in_review"
    again = await client.post(f"/api/posts/{post['id']}/submit", headers=auth_header(reporter))
    assert again.status_code == 409

    denied = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(reporter))
    assert denied.status_code == 403

    published = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None

    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.published"))).all()
    assert len(events) == 1
    assert events[0].payload["slugs"] == {"ne": "badhi-samachar"}


async def test_slug_is_frozen_after_publish(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    published = (await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers={**auth_header(editor), "If-Match": published["updated_at"]},
    )
    assert r.json()["translations"][0]["title"] == "नयाँ शीर्षक"
    assert r.json()["translations"][0]["slug"] == "badhi-samachar"


async def test_editing_published_post_writes_post_updated_event(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    published = (await client.post(f"/api/posts/{post['id']}/publish", headers=auth_header(editor))).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers={**auth_header(editor), "If-Match": published["updated_at"]},
    )
    assert r.status_code == 200
    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()
    assert len(events) == 1
    assert events[0].payload == {
        "post_id": post["id"],
        "category_id": cat.id,
        "slugs": {"ne": "badhi-samachar"},
    }


async def test_editing_draft_writes_no_post_updated_event(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    post = (await create(client, reporter, cat)).json()
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers={**auth_header(reporter), "If-Match": post["updated_at"]},
    )
    assert r.status_code == 200
    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()
    assert events == []


async def test_numbered_slug_stays_within_80_chars(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    for title in ("abcdefghi " * 7 + "abcdefghi", "a" * 79):
        first = (await create(client, reporter, cat, title=title)).json()["translations"][0]["slug"]
        second = (await create(client, reporter, cat, title=title)).json()["translations"][0]["slug"]
        third = (await create(client, reporter, cat, title=title)).json()["translations"][0]["slug"]
        assert len(first) == 79
        assert len(second) <= 80 and second.endswith("-2")
        assert len(third) <= 80 and third.endswith("-3")
        assert len({first, second, third}) == 3
