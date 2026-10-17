from app.modules.public.service import FEED_GEN_KEY
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


async def create_cat(client, user, **body):
    payload = {"name_ne": "खेलकुद", "name_en": "Sports"}
    payload.update(body)
    return await client.post("/api/categories", json=payload, headers=auth_header(user))


async def test_editor_creates_category_with_derived_slug(client, session):
    editor = await make_user(session, role=Role.editor)
    r = await create_cat(client, editor)
    assert r.status_code == 201
    assert r.json() == {
        "id": r.json()["id"], "parent_id": None, "slug": "sports", "name_ne": "खेलकुद",
        "name_en": "Sports", "sort": 0, "seo_description": None,
    }


async def test_reporter_can_list_but_not_manage(client, session):
    reporter = await make_user(session)
    await make_category(session)
    assert (await create_cat(client, reporter)).status_code == 403
    listed = await client.get("/api/categories", headers=auth_header(reporter))
    assert listed.status_code == 200
    assert [c["slug"] for c in listed.json()] == ["morang"]


async def test_invalid_and_duplicate_slugs(client, session):
    editor = await make_user(session, role=Role.editor)
    await make_category(session)
    for bad in ("Bad Slug", "bad--slug", "नेपाल"):
        r = await create_cat(client, editor, slug=bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "INVALID_SLUG"
    assert (await create_cat(client, editor, slug="a" * 81)).status_code == 422
    dup = await create_cat(client, editor, slug="morang")
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "SLUG_TAKEN"


async def test_tree_is_at_most_three_levels(client, session):
    editor = await make_user(session, role=Role.editor)
    root = await make_category(session, slug="province-1")
    child = await make_category(session, slug="morang", parent_id=root.id)
    grand = await create_cat(client, editor, slug="biratnagar", parent_id=child.id)
    assert grand.status_code == 201
    too_deep = await create_cat(client, editor, slug="ward-5", parent_id=grand.json()["id"])
    assert too_deep.status_code == 409
    assert too_deep.json()["error"]["code"] == "CATEGORY_TOO_DEEP"


async def test_unknown_parent_is_422(client, session):
    editor = await make_user(session, role=Role.editor)
    r = await create_cat(client, editor, parent_id=999999)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CATEGORY_NOT_FOUND"


async def test_move_into_own_subtree_is_409(client, session):
    editor = await make_user(session, role=Role.editor)
    a = await make_category(session, slug="a")
    b = await make_category(session, slug="b", parent_id=a.id)
    for parent in (b.id, a.id):
        r = await client.patch(f"/api/categories/{a.id}", json={"parent_id": parent}, headers=auth_header(editor))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CATEGORY_CYCLE"


async def test_move_subtree_beyond_depth_3_is_409(client, session):
    editor = await make_user(session, role=Role.editor)
    x = await make_category(session, slug="x")
    await make_category(session, slug="y", parent_id=x.id)
    z = await make_category(session, slug="z")
    w = await make_category(session, slug="w", parent_id=z.id)

    deep = await client.patch(f"/api/categories/{x.id}", json={"parent_id": w.id}, headers=auth_header(editor))
    assert deep.status_code == 409
    assert deep.json()["error"]["code"] == "CATEGORY_TOO_DEEP"

    ok = await client.patch(f"/api/categories/{x.id}", json={"parent_id": z.id}, headers=auth_header(editor))
    assert ok.status_code == 200
    assert ok.json()["parent_id"] == z.id


async def test_update_names_sort_seo_and_move_to_root(client, session):
    editor = await make_user(session, role=Role.editor)
    root = await make_category(session, slug="province-1")
    cat = await make_category(session, slug="morang", parent_id=root.id)
    r = await client.patch(
        f"/api/categories/{cat.id}",
        json={"name_en": "Morang District", "sort": 5, "seo_description": "News from Morang", "parent_id": None},
        headers=auth_header(editor),
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["name_en"], body["sort"], body["seo_description"], body["parent_id"]) == (
        "Morang District", 5, "News from Morang", None,
    )
    assert body["slug"] == "morang"


async def test_patch_cannot_change_slug_and_unknown_id_is_404(client, session):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    r = await client.patch(f"/api/categories/{cat.id}", json={"slug": "renamed"}, headers=auth_header(editor))
    assert r.status_code == 422
    missing = await client.patch("/api/categories/999999", json={"sort": 1}, headers=auth_header(editor))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CATEGORY_NOT_FOUND"


async def test_delete_refused_while_posts_or_children_reference_it(client, session):
    editor = await make_user(session, role=Role.editor)
    used = await make_category(session, slug="used")
    await create_post_via_api(client, editor, used)
    parent = await make_category(session, slug="parent")
    await make_category(session, slug="child", parent_id=parent.id)
    empty = await make_category(session, slug="empty")

    r = await client.delete(f"/api/categories/{used.id}", headers=auth_header(editor))
    assert r.status_code == 409
    assert r.json()["error"] == {
        "code": "CATEGORY_IN_USE", "message": r.json()["error"]["message"], "details": {"posts": 1, "children": 0},
    }
    r = await client.delete(f"/api/categories/{parent.id}", headers=auth_header(editor))
    assert r.status_code == 409
    assert r.json()["error"]["details"] == {"posts": 0, "children": 1}

    assert (await client.delete(f"/api/categories/{empty.id}", headers=auth_header(editor))).status_code == 204
    assert (await client.delete(f"/api/categories/{empty.id}", headers=auth_header(editor))).status_code == 404


async def test_public_tree_is_nested_sorted_and_cached(client, session):
    editor = await make_user(session, role=Role.editor)
    second = await make_category(session, slug="sports", name_ne="खेलकुद", name_en="Sports", sort=2)
    first = await make_category(session, slug="province-1", name_ne="प्रदेश १", name_en="Province 1", sort=1)
    await make_category(session, slug="morang", parent_id=first.id)

    r = await client.get("/api/public/categories")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, s-maxage=60, stale-while-revalidate=86400"
    assert r.headers["x-cache"] == "MISS"
    tree = r.json()
    assert [n["slug"] for n in tree] == ["province-1", "sports"]
    assert [c["slug"] for c in tree[0]["children"]] == ["morang"]
    assert tree[0]["children"][0]["children"] == []
    assert tree[1]["id"] == second.id

    assert (await client.get("/api/public/categories")).headers["x-cache"] == "HIT"

    await create_cat(client, editor, name_en="Weather", name_ne="मौसम", sort=3)
    after = await client.get("/api/public/categories")
    assert after.headers["x-cache"] == "MISS"
    assert [n["slug"] for n in after.json()] == ["province-1", "sports", "weather"]


async def test_public_tree_survives_redis_outage(session):
    await make_category(session)
    async with await down_client(session) as down:
        r = await down.get("/api/public/categories")
    assert r.status_code == 200
    assert [n["slug"] for n in r.json()] == ["morang"]


async def test_public_post_changes_bump_feed_generation(client, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await create_post_via_api(client, editor, cat)
    assert await fake_redis.get(FEED_GEN_KEY) is None  # drafts do not touch public caches

    live = await publish_via_api(client, editor, post)
    assert await fake_redis.get(FEED_GEN_KEY) == "1"

    r = await client.patch(
        f"/api/posts/{live['id']}", json={"locale": "ne", "title": "नयाँ शीर्षक"},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    assert r.status_code == 200
    assert await fake_redis.get(FEED_GEN_KEY) == "2"


async def test_create_race_on_a_non_slug_constraint_is_a_conflict_not_slug_taken(client, session, monkeypatch):
    """The parent vanishes between the check and the INSERT: an FK violation, not a taken slug."""
    from app.modules.taxonomy import service

    monkeypatch.setattr(service, "_check_parent", lambda *args, **kwargs: None)
    editor = await make_user(session, role=Role.editor)
    r = await create_cat(client, editor, slug="orphan", parent_id=999999)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONFLICT"


async def test_create_race_on_the_slug_constraint_is_slug_taken(client, session, monkeypatch):
    from app.modules.taxonomy import service

    await make_category(session, slug="sports")

    async def stale(_session):
        return {}  # the other request's row is not visible yet

    monkeypatch.setattr(service, "all_categories", stale)
    editor = await make_user(session, role=Role.editor)
    r = await create_cat(client, editor, slug="sports")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SLUG_TAKEN"


async def make_cycle(session):
    from sqlalchemy import update

    from app.modules.taxonomy.models import Category

    a = await make_category(session, slug="cycle-a")
    b = await make_category(session, slug="cycle-b", parent_id=a.id)
    await session.execute(update(Category).where(Category.id == a.id).values(parent_id=b.id))
    return a, b


async def test_ancestor_and_height_walks_survive_a_cycle_in_the_data(session):
    import threading

    from app.modules.taxonomy import service

    a, b = await make_cycle(session)
    cats = await service.all_categories(session)
    out: dict = {}

    def walk():
        out["depth"] = service._depth(cats, a.id)
        out["height"] = service._height(cats, a.id)
        out["found"] = service.descendant_ids(cats, a.id)

    # A daemon thread, so a regression fails the test instead of hanging the run.
    t = threading.Thread(target=walk, daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "walk over a cyclic tree did not return"
    assert out["depth"] <= len(cats) + 1
    assert out["height"] <= len(cats) + 1
    assert out["found"] == {a.id, b.id}


async def test_category_writes_take_the_advisory_lock(client, session):
    from sqlalchemy import text

    editor = await make_user(session, role=Role.editor)
    held = "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
    assert await session.scalar(text(held)) == 0
    created = await create_cat(client, editor)
    assert created.status_code == 201
    assert await session.scalar(text(held)) == 1  # transaction-scoped: held until the outer transaction ends
