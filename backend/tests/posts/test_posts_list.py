import uuid

from app.modules.users.models import Role
from tests.factories import auth_header, auth_if_match, make_category, make_user


def doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


async def create(client, user, category, title="बाढी समाचार", locale="ne"):
    r = await client.post(
        "/api/posts",
        json={"locale": locale, "title": title, "content_json": doc("x"), "category_id": category.id},
        headers=auth_header(user),
    )
    assert r.status_code == 201
    return r.json()


async def list_posts(client, user, **params):
    r = await client.get("/api/posts", params=params, headers=auth_header(user))
    assert r.status_code == 200, r.text
    return r.json()


def ids(page: dict) -> list[str]:
    return [item["id"] for item in page["items"]]


async def test_reporter_sees_only_own_posts(client, session):
    alice = await make_user(session)
    bob = await make_user(session)
    cat = await make_category(session)
    a1 = await create(client, alice, cat)
    a2 = await create(client, alice, cat, title="मोरङ समाचार")
    b1 = await create(client, bob, cat, title="विराटनगर खबर")

    page = await list_posts(client, alice)
    assert page["total"] == 2
    assert set(ids(page)) == {a1["id"], a2["id"]}
    assert b1["id"] not in ids(page)

    snooping = await list_posts(client, alice, author_id=str(bob.id))
    assert snooping == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_editor_sees_all_newest_updated_first(client, session):
    alice = await make_user(session)
    bob = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    older = await create(client, alice, cat)
    newer = await create(client, bob, cat, title="मोरङ समाचार")

    assert ids(await list_posts(client, editor)) == [newer["id"], older["id"]]

    touched = await client.patch(
        f"/api/posts/{older['id']}",
        json={"locale": "ne", "title": "विराटनगर खबर"},
        headers=auth_if_match(alice, older["updated_at"]),
    )
    assert touched.status_code == 200
    assert ids(await list_posts(client, editor)) == [older["id"], newer["id"]]


async def test_items_are_compact_summaries(client, session):
    alice = await make_user(session, name="Alice Rai")
    cat = await make_category(session)
    await create(client, alice, cat)
    item = (await list_posts(client, alice))["items"][0]
    assert set(item) == {
        "id", "status", "category_id", "author_id", "author_name", "view_count", "updated_at", "published_at", "scheduled_at",
        "translations",
    }
    assert item["author_name"] == "Alice Rai"
    assert item["translations"] == [
        {"locale": "ne", "title": "बाढी समाचार", "slug": "badhi-samachar", "status": "draft"}
    ]
    assert item["status"] == "draft" and item["published_at"] is None
    assert item["author_id"] == str(alice.id) and item["category_id"] == cat.id


async def test_filters_status_author_category_locale(client, session):
    alice = await make_user(session)
    bob = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    morang = await make_category(session)
    sunsari = await make_category(session, slug="sunsari", name_ne="सुनसरी", name_en="Sunsari")

    p1 = await create(client, alice, morang)
    live = await client.post(f"/api/posts/{p1['id']}/publish", headers=auth_if_match(editor, p1["updated_at"]))
    assert live.status_code == 200
    p2 = await create(client, bob, sunsari, title="मोरङ समाचार")
    with_en = await client.patch(
        f"/api/posts/{p2['id']}",
        json={"locale": "en", "title": "Flood in Biratnagar", "content_json": doc("x")},
        headers=auth_if_match(bob, p2["updated_at"]),
    )
    assert with_en.status_code == 200

    assert ids(await list_posts(client, editor, status="published")) == [p1["id"]]
    assert ids(await list_posts(client, editor, status="draft")) == [p2["id"]]
    assert ids(await list_posts(client, editor, author_id=str(bob.id))) == [p2["id"]]
    assert ids(await list_posts(client, editor, category_id=sunsari.id)) == [p2["id"]]
    assert ids(await list_posts(client, editor, locale="en")) == [p2["id"]]
    assert (await list_posts(client, editor, locale="ne"))["total"] == 2
    assert (await list_posts(client, editor, status="published", author_id=str(bob.id)))["total"] == 0


