from datetime import datetime

from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, make_category, make_user


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def create_ne(client, user, category, title="बाढी समाचार"):
    r = await client.post(
        "/api/posts",
        json={"locale": "ne", "title": title, "content_json": doc("पानी"), "category_id": category.id},
        headers=auth_header(user),
    )
    assert r.status_code == 201
    return r.json()


async def add_en(client, user, post, title="Flood in Biratnagar"):
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": title, "content_json": doc("It is raining")},
        headers=auth_if_match(user, post["updated_at"]),
    )
    assert r.status_code == 200
    return r.json()


async def publish(client, editor, post):
    r = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 200
    return r.json()


def by_locale(post: dict) -> dict[str, dict]:
    return {t["locale"]: t for t in post["translations"]}


async def test_publish_publishes_translations_present_at_that_moment(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await add_en(client, editor, await create_ne(client, editor, cat))
    assert {t["status"] for t in post["translations"]} == {"draft"}
    assert all(t["published_at"] is None for t in post["translations"])

    live = await publish(client, editor, post)
    trs = by_locale(live)
    assert trs["ne"]["status"] == trs["en"]["status"] == "published"
    published_at = datetime.fromisoformat(live["published_at"])
    assert datetime.fromisoformat(trs["ne"]["published_at"]) == published_at
    assert datetime.fromisoformat(trs["en"]["published_at"]) == published_at


async def test_translation_added_to_live_post_stays_draft_until_published(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish(client, editor, await create_ne(client, editor, cat))

    with_en = await add_en(client, editor, live)
    trs = by_locale(with_en)
    assert trs["en"]["status"] == "draft" and trs["en"]["published_at"] is None
    assert trs["ne"]["seo_auto"]["hreflang"] == {}  # draft English is not advertised

    r = await client.post(
        f"/api/posts/{live['id']}/translations/en/publish",
        headers=auth_if_match(editor, with_en["updated_at"]),
    )
    assert r.status_code == 200
    body = r.json()
    trs = by_locale(body)
    assert trs["en"]["status"] == "published" and trs["en"]["published_at"] is not None
    assert body["updated_at"] != with_en["updated_at"]
    assert set(trs["ne"]["seo_auto"]["hreflang"]) == {"ne", "en", "x-default"}
    assert trs["ne"]["seo_auto"]["hreflang"]["en"].endswith("/en/morang/flood-in-biratnagar")
    assert trs["en"]["seo_auto"]["hreflang"]["ne"].endswith("/ne/morang/badhi-samachar")

    events = (await session.scalars(
        select(OutboxEvent).where(OutboxEvent.topic == "post.updated").order_by(OutboxEvent.id)
    )).all()
    assert len(events) == 2  # one for the PATCH on the live post, one for the translation publish
    assert events[-1].payload["slugs"] == {"ne": "badhi-samachar", "en": "flood-in-biratnagar"}


async def test_translation_publish_guards(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)

    draft = await add_en(client, editor, await create_ne(client, editor, cat))
    not_live = await client.post(
        f"/api/posts/{draft['id']}/translations/en/publish", headers=auth_if_match(editor, draft["updated_at"])
    )
    assert not_live.status_code == 409
    assert not_live.json()["error"]["code"] == "INVALID_TRANSITION"

    live = await publish(client, editor, await create_ne(client, editor, cat, title="मोरङ समाचार"))
    url_en = f"/api/posts/{live['id']}/translations/en/publish"
    url_ne = f"/api/posts/{live['id']}/translations/ne/publish"

    denied = await client.post(url_en, headers=auth_if_match(reporter, live["updated_at"]))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN_ROLE"

    missing = await client.post(url_en, headers=auth_header(editor))
    assert missing.status_code == 428

    stale = await client.post(url_en, headers=auth_if_match(editor, "2020-01-01T00:00:00+00:00"))
    assert stale.status_code == 412

    no_en = await client.post(url_en, headers=auth_if_match(editor, live["updated_at"]))
    assert no_en.status_code == 404
    assert no_en.json()["error"]["code"] == "TRANSLATION_NOT_FOUND"

    already = await client.post(url_ne, headers=auth_if_match(editor, live["updated_at"]))
    assert already.status_code == 409
    assert already.json()["error"]["code"] == "INVALID_TRANSITION"

    bad_locale = await client.post(
        f"/api/posts/{live['id']}/translations/fr/publish", headers=auth_if_match(editor, live["updated_at"])
    )
    assert bad_locale.status_code == 422


async def test_draft_translation_slug_follows_title_while_published_one_is_frozen(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish(client, editor, await create_ne(client, editor, cat))
    with_en = await add_en(client, editor, live, title="Draft English")
    assert by_locale(with_en)["en"]["slug"] == "draft-english"

    retitled = await client.patch(
        f"/api/posts/{live['id']}",
        json={"locale": "en", "title": "Late English"},
        headers=auth_if_match(editor, with_en["updated_at"]),
    )
    assert by_locale(retitled.json())["en"]["slug"] == "late-english"

    ne_retitled = await client.patch(
        f"/api/posts/{live['id']}",
        json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers=auth_if_match(editor, retitled.json()["updated_at"]),
    )
    ne = by_locale(ne_retitled.json())["ne"]
    assert ne["title"] == "नयाँ शीर्षक"
    assert ne["slug"] == "badhi-samachar"
