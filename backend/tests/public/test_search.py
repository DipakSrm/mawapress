from app.modules.users.models import Role
from tests.factories import auth_if_match, create_post_via_api, doc, make_category, make_user, publish_via_api


async def live_post(client, editor, cat, title, body, locale="en"):
    return await publish_via_api(client, editor, await create_post_via_api(client, editor, cat, title=title, body=body, locale=locale))


async def search(client, q, locale="en", **params):
    return await client.get("/api/public/search", params={"q": q, "locale": locale, **params})


async def test_search_ranks_title_matches_above_body_matches(client, session):
    editor = await make_user(session, role=Role.editor, name="Sita Rai")
    cat = await make_category(session)
    await live_post(client, editor, cat, "Market prices", "A flood of buyers at the haat")
    await live_post(client, editor, cat, "Flood relief in Biratnagar", "Water is rising")

    r = await search(client, "flood")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    body = r.json()
    assert body["total"] == 2
    assert [i["slug"] for i in body["items"]] == ["flood-relief-in-biratnagar", "market-prices"]
    first = body["items"][0]
    assert first["title"] == "Flood relief in Biratnagar"
    assert first["excerpt"] == "Water is rising"
    assert first["category_slug"] == "morang"
    assert first["author_name"] == "Sita Rai"
    assert first["published_at"] is not None
    assert first["image"] is None


async def test_search_nepali_and_typo_tolerant_title(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await live_post(client, editor, cat, "बाढी पीडितलाई राहत", "विराटनगरमा राहत वितरण", locale="ne")
    await live_post(client, editor, cat, "Flood relief in Biratnagar", "Water is rising")

    ne = await search(client, "बाढी", locale="ne")
    assert [i["slug"] for i in ne.json()["items"]] == ["badhi-piditlai-rahat"]
    typo = await search(client, "biratnagr")  # no exact lexeme; trigram word similarity on the title
    assert [i["slug"] for i in typo.json()["items"]] == ["flood-relief-in-biratnagar"]


async def test_search_only_returns_public_translations_in_that_locale(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await create_post_via_api(client, editor, cat, title="Flood draft", body="flood", locale="en")  # never published
    live_ne = await live_post(client, editor, cat, "बाढी", "पानी", locale="ne")
    r = await client.patch(  # English translation added to a live post stays a draft
        f"/api/posts/{live_ne['id']}", json={"locale": "en", "title": "Flood warning", "content_json": doc("flood")},
        headers=auth_if_match(editor, live_ne["updated_at"]),
    )
    assert r.status_code == 200
    archived = await live_post(client, editor, cat, "Flood archive", "old flood")
    await client.post(f"/api/posts/{archived['id']}/unpublish", headers=auth_if_match(editor, archived["updated_at"]))

    assert (await search(client, "flood")).json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
    assert (await search(client, "बाढी", locale="ne")).json()["total"] == 1


async def test_search_paginates_with_total(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    for title in ("Flood one", "Flood two", "Flood three"):
        await live_post(client, editor, cat, title, "water")
    page1 = (await search(client, "flood", limit=2)).json()
    page2 = (await search(client, "flood", limit=2, offset=2)).json()
    assert (page1["total"], len(page1["items"]), page2["total"], len(page2["items"])) == (3, 2, 3, 1)
    assert not {i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]}


async def test_search_validates_q_and_locale(client, session):
    assert (await search(client, "a")).status_code == 422
    short = await search(client, "  a  ")
    assert short.status_code == 422
    assert short.json()["error"]["code"] == "QUERY_TOO_SHORT"
    assert (await search(client, "x" * 201)).status_code == 422
    bad_locale = await search(client, "flood", locale="fr")
    assert bad_locale.status_code == 404
    assert bad_locale.json()["error"]["code"] == "LOCALE_NOT_FOUND"


async def test_search_punctuation_and_operators_never_500(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    await live_post(client, editor, cat, "Flood relief in Biratnagar", "Water is rising")
    for q in ("!!", "a & (b", "' OR 1=1 --", "flood:*", "\\\\", "<script>"):
        r = await search(client, q)
        assert r.status_code == 200, q
        assert isinstance(r.json()["items"], list)


async def test_card_excerpt_is_auto_until_an_editor_sets_one(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live = await live_post(client, editor, cat, "Flood relief", ("word " * 80).strip())

    auto = (await search(client, "flood")).json()["items"][0]["excerpt"]
    assert len(auto) <= 200 and auto.endswith("…")

    r = await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "en", "excerpt": "Custom summary"},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    assert r.status_code == 200
    assert (await search(client, "flood")).json()["items"][0]["excerpt"] == "Custom summary"
