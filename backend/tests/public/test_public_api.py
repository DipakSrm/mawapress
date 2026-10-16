from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.cache import get_redis
from app.db.session import get_session
from app.main import create_app
from app.modules.public.service import post_cache_key
from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, make_category, make_user


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def published_post(client, session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    cat = await make_category(session)
    post = (await client.post(
        "/api/posts",
        json={"locale": "ne", "title": "बाढी समाचार", "content_json": doc("पानी"), "category_id": cat.id},
        headers=auth_header(editor),
    )).json()
    published = (await client.post(
        f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"])
    )).json()
    return editor, published


async def test_published_post_is_served_then_cached(client, session):
    await published_post(client, session)
    first = await client.get("/api/public/posts/ne/badhi-samachar")
    assert first.status_code == 200
    assert first.headers["x-cache"] == "MISS"
    assert first.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    body = first.json()
    assert body["title"] == "बाढी समाचार"
    assert body["author_name"] == "Sita Rai"
    assert body["category_slug"] == "morang"
    assert body["seo"]["json_ld"][0]["@type"] == "NewsArticle"

    second = await client.get("/api/public/posts/ne/badhi-samachar")
    assert second.headers["x-cache"] == "HIT"
    assert second.json() == body


async def test_draft_is_not_public(client, session):
    reporter = await make_user(session)
    cat = await make_category(session)
    draft = (await client.post(
        "/api/posts",
        json={"locale": "ne", "title": "गोप्य मस्यौदा", "content_json": doc("x"), "category_id": cat.id},
        headers=auth_header(reporter),
    )).json()
    r = await client.get(f"/api/public/posts/ne/{draft['translations'][0]['slug']}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "POST_NOT_FOUND"


async def test_editing_published_post_invalidates_cache(client, session):
    editor, published = await published_post(client, session)
    await client.get("/api/public/posts/ne/badhi-samachar")  # warm cache

    await client.patch(
        f"/api/posts/{published['id']}",
        json={"locale": "ne", "title": "विराटनगरमा भीषण बाढी"},
        headers={**auth_header(editor), "If-Match": published["updated_at"]},
    )
    r = await client.get("/api/public/posts/ne/badhi-samachar")
    assert r.headers["x-cache"] == "MISS"
    assert r.json()["title"] == "विराटनगरमा भीषण बाढी"


class DownRedis:
    async def get(self, *args, **kwargs):
        raise RedisConnectionError("redis down")

    set = delete = get


async def down_client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: DownRedis()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_public_get_survives_redis_outage(client, session):
    await published_post(client, session)
    async with await down_client(session) as down:
        r = await down.get("/api/public/posts/ne/badhi-samachar")
    assert r.status_code == 200
    assert r.json()["title"] == "बाढी समाचार"
    assert r.headers["x-cache"] == "MISS"


async def test_patch_survives_redis_outage(client, session):
    editor, published = await published_post(client, session)
    async with await down_client(session) as down:
        r = await down.patch(
            f"/api/posts/{published['id']}",
            json={"locale": "ne", "title": "विराटनगरमा भीषण बाढी"},
            headers={**auth_header(editor), "If-Match": published["updated_at"]},
        )
    assert r.status_code == 200
    assert r.json()["translations"][0]["title"] == "विराटनगरमा भीषण बाढी"


async def draft_post(client, editor, cat, title="बाढी समाचार"):
    r = await client.post(
        "/api/posts",
        json={"locale": "ne", "title": title, "content_json": doc("पानी"), "category_id": cat.id},
        headers=auth_header(editor),
    )
    assert r.status_code == 201
    return r.json()


async def add_english(client, editor, post, title="Flood in Biratnagar"):
    r = await client.patch(
        f"/api/posts/{post['id']}",
        json={"locale": "en", "title": title, "content_json": doc("It is raining")},
        headers=auth_if_match(editor, post["updated_at"]),
    )
    assert r.status_code == 200
    return r.json()


async def test_en_locale_and_alternates_when_both_published(client, session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    cat = await make_category(session)
    with_en = await add_english(client, editor, await draft_post(client, editor, cat))
    published = await client.post(
        f"/api/posts/{with_en['id']}/publish", headers=auth_if_match(editor, with_en["updated_at"])
    )
    assert published.status_code == 200

    en = await client.get("/api/public/posts/en/flood-in-biratnagar")
    assert en.status_code == 200
    body = en.json()
    assert body["locale"] == "en"
    assert body["title"] == "Flood in Biratnagar"
    assert body["content_html"] == "<p>It is raining</p>"
    assert body["alternates"] == {"ne": "badhi-samachar"}
    assert body["seo"]["hreflang"]["ne"].endswith("/ne/morang/badhi-samachar")
    assert body["seo"]["hreflang"]["x-default"].endswith("/ne/morang/badhi-samachar")
    assert body["seo"]["json_ld"][0]["inLanguage"] == "en"

    ne = await client.get("/api/public/posts/ne/badhi-samachar")
    assert ne.json()["alternates"] == {"en": "flood-in-biratnagar"}


async def test_draft_translation_on_live_post_is_hidden(client, session):
    editor, published = await published_post(client, session)
    await add_english(client, editor, published)  # autosaved half translation on a live post

    en = await client.get("/api/public/posts/en/flood-in-biratnagar")
    assert en.status_code == 404
    assert en.json()["error"]["code"] == "POST_NOT_FOUND"

    ne = await client.get("/api/public/posts/ne/badhi-samachar")
    assert ne.status_code == 200
    assert ne.json()["alternates"] == {}
    assert ne.json()["seo"]["hreflang"] == {}


async def test_publishing_translation_invalidates_cached_sibling(client, session):
    editor, published = await published_post(client, session)
    with_en = await add_english(client, editor, published)
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).headers["x-cache"] == "MISS"
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).headers["x-cache"] == "HIT"

    r = await client.post(
        f"/api/posts/{published['id']}/translations/en/publish",
        headers=auth_if_match(editor, with_en["updated_at"]),
    )
    assert r.status_code == 200

    ne = await client.get("/api/public/posts/ne/badhi-samachar")
    assert ne.headers["x-cache"] == "MISS"
    assert ne.json()["alternates"] == {"en": "flood-in-biratnagar"}
    en = await client.get("/api/public/posts/en/flood-in-biratnagar")
    assert en.status_code == 200
    assert en.json()["alternates"] == {"ne": "badhi-samachar"}


async def test_publish_invalidates_public_cache(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await draft_post(client, editor, cat)
    key = post_cache_key("ne", "badhi-samachar")
    await fake_redis.set(key, "stale entry from an earlier publication")

    r = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 200
    assert await fake_redis.get(key) is None

    served = await client.get("/api/public/posts/ne/badhi-samachar")
    assert served.headers["x-cache"] == "MISS"
    assert served.json()["title"] == "बाढी समाचार"


async def test_unknown_locale_is_404_envelope(client, session):
    await published_post(client, session)
    for locale in ("fr", "NE", "nep"):
        r = await client.get(f"/api/public/posts/{locale}/badhi-samachar")
        assert r.status_code == 404, locale
        assert r.json()["error"]["code"] == "POST_NOT_FOUND"
