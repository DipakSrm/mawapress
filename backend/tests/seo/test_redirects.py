from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.public.service import NOT_FOUND_MARKER, post_cache_key, redirect_cache_key
from app.modules.seo.models import Redirect
from app.modules.users.models import Role
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    down_client,
    make_category,
    make_user,
    publish_via_api,
)

OLD = "/ne/morang/badhi-samachar"


async def live_post(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    return editor, cat, await publish_via_api(client, editor, await create_post_via_api(client, editor, cat))


async def change_slug(client, user, post, slug, locale="ne"):
    return await client.patch(
        f"/api/posts/{post['id']}", json={"locale": locale, "slug": slug}, headers=auth_if_match(user, post["updated_at"])
    )


async def redirect_rows(session):
    rows = (await session.scalars(select(Redirect).order_by(Redirect.from_path))).all()
    return [(r.from_path, r.to_path, r.code) for r in rows]


async def resolve(client, path):
    return await client.get("/api/public/redirects/resolve", params={"path": path})


async def test_slug_change_moves_the_article_and_writes_a_301(client, session):
    editor, cat, live = await live_post(client, session)
    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 200  # warm cache

    r = await change_slug(client, editor, live, "flood-news")
    assert r.status_code == 200
    tr = r.json()["translations"][0]
    assert tr["slug"] == "flood-news"
    assert tr["seo_auto"]["canonical"].endswith("/ne/morang/flood-news")
    assert await redirect_rows(session) == [(OLD, "/ne/morang/flood-news", 301)]

    assert (await client.get("/api/public/posts/ne/badhi-samachar")).status_code == 404
    assert (await client.get("/api/public/posts/ne/flood-news")).status_code == 200

    [event] = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()
    assert event.payload["slugs"] == {"ne": "flood-news"}
    assert event.payload["redirect"] == {"from": OLD, "to": "/ne/morang/flood-news"}

    [rev] = (await client.get(f"/api/posts/{live['id']}/revisions", headers=auth_header(editor))).json()["items"]
    assert rev["slug"] == "badhi-samachar"


async def test_redirect_chains_collapse(client, session):
    editor, cat, live = await live_post(client, session)
    b = (await change_slug(client, editor, live, "flood-news")).json()
    c = await change_slug(client, editor, b, "flood-update")
    assert c.status_code == 200
    assert await redirect_rows(session) == [
        (OLD, "/ne/morang/flood-update", 301),
        ("/ne/morang/flood-news", "/ne/morang/flood-update", 301),
    ]


async def test_slug_change_back_never_leaves_a_self_redirect(client, session):
    editor, cat, live = await live_post(client, session)
    b = (await change_slug(client, editor, live, "flood-news")).json()
    back = await change_slug(client, editor, b, "badhi-samachar")
    assert back.status_code == 200
    assert await redirect_rows(session) == [("/ne/morang/flood-news", OLD, 301)]
    assert (await resolve(client, OLD)).status_code == 404  # the article itself lives there again


async def test_same_slug_is_a_no_op(client, session):
    editor, cat, live = await live_post(client, session)
    r = await change_slug(client, editor, live, "badhi-samachar")
    assert r.status_code == 200
    assert await redirect_rows(session) == []


async def test_slug_change_guards(client, session):
    reporter = await make_user(session)
    editor, cat, live = await live_post(client, session)
    other = await publish_via_api(client, editor, await create_post_via_api(client, editor, cat, title="Flood news"))
    assert other["translations"][0]["slug"] == "flood-news"

    taken = await change_slug(client, editor, live, "flood-news")
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "SLUG_TAKEN"
    for bad in ("Flood News", "flood--news", "बाढी"):
        r = await change_slug(client, editor, live, bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "INVALID_SLUG"
    too_long = await change_slug(client, editor, live, "a" * 81)
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "INVALID_SLUG"

    own_draft = await create_post_via_api(client, reporter, cat, title="Reporter draft")
    denied = await change_slug(client, reporter, own_draft, "my-slug")
    assert denied.status_code == 403
    draft_slug = await change_slug(client, editor, own_draft, "my-slug")
    assert draft_slug.status_code == 422
    assert draft_slug.json()["error"]["code"] == "SLUG_NOT_EDITABLE"
    assert await redirect_rows(session) == []


async def test_resolve_returns_target_and_is_cached(client, session, fake_redis):
    editor, cat, live = await live_post(client, session)
    b = (await change_slug(client, editor, live, "flood-news")).json()

    first = await resolve(client, OLD)
    assert first.status_code == 200
    assert first.json() == {"to_path": "/ne/morang/flood-news", "code": 301}
    assert first.headers["x-cache"] == "MISS"
    assert first.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    assert (await resolve(client, OLD)).headers["x-cache"] == "HIT"

    await change_slug(client, editor, b, "flood-update")  # repoints OLD, so its cached answer must go
    assert (await resolve(client, OLD)).json() == {"to_path": "/ne/morang/flood-update", "code": 301}


async def test_resolve_404_is_cached_then_cleared_when_a_redirect_appears(client, session, fake_redis):
    editor, cat, live = await live_post(client, session)
    missing = await resolve(client, OLD)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "REDIRECT_NOT_FOUND"
    assert await fake_redis.get(redirect_cache_key(OLD)) == NOT_FOUND_MARKER

    await change_slug(client, editor, live, "flood-news")
    assert await fake_redis.get(redirect_cache_key(OLD)) is None
    assert await fake_redis.get(post_cache_key("ne", "badhi-samachar")) is None
    assert (await resolve(client, OLD)).status_code == 200


async def test_resolve_validates_path(client):
    bad = await resolve(client, "ne/morang/x")
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_PATH"
    too_long = await resolve(client, "/" + "a" * 300)
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "INVALID_PATH"
    assert (await resolve(client, "/" + "a" * 299)).status_code == 404  # 300 chars is still allowed


async def test_resolve_normalises_the_path_before_lookup(client, session):
    editor, cat, live = await live_post(client, session)
    await change_slug(client, editor, live, "flood-news")
    expected = {"to_path": "/ne/morang/flood-news", "code": 301}
    for variant in (
        OLD + "?utm_source=x&y=1",
        OLD + "#section",
        OLD + "?a=1#frag",
        "/ne//morang///badhi-samachar",
        OLD + "/",
        "/NE/morang/badhi-samachar",
        "/Ne//morang/badhi-samachar/?q=1",
    ):
        r = await resolve(client, variant)
        assert r.status_code == 200, variant
        assert r.json() == expected, variant


async def test_resolve_lowercases_only_the_locale_segment(client, session):
    editor, cat, live = await live_post(client, session)
    await change_slug(client, editor, live, "flood-news")
    assert (await resolve(client, "/ne/Morang/badhi-samachar")).status_code == 404
    assert (await resolve(client, "/ne/morang/Badhi-Samachar")).status_code == 404


async def test_resolve_removes_only_one_trailing_slash_and_keeps_root(client, fake_redis):
    for path in ("/", "/ne", "/ne/morang", "/ne/morang/a/b", "/xx/morang/a", "/ne/morang/a_b", "/ne/morang/ a"):
        r = await resolve(client, path)
        assert r.status_code == 404, path
        assert r.json()["error"]["code"] == "REDIRECT_NOT_FOUND"
    assert await fake_redis.keys("public:redirect:*") == []  # nothing off-pattern is cached


async def test_resolve_caches_a_well_formed_miss_under_the_normalised_path(client, fake_redis):
    assert (await resolve(client, "/NE//morang/missing/?x=1")).status_code == 404
    assert await fake_redis.get(redirect_cache_key("/ne/morang/missing")) == NOT_FOUND_MARKER


async def test_resolve_survives_redis_outage(client, session):
    editor, cat, live = await live_post(client, session)
    await change_slug(client, editor, live, "flood-news")
    async with await down_client(session) as down:
        r = await down.get("/api/public/redirects/resolve", params={"path": OLD})
    assert r.status_code == 200
    assert r.json()["to_path"] == "/ne/morang/flood-news"
