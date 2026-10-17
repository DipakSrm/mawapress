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


async def newsroom(session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    province = await make_category(session, slug="province-1", name_ne="प्रदेश १", name_en="Province 1", sort=1)
    morang = await make_category(session, slug="morang", parent_id=province.id)
    sports = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports", sort=2)
    await make_category(session, slug="weather", name_ne="मौसम", name_en="Weather", sort=3)  # stays empty
    return editor, province, morang, sports


async def live(client, editor, cat, title, locale="ne"):
    return await publish_via_api(client, editor, await create_post_via_api(client, editor, cat, title=title, locale=locale))


def slugs(cards):
    return [c["slug"] for c in cards]


async def test_home_groups_latest_posts_by_top_level_category(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, morang, "Alpha")
    await live(client, editor, province, "Bravo")
    await live(client, editor, sports, "Charlie")
    await create_post_via_api(client, editor, sports, title="Delta")  # draft: never on the home page

    r = await client.get("/api/public/home", params={"locale": "ne"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    body = r.json()
    assert body["breaking"] == []
    blocks = body["categories"]
    assert [b["category"]["slug"] for b in blocks] == ["province-1", "sports"]  # sorted; empty "weather" omitted
    assert blocks[0]["category"] == {"id": province.id, "slug": "province-1", "name": "प्रदेश १", "seo_description": None}
    assert slugs(blocks[0]["posts"]) == ["bravo", "alpha"]  # newest first, children included
    assert blocks[0]["posts"][1]["category_slug"] == "morang"
    assert slugs(blocks[1]["posts"]) == ["charlie"]
    card = blocks[1]["posts"][0]
    assert set(card) == {"id", "title", "slug", "excerpt", "category_slug", "author_name", "published_at", "image"}
    assert card["author_name"] == "Sita Rai"


async def test_home_breaking_strip(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, morang, "Alpha")
    charlie = await live(client, editor, sports, "Charlie")
    r = await client.patch(
        f"/api/posts/{charlie['id']}", json={"locale": "ne", "is_breaking": True},
        headers=auth_if_match(editor, charlie["updated_at"]),
    )
    assert r.status_code == 200
    home = (await client.get("/api/public/home", params={"locale": "ne"})).json()
    assert slugs(home["breaking"]) == ["charlie"]


async def test_home_shows_latest_six_per_category(client, session):
    editor, province, morang, sports = await newsroom(session)
    for n in range(1, 8):
        await live(client, editor, sports, f"Sport {n}")
    home = (await client.get("/api/public/home", params={"locale": "ne"})).json()
    [block] = home["categories"]
    assert slugs(block["posts"]) == ["sport-7", "sport-6", "sport-5", "sport-4", "sport-3", "sport-2"]


async def test_home_cache_follows_public_changes_only(client, session):
    editor, province, morang, sports = await newsroom(session)
    alpha = await live(client, editor, morang, "Alpha")

    async def home():
        return await client.get("/api/public/home", params={"locale": "ne"})

    assert (await home()).headers["x-cache"] == "MISS"
    assert (await home()).headers["x-cache"] == "HIT"

    draft = await create_post_via_api(client, editor, sports, title="Bravo")
    edited = await client.patch(  # editing a draft is invisible to readers
        f"/api/posts/{draft['id']}", json={"locale": "ne", "title": "Bravo two"},
        headers=auth_if_match(editor, draft["updated_at"]),
    )
    assert (await home()).headers["x-cache"] == "HIT"

    await publish_via_api(client, editor, edited.json())
    after_publish = await home()
    assert after_publish.headers["x-cache"] == "MISS"
    assert [b["category"]["slug"] for b in after_publish.json()["categories"]] == ["province-1", "sports"]

    r = await client.post(f"/api/posts/{alpha['id']}/unpublish", headers=auth_if_match(editor, alpha["updated_at"]))
    assert r.status_code == 200
    after_unpublish = await home()
    assert after_unpublish.headers["x-cache"] == "MISS"
    assert [b["category"]["slug"] for b in after_unpublish.json()["categories"]] == ["sports"]


async def test_category_feed_includes_children_and_paginates(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, morang, "Alpha")
    await live(client, editor, province, "Bravo")
    await live(client, editor, sports, "Charlie")

    page1 = (await client.get("/api/public/category/province-1", params={"locale": "ne", "limit": 1})).json()
    assert page1["category"] == {"id": province.id, "slug": "province-1", "name": "प्रदेश १", "seo_description": None}
    assert (page1["total"], page1["limit"], page1["offset"], slugs(page1["items"])) == (2, 1, 0, ["bravo"])
    page2 = (await client.get("/api/public/category/province-1", params={"locale": "ne", "limit": 1, "offset": 1})).json()
    assert slugs(page2["items"]) == ["alpha"]

    child = (await client.get("/api/public/category/morang", params={"locale": "ne"})).json()
    assert (child["total"], slugs(child["items"])) == (1, ["alpha"])


async def test_category_feed_is_per_locale(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, morang, "Alpha")
    await live(client, editor, morang, "Flood in Biratnagar", locale="en")
    en = (await client.get("/api/public/category/province-1", params={"locale": "en"})).json()
    assert slugs(en["items"]) == ["flood-in-biratnagar"]
    assert en["category"]["name"] == "Province 1"


async def test_unknown_category_or_locale_is_404(client, session):
    await newsroom(session)
    missing = await client.get("/api/public/category/nope", params={"locale": "ne"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CATEGORY_NOT_FOUND"
    for url in ("/api/public/home", "/api/public/category/sports"):
        r = await client.get(url, params={"locale": "fr"})
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "LOCALE_NOT_FOUND"


async def test_category_feed_cache_is_cleared_by_category_edit(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, sports, "Charlie")
    url, params = "/api/public/category/sports", {"locale": "en"}
    assert (await client.get(url, params=params)).headers["x-cache"] == "MISS"
    assert (await client.get(url, params=params)).headers["x-cache"] == "HIT"

    r = await client.patch(f"/api/categories/{sports.id}", json={"name_en": "Sport"}, headers=auth_header(editor))
    assert r.status_code == 200
    after = await client.get(url, params=params)
    assert after.headers["x-cache"] == "MISS"
    assert after.json()["category"]["name"] == "Sport"


async def test_feeds_survive_redis_outage(client, session):
    editor, province, morang, sports = await newsroom(session)
    await live(client, editor, sports, "Charlie")
    async with await down_client(session) as down:
        home = await down.get("/api/public/home", params={"locale": "ne"})
        feed = await down.get("/api/public/category/sports", params={"locale": "ne"})
    assert home.status_code == 200 and home.headers["x-cache"] == "MISS"
    assert slugs(home.json()["categories"][0]["posts"]) == ["charlie"]
    assert feed.status_code == 200
    assert slugs(feed.json()["items"]) == ["charlie"]
