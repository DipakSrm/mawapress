from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.posts.models import Post, TranslationStatus
from app.modules.public.service import FEED_GEN_KEY, post_cache_key
from app.modules.users.models import Role
from tests.factories import (
    auth_header,
    auth_if_match,
    create_post_via_api,
    make_category,
    make_user,
    publish_via_api,
)


def iso(delta: timedelta) -> str:
    return (utcnow() + delta).isoformat()


async def setup(client, session):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    post = await create_post_via_api(client, reporter, cat)
    return reporter, editor, post


async def schedule(client, editor, post, when, **kw):
    return await client.post(
        f"/api/posts/{post['id']}/schedule", json={"scheduled_at": when},
        headers=auth_if_match(editor, post["updated_at"]), **kw,
    )


async def test_schedule_sets_status_and_scheduled_at(client, session):
    _, editor, post = await setup(client, session)
    when = iso(timedelta(hours=2))
    r = await schedule(client, editor, post, when)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "scheduled" and body["scheduled_at"] is not None
    assert body["published_at"] is None

    # Rescheduling a scheduled post is allowed.
    r2 = await schedule(client, editor, body, iso(timedelta(hours=5)))
    assert r2.status_code == 200 and r2.json()["scheduled_at"] != body["scheduled_at"]

    listed = await client.get("/api/posts?status=scheduled", headers=auth_header(editor))
    assert [i["id"] for i in listed.json()["items"]] == [post["id"]]
    assert listed.json()["items"][0]["scheduled_at"] is not None


async def test_schedule_from_in_review(client, session):
    reporter, editor, post = await setup(client, session)
    sub = await client.post(f"/api/posts/{post['id']}/submit", headers=auth_header(reporter))
    r = await schedule(client, editor, sub.json(), iso(timedelta(hours=1)))
    assert r.status_code == 200 and r.json()["status"] == "scheduled"


async def test_schedule_time_validation(client, session):
    _, editor, post = await setup(client, session)
    for delta in (timedelta(hours=-1), timedelta(seconds=30), timedelta(days=366)):
        r = await schedule(client, editor, post, iso(delta))
        assert r.status_code == 422, delta
        assert r.json()["error"]["code"] == "INVALID_SCHEDULE_TIME"
    naive = await schedule(client, editor, post, "2099-01-01T00:00:00")
    assert naive.status_code == 422
    unchanged = await client.get(f"/api/posts/{post['id']}", headers=auth_header(editor))
    assert unchanged.json()["status"] == "draft" and unchanged.json()["scheduled_at"] is None


async def test_schedule_guards(client, session):
    reporter, editor, post = await setup(client, session)
    url = f"/api/posts/{post['id']}/schedule"
    body = {"scheduled_at": iso(timedelta(hours=1))}
    assert (await client.post(url, json=body, headers=auth_if_match(reporter, post["updated_at"]))).status_code == 403
    missing = await client.post(url, json=body, headers=auth_header(editor))
    assert missing.status_code == 428
    stale = await client.post(url, json=body, headers=auth_if_match(editor, "2000-01-01T00:00:00+00:00"))
    assert stale.status_code == 412

    live = await publish_via_api(client, editor, post)
    wrong = await schedule(client, editor, live, iso(timedelta(hours=1)))
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_unschedule(client, session):
    reporter, editor, post = await setup(client, session)
    sched = (await schedule(client, editor, post, iso(timedelta(hours=1)))).json()
    url = f"/api/posts/{post['id']}/unschedule"
    assert (await client.post(url, headers=auth_if_match(reporter, sched["updated_at"]))).status_code == 403
    assert (await client.post(url, headers=auth_header(editor))).status_code == 428
    assert (await client.post(url, headers=auth_if_match(editor, "2000-01-01T00:00:00+00:00"))).status_code == 412
    r = await client.post(url, headers=auth_if_match(editor, sched["updated_at"]))
    assert r.status_code == 200
    assert r.json()["status"] == "draft" and r.json()["scheduled_at"] is None

    again = await client.post(url, headers=auth_if_match(editor, r.json()["updated_at"]))
    assert again.status_code == 409


