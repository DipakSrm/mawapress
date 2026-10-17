import uuid
from contextlib import asynccontextmanager

from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.posts.models import Post
from app.modules.public.service import FEED_GEN_KEY, post_cache_key
from app.modules.users.models import Role
from app.worker import seo as seo_worker
from app.worker.seo import refresh_seo_for
from app.worker.settings import WorkerSettings
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    doc,
    make_category,
    make_user,
    publish_via_api,
)


def make_ctx(session, redis, counter=None) -> dict:
    @asynccontextmanager
    async def factory():
        if counter is not None:
            counter.append(1)
        yield session

    return {"session_factory": factory, "cache_redis": redis}


async def live_and_draft(client, session, cat, author, editor):
    live = await create_post_via_api(client, author, cat, title="बाढी समाचार")
    r = await client.patch(
        f"/api/posts/{live['id']}",
        json={"locale": "en", "title": "Flood news", "content_json": doc("rain")},
        headers=auth_if_match(editor, live["updated_at"]),
    )
    live = await publish_via_api(client, editor, r.json())
    draft = await create_post_via_api(client, author, cat, title="मस्यौदा")
    return live, draft


def article(post_row, locale):
    tr = next(t for t in post_row.translations if t.locale == locale)
    return tr.seo_auto["json_ld"][0]


async def topics(session):
    rows = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
    return [(e.topic, e.payload["post_id"]) for e in rows]


async def reload(session, post_id):
    return await session.get(Post, uuid.UUID(post_id), populate_existing=True)


async def test_category_rename_enqueues_a_refresh_and_the_job_updates_seo_and_emits_events(
    client, session, fake_redis, jobs
):
    editor = await make_user(session, role=Role.editor)
    author = await make_user(session)
    cat = await make_category(session, slug="morang", name_ne="मोरङ", name_en="Morang")
    live, draft = await live_and_draft(client, session, cat, author, editor)
    jobs.clear()
    events_before = len(await topics(session))
    cache_key = post_cache_key("ne", live["translations"][0]["slug"])
    await fake_redis.set(cache_key, "stale")

    r = await client.patch(
        f"/api/categories/{cat.id}", json={"name_ne": "मोरङ जिल्ला", "name_en": "Morang District"},
        headers=auth_header(editor),
    )
    assert r.status_code == 200
    assert jobs == [("refresh_seo_for", ("category", str(cat.id)))]  # enqueued after the commit, not run inline
    assert article(await reload(session, live["id"]), "ne")["articleSection"] == "मोरङ"  # old until the job runs

    await fake_redis.set(cache_key, "stale")  # the rename itself bumped the feeds; restart from here
    gen_before = int(await fake_redis.get(FEED_GEN_KEY) or 0)
    await refresh_seo_for(make_ctx(session, fake_redis), "category", str(cat.id))

    row = await reload(session, live["id"])
    assert article(row, "ne")["articleSection"] == "मोरङ जिल्ला"
    assert article(row, "en")["articleSection"] == "Morang District"
    assert article(await reload(session, draft["id"]), "ne")["articleSection"] == "मोरङ जिल्ला"  # drafts too
    assert (await topics(session))[events_before:] == [("post.updated", live["id"])]  # but only live posts emit
    assert await fake_redis.get(cache_key) is None
    assert int(await fake_redis.get(FEED_GEN_KEY)) == gen_before + 1


async def test_category_update_without_a_name_change_enqueues_nothing(client, session, jobs):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    r = await client.patch(f"/api/categories/{cat.id}", json={"sort": 3}, headers=auth_header(editor))
    assert r.status_code == 200 and jobs == []


async def test_admin_user_rename_refreshes_the_author_in_json_ld(client, session, fake_redis, jobs):
    admin = await make_user(session, role=Role.admin)
    editor = await make_user(session, role=Role.editor)
    author = await make_user(session, name="Old Author")
    cat = await make_category(session)
    live, _ = await live_and_draft(client, session, cat, author, editor)
    jobs.clear()
    events_before = len(await topics(session))

    r = await client.patch(f"/api/users/{author.id}", json={"name": "New Author"}, headers=auth_header(admin))
    assert r.status_code == 200
    assert jobs == [("refresh_seo_for", ("user", str(author.id)))]
    await refresh_seo_for(make_ctx(session, fake_redis), "user", str(author.id))

    row = await reload(session, live["id"])
    assert article(row, "ne")["author"] == [{"@type": "Person", "name": "New Author"}]
    assert article(row, "en")["author"][0]["name"] == "New Author"
    assert (await topics(session))[events_before:] == [("post.updated", live["id"])]


async def test_self_rename_enqueues_a_refresh_but_a_bio_edit_does_not(client, session, fake_redis, jobs):
    author = await make_user(session, name="Old Author")
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    live, _ = await live_and_draft(client, session, cat, author, editor)
    jobs.clear()
    await client.patch("/api/auth/me", json={"bio": "hello"}, headers=auth_header(author))
    assert jobs == []
    r = await client.patch("/api/auth/me", json={"name": "Self Renamed"}, headers=auth_header(author))
    assert r.status_code == 200
    assert jobs == [("refresh_seo_for", ("user", str(author.id)))]
    await refresh_seo_for(make_ctx(session, fake_redis), "user", str(author.id))
    assert article(await reload(session, live["id"]), "ne")["author"][0]["name"] == "Self Renamed"


async def test_job_works_in_batches_each_in_its_own_transaction(client, session, fake_redis, monkeypatch):
    monkeypatch.setattr(seo_worker, "BATCH_SIZE", 2)
    editor = await make_user(session, role=Role.editor)
    author = await make_user(session)
    cat = await make_category(session, slug="batches", name_en="Old")
    ids = []
    for i in range(5):
        post = await create_post_via_api(client, author, cat, title=f"शीर्षक {i}")
        ids.append((await publish_via_api(client, editor, post))["id"])
    cat.name_ne = "नयाँ नाम"
    await session.flush()
    events_before = len(await topics(session))
    opened: list[int] = []
    await refresh_seo_for(make_ctx(session, fake_redis, opened), "category", str(cat.id))
    assert len(opened) >= 3  # 5 posts at 2 per batch
    for pid in ids:
        assert article(await reload(session, pid), "ne")["articleSection"] == "नयाँ नाम"
    assert len((await topics(session))[events_before:]) == 5


async def test_unknown_kind_or_id_is_a_quiet_no_op(session, fake_redis):
    assert await refresh_seo_for(make_ctx(session, fake_redis), "category", "999999") == 0
    assert await refresh_seo_for(make_ctx(session, fake_redis), "user", str(uuid.uuid4())) == 0
    assert await refresh_seo_for(make_ctx(session, fake_redis), "nope", "1") == 0


def test_job_is_registered_with_the_worker():
    assert refresh_seo_for in WorkerSettings.functions