async def test_q_matches_title_case_insensitively(client, session):
    alice = await make_user(session)
    cat = await make_category(session)
    flood = await create(client, alice, cat, title="Flood in Biratnagar", locale="en")
    await create(client, alice, cat, title="Road news", locale="en")
    badhi = await create(client, alice, cat)  # "बाढी समाचार"

    assert ids(await list_posts(client, alice, q="flood")) == [flood["id"]]
    assert ids(await list_posts(client, alice, q="BIRAT")) == [flood["id"]]
    assert ids(await list_posts(client, alice, q="बाढी")) == [badhi["id"]]
    assert (await list_posts(client, alice, q="flood", locale="ne"))["total"] == 0
    assert (await list_posts(client, alice, q="   "))["total"] == 3  # blank q is ignored


async def test_q_escapes_like_wildcards(client, session):
    alice = await make_user(session)
    cat = await make_category(session)
    await create(client, alice, cat, title="Rain alert", locale="en")
    percent = await create(client, alice, cat, title="100% rain", locale="en")

    assert ids(await list_posts(client, alice, q="%")) == [percent["id"]]
    assert (await list_posts(client, alice, q="_"))["total"] == 0
    assert (await list_posts(client, alice, q="\\"))["total"] == 0


async def test_pagination_and_limits(client, session):
    alice = await make_user(session)
    cat = await make_category(session)
    created = [
        await create(client, alice, cat, title=title, locale="en")
        for title in ("Rain alert", "Road news", "Election result")
    ]

    first = await list_posts(client, alice, limit=2)
    assert (first["total"], first["limit"], first["offset"], len(first["items"])) == (3, 2, 0, 2)
    second = await list_posts(client, alice, limit=2, offset=2)
    assert (second["total"], second["offset"], len(second["items"])) == (3, 2, 1)
    assert ids(first) + ids(second) == [p["id"] for p in reversed(created)]
    assert (await list_posts(client, alice, offset=10))["items"] == []

    for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "bogus"}, {"locale": "fr"}, {"q": "x" * 201}):
        r = await client.get("/api/posts", params=bad, headers=auth_header(alice))
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_list_requires_login(client):
    r = await client.get("/api/posts")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_published_at_range_filters(client, session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.modules.posts.models import Post

    alice = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    now = datetime.now(UTC)
    ages = {"old": timedelta(days=3), "mid": timedelta(hours=10), "new": timedelta(hours=1)}
    made = {}
    for key, age in ages.items():
        post = await create(client, alice, cat, title=f"Story {key}", locale="en")
        live = await client.post(f"/api/posts/{post['id']}/publish", headers=auth_if_match(editor, post["updated_at"]))
        assert live.status_code == 200
        made[key] = post["id"]
        await session.execute(update(Post).where(Post.id == uuid.UUID(post["id"])).values(published_at=now - age))
    await create(client, alice, cat, title="Still a draft", locale="en")  # published_at is NULL
    await session.commit()

    cutoff = (now - timedelta(hours=24)).isoformat()
    last_day = await list_posts(client, editor, published_after=cutoff)
    assert set(ids(last_day)) == {made["mid"], made["new"]} and last_day["total"] == 2

    before = await list_posts(client, editor, published_before=cutoff)
    assert ids(before) == [made["old"]]

    window = await list_posts(
        client, editor, published_after=(now - timedelta(days=5)).isoformat(), published_before=(now - timedelta(hours=5)).isoformat()
    )
    assert set(ids(window)) == {made["old"], made["mid"]}

    # a post published exactly at the boundary: after is inclusive, before is exclusive
    boundary = now - timedelta(hours=10)
    assert made["mid"] in ids(await list_posts(client, editor, published_after=boundary.isoformat()))
    assert made["mid"] not in ids(await list_posts(client, editor, published_before=boundary.isoformat()))


async def test_published_range_rejects_naive_datetimes(client, session):
    editor = await make_user(session, role=Role.editor)
    for name in ("published_after", "published_before"):
        r = await client.get("/api/posts", params={name: "2026-01-01T00:00:00"}, headers=auth_header(editor))
        assert r.status_code == 422