async def test_unarchive_restores_published_translations(client, session, fake_redis):
    reporter, editor, post = await setup(client, session)
    live = await publish_via_api(client, editor, post)
    slug = live["translations"][0]["slug"]
    arch = await client.post(f"/api/posts/{post['id']}/unpublish", headers=auth_if_match(editor, live["updated_at"]))
    assert arch.status_code == 200 and arch.json()["status"] == "archived"

    key = post_cache_key("ne", slug)
    await fake_redis.set(key, "stale")
    gen_before = int(await fake_redis.get(FEED_GEN_KEY) or 0)
    url = f"/api/posts/{post['id']}/unarchive"
    assert (await client.post(url, headers=auth_if_match(reporter, arch.json()["updated_at"]))).status_code == 403
    assert (await client.post(url, headers=auth_header(editor))).status_code == 428
    r = await client.post(url, headers=auth_if_match(editor, arch.json()["updated_at"]))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"
    assert r.json()["translations"][0]["status"] == "published"
    assert r.json()["published_at"] == live["published_at"]
    assert await fake_redis.get(key) is None
    assert int(await fake_redis.get(FEED_GEN_KEY)) == gen_before + 1
    topics = (await session.scalars(select(OutboxEvent.topic).order_by(OutboxEvent.id))).all()
    assert topics == ["post.published", "post.unpublished", "post.published"]

    public = await client.get(f"/api/public/posts/ne/{slug}")
    assert public.status_code == 200


async def test_unarchive_without_published_translation_is_rejected(client, session):
    _, editor, post = await setup(client, session)
    live = await publish_via_api(client, editor, post)
    arch = (await client.post(
        f"/api/posts/{post['id']}/unpublish", headers=auth_if_match(editor, live["updated_at"])
    )).json()
    row = await session.get(Post, post["id"])
    for t in row.translations:
        t.status = TranslationStatus.draft
    await session.flush()
    before = await session.scalar(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()).limit(1))
    r = await client.post(f"/api/posts/{post['id']}/unarchive", headers=auth_if_match(editor, arch["updated_at"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_PUBLISHED_TRANSLATION"
    await session.refresh(row)
    assert row.status.value == "archived"
    assert await session.scalar(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()).limit(1)) == before


async def test_unarchive_wrong_status(client, session):
    _, editor, post = await setup(client, session)
    r = await client.post(f"/api/posts/{post['id']}/unarchive", headers=auth_if_match(editor, post["updated_at"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_unarchive_requires_a_current_version(client, session):
    _, editor, post = await setup(client, session)
    live = await publish_via_api(client, editor, post)
    arch = (await client.post(
        f"/api/posts/{post['id']}/unpublish", headers=auth_if_match(editor, live["updated_at"])
    )).json()
    stale = await client.post(
        f"/api/posts/{post['id']}/unarchive", headers=auth_if_match(editor, live["updated_at"])
    )
    assert stale.status_code == 412 and stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert (await session.get(Post, post["id"])).status.value == "archived"
    assert arch["status"] == "archived"


async def test_publish_now_from_scheduled(client, session, fake_redis):
    _, editor, post = await setup(client, session)
    sched = (await schedule(client, editor, post, iso(timedelta(hours=3)))).json()
    url = f"/api/posts/{post['id']}/publish"
    assert (await client.post(url, headers=auth_header(editor))).status_code == 428
    assert (await client.post(url, headers=auth_if_match(editor, post["updated_at"]))).status_code == 412

    before = utcnow()
    r = await client.post(url, headers=auth_if_match(editor, sched["updated_at"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "published" and body["scheduled_at"] is None
    assert datetime.fromisoformat(body["published_at"]) >= before
    assert body["translations"][0]["status"] == "published"
    topics = (await session.scalars(select(OutboxEvent.topic).order_by(OutboxEvent.id))).all()
    assert topics == ["post.published"]
    assert (await client.get(f"/api/public/posts/ne/{body['translations'][0]['slug']}")).status_code == 200
