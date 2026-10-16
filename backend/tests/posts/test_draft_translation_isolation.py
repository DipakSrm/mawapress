from datetime import datetime

from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.posts import service
from app.modules.public.service import post_cache_key
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, make_category, make_user
from tests.posts.test_translation_publish import add_en, by_locale, create_ne, doc, publish

def iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


NE_URL = "/api/public/posts/ne/badhi-samachar"


async def live_post_with_warm_ne(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await publish(client, editor, await create_ne(client, editor, cat))
    warm = await client.get(NE_URL)
    assert warm.status_code == 200
    assert await fake_redis.exists(post_cache_key("ne", "badhi-samachar")) == 1
    return editor, live, warm.json()


async def patch(client, editor, post, **body):
    r = await client.patch(f"/api/posts/{post['id']}", json=body, headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 200, r.text
    return r.json()


async def updated_events(session):
    return (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()


async def test_draft_translation_autosave_on_live_post_leaves_public_side_alone(client, session, fake_redis):
    editor, live, _ = await live_post_with_warm_ne(client, session, fake_redis)
    with_en = await add_en(client, editor, live)  # adds a draft English translation
    autosaved = await patch(client, editor, with_en, locale="en", content_json=doc("more rain"))
    await patch(client, editor, autosaved, locale="en", title="Flood update", seo_title="Flood SEO")

    assert await updated_events(session) == []
    assert await fake_redis.exists(post_cache_key("ne", "badhi-samachar")) == 1


async def test_editing_published_translation_still_emits_event_and_invalidates_cache(client, session, fake_redis):
    editor, live, _ = await live_post_with_warm_ne(client, session, fake_redis)
    await patch(client, editor, live, locale="ne", content_json=doc("नयाँ पानी"))

    assert len(await updated_events(session)) == 1
    assert await fake_redis.exists(post_cache_key("ne", "badhi-samachar")) == 0


async def test_draft_autosave_does_not_move_public_modified_dates_but_editing_ne_does(client, session, fake_redis):
    editor, live, before = await live_post_with_warm_ne(client, session, fake_redis)
    with_en = await add_en(client, editor, live)
    await patch(client, editor, with_en, locale="en", content_json=doc("more rain"))

    await fake_redis.flushall()  # force a fresh read from the database
    after = (await client.get(NE_URL)).json()
    assert after["updated_at"] == before["updated_at"]
    assert after["seo"]["json_ld"][0]["dateModified"] == before["seo"]["json_ld"][0]["dateModified"]

    current = (await client.get(f"/api/posts/{live['id']}", headers=auth_header(editor))).json()
    await patch(client, editor, current, locale="ne", title="नयाँ शीर्षक")
    await fake_redis.flushall()
    edited = (await client.get(NE_URL)).json()
    assert datetime.fromisoformat(edited["updated_at"]) > datetime.fromisoformat(before["updated_at"])
    assert edited["seo"]["json_ld"][0]["dateModified"] > before["seo"]["json_ld"][0]["dateModified"]


async def test_translation_published_later_shows_its_own_published_at(client, session, fake_redis):
    editor, live, before = await live_post_with_warm_ne(client, session, fake_redis)
    with_en = await add_en(client, editor, live)
    r = await client.post(
        f"/api/posts/{live['id']}/translations/en/publish", headers=auth_if_match(editor, with_en["updated_at"])
    )
    assert r.status_code == 200
    en_published_at = by_locale(r.json())["en"]["published_at"]

    en = (await client.get("/api/public/posts/en/flood-in-biratnagar")).json()
    assert en["published_at"] == en_published_at
    assert iso(en["seo"]["json_ld"][0]["datePublished"]) == iso(en_published_at)
    assert datetime.fromisoformat(en_published_at) > datetime.fromisoformat(live["published_at"])

    await fake_redis.flushall()
    ne = (await client.get(NE_URL)).json()
    assert ne["published_at"] == live["published_at"] == before["published_at"]
    assert iso(ne["seo"]["json_ld"][0]["datePublished"]) == iso(live["published_at"])


async def test_adding_translation_retries_slug_collision(client, session, fake_redis, monkeypatch):
    editor, live, _ = await live_post_with_warm_ne(client, session, fake_redis)
    other = await publish(client, editor, await create_ne(client, editor, await make_category(session, slug="x"), title="x"))
    first_en = await add_en(client, editor, other, title="Flood in Biratnagar")  # takes the English slug
    real = service.unique_slug
    calls: list[str] = []

    async def racing(session_, locale, base, exclude_id=None):
        calls.append(base)
        if len(calls) == 1:
            return base
        return await real(session_, locale, base, exclude_id)

    monkeypatch.setattr(service, "unique_slug", racing)
    body = await add_en(client, editor, live, title="Flood in Biratnagar")
    assert first_en["translations"][-1]["slug"] == "flood-in-biratnagar"
    assert by_locale(body)["en"]["slug"] == "flood-in-biratnagar-2"
    assert calls == ["flood-in-biratnagar", "flood-in-biratnagar"]


async def test_retitling_draft_translation_retries_then_gives_409(client, session, fake_redis, monkeypatch):
    editor, live, _ = await live_post_with_warm_ne(client, session, fake_redis)
    with_en = await add_en(client, editor, live, title="Draft English")
    other = await publish(client, editor, await create_ne(client, editor, await make_category(session, slug="x"), title="x"))
    await add_en(client, editor, other, title="Taken Title")
    real = service.unique_slug
    calls: list[str] = []

    async def racing(session_, locale, base, exclude_id=None):
        calls.append(base)
        if len(calls) == 1:
            return base
        return await real(session_, locale, base, exclude_id)

    monkeypatch.setattr(service, "unique_slug", racing)
    retitled = await patch(client, editor, with_en, locale="en", title="Taken Title")
    assert by_locale(retitled)["en"]["slug"] == "taken-title-2"
    assert len(calls) == 2

    calls.clear()

    async def always_taken(session_, locale, base, exclude_id=None):
        calls.append(base)
        return "taken-title"

    monkeypatch.setattr(service, "unique_slug", always_taken)
    r = await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "en", "title": "Another Title"},
        headers=auth_if_match(editor, retitled["updated_at"]),
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SLUG_TAKEN"
    assert len(calls) == 3
