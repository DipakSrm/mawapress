from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree as ET

from sqlalchemy import update

from app.modules.media.models import Media
from app.modules.posts.models import Post, PostTranslation
from app.modules.users.models import Role
from tests.factories import auth_if_match, create_post_via_api, doc, make_category, make_user, publish_via_api

SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
XH = "{http://www.w3.org/1999/xhtml}"
NEWS = "{http://www.google.com/schemas/sitemap-news/0.9}"
DC = "{http://purl.org/dc/elements/1.1/}"
MEDIA = "{http://search.yahoo.com/mrss/}"
SITE = "https://mawapress.com"
CC = "public, s-maxage=300"


async def setup(session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    province = await make_category(session, slug="province-1", name_ne="प्रदेश १", name_en="Province 1", sort=1)
    morang = await make_category(session, slug="morang", parent_id=province.id)
    sports = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports", sort=2)
    return editor, province, morang, sports


async def live(client, editor, cat, title, locale="ne", **kw):
    post = await create_post_via_api(client, editor, cat, title=title, locale=locale, **kw)
    return await publish_via_api(client, editor, post)


async def add_en(client, editor, post, title="Flood in Biratnagar"):
    r = await client.patch(
        f"/api/posts/{post['id']}", json={"locale": "en", "title": title, "content_json": doc("rain")},
        headers=auth_if_match(editor, post["updated_at"]),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def set_published_at(session, slug, when):
    await session.execute(update(PostTranslation).where(PostTranslation.slug == slug).values(published_at=when))
    await session.flush()


def xml(r):
    assert r.status_code == 200, r.text
    return ET.fromstring(r.content)


async def test_index_lists_only_months_with_content(client, session):
    editor, _, morang, sports = await setup(session)
    await live(client, editor, morang, "Alpha")
    await live(client, editor, sports, "Bravo")
    await create_post_via_api(client, editor, sports, title="Draft one")  # never public
    await set_published_at(session, "alpha", datetime(2026, 3, 5, tzinfo=UTC))
    await set_published_at(session, "bravo", datetime(2026, 5, 9, tzinfo=UTC))

    r = await client.get("/api/public/sitemap.xml")
    assert r.headers["content-type"].startswith("application/xml")
    assert r.headers["cache-control"] == CC
    locs = [e.text for e in xml(r).iter(f"{SM}loc")]
    assert locs == [
        f"{SITE}/sitemaps/posts-2026-03.xml", f"{SITE}/sitemaps/posts-2026-05.xml", f"{SITE}/sitemaps/categories.xml",
    ]


async def test_monthly_sitemap_has_alternates_and_skips_drafts(client, session):
    editor, _, morang, sports = await setup(session)
    both = await live(client, editor, morang, "Alpha")
    both = await add_en(client, editor, both)
    r = await client.post(
        f"/api/posts/{both['id']}/translations/en/publish", headers=auth_if_match(editor, both["updated_at"])
    )
    assert r.status_code == 200
    solo = await live(client, editor, sports, "Bravo")
    await add_en(client, editor, solo, title="Bravo draft")  # draft English: excluded
    await live(client, editor, sports, "Elsewhere")
    now = datetime.now(UTC)
    month = now.strftime("%Y-%m")
    await set_published_at(session, "elsewhere", datetime(2020, 1, 2, tzinfo=UTC))
    for slug in ("alpha", "flood-in-biratnagar", "bravo"):
        await set_published_at(session, slug, now)

    root = xml(await client.get(f"/api/public/sitemaps/posts-{month}.xml"))
    urls = {u.find(f"{SM}loc").text: u for u in root.findall(f"{SM}url")}
    assert set(urls) == {
        f"{SITE}/ne/morang/alpha", f"{SITE}/en/morang/flood-in-biratnagar", f"{SITE}/ne/sports/bravo",
    }
    alt = {a.get("hreflang"): a.get("href") for a in urls[f"{SITE}/ne/morang/alpha"].findall(f"{XH}link")}
    assert alt == {
        "ne": f"{SITE}/ne/morang/alpha", "en": f"{SITE}/en/morang/flood-in-biratnagar",
        "x-default": f"{SITE}/ne/morang/alpha",
    }
    assert urls[f"{SITE}/ne/morang/alpha"].find(f"{SM}lastmod").text
    assert urls[f"{SITE}/ne/sports/bravo"].findall(f"{XH}link") == []


async def test_month_param_is_validated(client, session):
    await setup(session)
    for bad in ("2026-13", "2026-00", "abcd-01", "26-01", "2026-1"):
        assert (await client.get(f"/api/public/sitemaps/posts-{bad}.xml")).status_code == 404
    empty = await client.get("/api/public/sitemaps/posts-2019-01.xml")
    assert empty.status_code == 200 and xml(empty).findall(f"{SM}url") == []


async def test_categories_sitemap(client, session):
    await setup(session)
    root = xml(await client.get("/api/public/sitemaps/categories.xml"))
    locs = {e.text for e in root.iter(f"{SM}loc")}
    assert f"{SITE}/ne/morang" in locs and f"{SITE}/en/sports" in locs and len(locs) == 6


async def test_news_sitemap_respects_48h_window(client, session):
    editor, _, morang, sports = await setup(session)
    await live(client, editor, morang, "Fresh")
    await live(client, editor, sports, "Old")
    await live(client, editor, sports, "Fresh English <b> & co", locale="en")
    await set_published_at(session, "old", datetime.now(UTC) - timedelta(hours=49))
    await set_published_at(session, "fresh", datetime.now(UTC) - timedelta(hours=47))

    r = await client.get("/api/public/news-sitemap.xml")
    assert r.headers["cache-control"] == CC
    got = {i.find(f"{SM}loc").text: i for i in xml(r).findall(f"{SM}url")}
    assert set(got) == {f"{SITE}/ne/morang/fresh", f"{SITE}/en/sports/fresh-english-b-co"}
    ne = got[f"{SITE}/ne/morang/fresh"].find(f"{NEWS}news")
    assert ne.find(f"{NEWS}publication/{NEWS}name").text == "मावाप्रेस"
    assert ne.find(f"{NEWS}publication/{NEWS}language").text == "ne"
    assert ne.find(f"{NEWS}title").text == "Fresh"
    assert ne.find(f"{NEWS}publication_date").text
    en = got[f"{SITE}/en/sports/fresh-english-b-co"].find(f"{NEWS}news")
    assert en.find(f"{NEWS}publication/{NEWS}name").text == "MAWAPRESS"
    assert en.find(f"{NEWS}publication/{NEWS}language").text == "en"
    assert en.find(f"{NEWS}title").text == "Fresh English <b> & co"


async def test_rss_is_valid_and_escapes(client, session):
    editor, _, morang, _ = await setup(session)
    await live(client, editor, morang, 'Tom & "Jerry" <script> बाढी')
    await session.execute(update(PostTranslation).values(excerpt="a < b & c"))
    await session.flush()
    r = await client.get("/api/public/rss.xml", params={"locale": "ne"})
    assert r.headers["content-type"].startswith("application/rss+xml")
    assert r.headers["cache-control"] == CC
    root = xml(r)
    assert root.tag == "rss" and root.get("version") == "2.0"
    ch = root.find("channel")
    assert ch.find("title").text == "मावाप्रेस"
    assert ch.find("link").text == f"{SITE}/ne"
    assert ch.find("language").text == "ne"
    assert ch.find("description").text
    [item] = ch.findall("item")
    assert item.find("title").text == 'Tom & "Jerry" <script> बाढी'
    assert item.find("description").text == "a < b & c"
    link = item.find("link").text
    assert link.startswith(f"{SITE}/ne/morang/")
    guid = item.find("guid")
    assert guid.text == link and guid.get("isPermaLink") == "true"
    assert item.find(f"{DC}creator").text == "Sita Rai"
    parsed = datetime.strptime(item.find("pubDate").text, "%a, %d %b %Y %H:%M:%S %z")
    assert parsed.utcoffset() == timedelta(0)


async def test_rss_limited_to_50_and_per_locale(client, session):
    editor, _, morang, _ = await setup(session)
    for n in range(52):
        await live(client, editor, morang, f"Item {n}")
    await live(client, editor, morang, "English one", locale="en")
    ne = xml(await client.get("/api/public/rss.xml", params={"locale": "ne"}))
    assert len(ne.findall("channel/item")) == 50
    en = xml(await client.get("/api/public/rss.xml", params={"locale": "en"}))
    assert [i.find("title").text for i in en.findall("channel/item")] == ["English one"]


async def test_category_rss_includes_children(client, session):
    editor, _, morang, sports = await setup(session)
    await live(client, editor, morang, "Alpha")
    await live(client, editor, sports, "Charlie")
    root = xml(await client.get("/api/public/category/province-1/rss.xml", params={"locale": "ne"}))
    assert [i.find("title").text for i in root.findall("channel/item")] == ["Alpha"]
    assert root.find("channel/link").text == f"{SITE}/ne/province-1"
    assert root.find("channel/title").text == "प्रदेश १ | मावाप्रेस"


async def test_rss_featured_image_as_media_content(client, session):
    editor, _, morang, _ = await setup(session)
    post = await live(client, editor, morang, "Pic")
    media = Media(
        key="media/2026/10/x.jpg", mime="image/jpeg", size_bytes=10, width=10, height=10, uploader_id=editor.id
    )
    session.add(media)
    await session.flush()
    await session.execute(update(Post).where(Post.id == post["id"]).values(featured_media_id=media.id))
    await session.flush()
    root = xml(await client.get("/api/public/rss.xml", params={"locale": "ne"}))
    [content] = root.findall(f"channel/item/{MEDIA}content")
    assert content.get("url").startswith("http") and content.get("url").endswith("media/2026/10/x.jpg")
    assert content.get("medium") == "image"


async def test_404s(client, session):
    await setup(session)
    r = await client.get("/api/public/category/nope/rss.xml", params={"locale": "ne"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "CATEGORY_NOT_FOUND"
    for url in ("/api/public/rss.xml", "/api/public/category/sports/rss.xml"):
        r = await client.get(url, params={"locale": "fr"})
        assert r.status_code == 404 and r.json()["error"]["code"] == "LOCALE_NOT_FOUND"


async def test_cache_hit_then_publish_invalidates(client, session):
    editor, _, morang, sports = await setup(session)
    await live(client, editor, morang, "Alpha")
    urls = [
        ("/api/public/sitemap.xml", {}), ("/api/public/sitemaps/categories.xml", {}),
        ("/api/public/news-sitemap.xml", {}), ("/api/public/rss.xml", {"locale": "ne"}),
        ("/api/public/category/sports/rss.xml", {"locale": "ne"}),
    ]
    for url, params in urls:
        assert (await client.get(url, params=params)).headers["x-cache"] == "MISS", url
        assert (await client.get(url, params=params)).headers["x-cache"] == "HIT", url
    await live(client, editor, sports, "Bravo")
    for url, params in urls:
        assert (await client.get(url, params=params)).headers["x-cache"] == "MISS", url
    body = xml(await client.get("/api/public/rss.xml", params={"locale": "ne"}))
    assert len(body.findall("channel/item")) == 2


async def test_control_characters_do_not_break_xml(client, session):
    editor, _, morang, _ = await setup(session)
    await live(client, editor, morang, "Bad \x0b char")
    xml(await client.get("/api/public/rss.xml", params={"locale": "ne"}))
