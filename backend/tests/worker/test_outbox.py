import json
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.worker.outbox import BATCH_SIZE, LEASE_SECONDS, MAX_ATTEMPTS, OUTBOX_LOCK_KEY, process_outbox
from tests.factories import make_category

SITE = "https://mawapress.com"
# Listing pages a change to a post in category "morang" (locales ne + en) can affect.
LISTING_URLS_MORANG = [
    f"{SITE}/", f"{SITE}/en", f"{SITE}/ne", f"{SITE}/en/morang", f"{SITE}/en/morang/rss.xml",
    f"{SITE}/ne/morang", f"{SITE}/ne/morang/rss.xml",
    f"{SITE}/sitemap.xml", f"{SITE}/news-sitemap.xml", f"{SITE}/rss.xml",
]

FULL = dict(
    revalidate_url="https://web.test/api/revalidate",
    revalidate_secret="s3cret",
    cf_zone_id="zone1",
    cf_api_token="cf-token",
    site_url="https://mawapress.com",
)


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**FULL, **overrides})


class Recorder:
    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"ok": self.status < 300})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def body(self, i: int):
        return json.loads(self.requests[i].content)


def make_ctx(session, http, settings=None) -> dict:
    @asynccontextmanager
    async def factory():
        try:
            yield session  # the test session owns the outer rollback
        except Exception:
            await session.rollback()  # what closing a real per-call session does
            raise

    return {"session_factory": factory, "http": http, "settings": settings or make_settings()}


async def add_event(session, topic="post.published", payload=None, **cols) -> OutboxEvent:
    ev = OutboxEvent(topic=topic, payload=payload or {}, **cols)
    session.add(ev)
    await session.flush()
    return ev


async def post_payload(session, slugs=None, **extra) -> dict:
    cat = await make_category(session, slug="morang")
    return {
        "post_id": "00000000-0000-0000-0000-0000000000a1",
        "category_id": cat.id,
        "slugs": slugs or {"ne": "ne-slug", "en": "en-slug"},
        **extra,
    }


async def run(session, settings=None, status=200) -> Recorder:
    rec = Recorder(status)
    async with rec.client() as http:
        await process_outbox(make_ctx(session, http, settings))
    return rec


async def test_success_marks_processed_and_sends_revalidation(session):
    ev = await add_event(session, payload=await post_payload(session))
    rec = await run(session)
    await session.refresh(ev)
    assert ev.processed_at is not None and ev.attempts == 0 and ev.dead_at is None
    reval = rec.requests[0]
    assert str(reval.url) == "https://web.test/api/revalidate"
    assert reval.headers["x-revalidate-secret"] == "s3cret"
    assert rec.body(0) == {
        "tags": ["post:00000000-0000-0000-0000-0000000000a1", "home", "category:morang", "search", "feeds"],
        "paths": ["/en/morang/en-slug", "/ne/morang/ne-slug"],
    }


async def test_cf_purge_gets_absolute_urls(session):
    await add_event(session, payload=await post_payload(session))
    rec = await run(session)
    purge = rec.requests[1]
    assert str(purge.url) == "https://api.cloudflare.com/client/v4/zones/zone1/purge_cache"
    assert purge.headers["authorization"] == "Bearer cf-token"
    assert rec.body(1) == {"files": [
        "https://mawapress.com/en/morang/en-slug", "https://mawapress.com/ne/morang/ne-slug",
        *LISTING_URLS_MORANG,
    ]}


async def test_redirect_event_revalidates_and_purges_old_and_new_paths(session):
    payload = await post_payload(
        session,
        slugs={"ne": "new"},
        redirect={"from": "/ne/morang/old", "to": "/ne/morang/new"},
        redirects=[
            {"from": "/ne/morang/old", "to": "/ne/morang/new"},
            {"from": "/ne/sports/new", "to": "/ne/morang/new"},
        ],
    )
    await add_event(session, "post.updated", payload)
    rec = await run(session)
    paths = rec.body(0)["paths"]
    assert paths == ["/ne/morang/new", "/ne/morang/old", "/ne/sports/new"]  # deduped, order kept
    files = rec.body(1)["files"]
    assert files[:3] == [f"{SITE}{p}" for p in paths]  # article and redirect paths first
    assert f"{SITE}/ne/morang" in files and f"{SITE}/ne/morang/rss.xml" in files and f"{SITE}/" in files
    assert f"{SITE}/en" not in files  # only the locales the post has


async def test_unpublished_also_revalidates(session):
    await add_event(session, "post.unpublished", await post_payload(session, slugs={"ne": "gone"}))
    rec = await run(session)
    assert rec.body(0)["paths"] == ["/ne/morang/gone"]


async def test_cf_purge_batches_of_30(session):
    redirects = [{"from": f"/ne/morang/old-{i}", "to": "/ne/morang/new"} for i in range(70)]
    payload = await post_payload(session, slugs={"ne": "new"}, redirects=redirects)
    await add_event(session, "post.updated", payload)
    rec = await run(session, make_settings(revalidate_url=None))
    batches = [rec.body(i)["files"] for i in range(len(rec.requests))]
    assert [len(b) for b in batches] == [30, 30, 18]  # 71 article paths + 7 listing/feed urls (locale ne only)
    assert len({u for b in batches for u in b}) == 78


async def test_unset_config_skips_and_marks_processed(session):
    ev = await add_event(session, payload=await post_payload(session))
    rec = await run(session, make_settings(revalidate_url=None, cf_zone_id=None, cf_api_token=None))
    await session.refresh(ev)
    assert rec.requests == [] and ev.processed_at is not None


async def test_partial_config_skips_only_that_handler(session):
    await add_event(session, payload=await post_payload(session))
    rec = await run(session, make_settings(cf_api_token=None))
    assert [str(r.url) for r in rec.requests] == ["https://web.test/api/revalidate"]


async def test_sent_back_makes_no_external_call(session):
    ev = await add_event(session, "post.sent_back", {"post_id": "x", "note": None})
    rec = await run(session)
    await session.refresh(ev)
    assert rec.requests == [] and ev.processed_at is not None


async def test_unknown_topic_marked_processed_with_warning(session, caplog):
    ev = await add_event(session, "post.mystery")
    with caplog.at_level("WARNING"):
        rec = await run(session)
    await session.refresh(ev)
    assert ev.processed_at is not None and rec.requests == []
    assert "post.mystery" in caplog.text


async def test_failure_schedules_backoff_and_records_error(session):
    ev = await add_event(session, payload=await post_payload(session))
    before = utcnow()
    await run(session, status=500)
    await session.refresh(ev)
    assert ev.processed_at is None and ev.dead_at is None
    assert ev.attempts == 1
    assert "500" in ev.last_error
    delay = ev.next_attempt_at - before
    assert timedelta(seconds=19) < delay < timedelta(seconds=25)  # 2**1 * 10s


async def test_network_error_is_a_failure_and_error_is_truncated(session):
    ev = await add_event(session, payload=await post_payload(session))

    def boom(request):
        raise httpx.ConnectError("x" * 900)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as http:
        await process_outbox(make_ctx(session, http))
    await session.refresh(ev)
    assert ev.attempts == 1 and len(ev.last_error) == 500


async def test_fifth_failure_dead_letters(session):
    ev = await add_event(session, payload=await post_payload(session), attempts=MAX_ATTEMPTS - 1)
    await run(session, status=502)
    await session.refresh(ev)
    assert ev.attempts == MAX_ATTEMPTS and ev.dead_at is not None and ev.processed_at is None
    assert (await run(session)).requests == []  # a dead row is never picked up again


async def test_rows_waiting_for_backoff_are_skipped(session):
    await add_event(session, payload=await post_payload(session), next_attempt_at=utcnow() + timedelta(minutes=5))
    assert (await run(session)).requests == []


async def test_due_retry_is_picked_up(session):
    ev = await add_event(
        session, payload=await post_payload(session), attempts=2, next_attempt_at=utcnow() - timedelta(seconds=1)
    )
    await run(session)
    await session.refresh(ev)
    assert ev.processed_at is not None


async def test_batch_respects_limit_and_order(session):
    await session.execute(update(OutboxEvent).values(processed_at=utcnow()))
    events = [await add_event(session, "post.sent_back", {"n": i}) for i in range(BATCH_SIZE + 5)]
    await run(session)
    done = (await session.scalars(
        select(OutboxEvent.id).where(OutboxEvent.processed_at.is_not(None), OutboxEvent.id.in_([e.id for e in events]))
    )).all()
    assert sorted(done) == [e.id for e in events[:BATCH_SIZE]]
    left = await session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed_at.is_(None)))
    assert left == 5


async def test_one_failing_row_does_not_block_others(session):
    bad = await add_event(session, payload={"post_id": "p", "category_id": 1, "slugs": {}})
    good = await add_event(session, "post.sent_back")
    await run(session, status=500)
    await session.refresh(bad)
    await session.refresh(good)
    assert bad.attempts == 1 and good.processed_at is not None


async def test_timeout_is_recorded_and_other_events_still_succeed(session):
    slow = await add_event(session, payload=await post_payload(session))
    ok = await add_event(session, "post.sent_back")

    def hang(request):
        raise httpx.ReadTimeout("timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(hang)) as http:
        await process_outbox(make_ctx(session, http))
    await session.refresh(slow)
    await session.refresh(ok)
    assert slow.attempts == 1 and "ReadTimeout" in slow.last_error and slow.next_attempt_at is not None
    assert ok.processed_at is not None


async def test_db_error_in_one_event_does_not_poison_the_batch(session):
    good_payload = await post_payload(session)
    poison = await add_event(session, payload={"post_id": "p", "category_id": "not-an-int", "slugs": {}})
    good = await add_event(session, payload=good_payload)
    later = await add_event(session, "post.sent_back")
    rec = await run(session)
    for ev in (poison, good, later):
        await session.refresh(ev)
    assert poison.attempts == 1 and poison.processed_at is None and poison.last_error
    assert poison.next_attempt_at is not None and poison.dead_at is None
    assert good.processed_at is not None and later.processed_at is not None
    assert len(rec.requests) == 2  # only the good event reached the network
    rec2 = await run(session)  # the poison row is backing off, not blocking
    assert rec2.requests == []


async def test_leased_row_is_not_reclaimed_until_lease_expires(session):
    ev = await add_event(session, "post.sent_back")
    # a claim that crashed before recording: the lease is all that is left on the row
    ev.next_attempt_at = utcnow() + timedelta(seconds=LEASE_SECONDS)
    await session.flush()
    await run(session)
    await session.refresh(ev)
    assert ev.processed_at is None
    ev.next_attempt_at = utcnow() - timedelta(seconds=1)
    await session.flush()
    await run(session)
    await session.refresh(ev)
    assert ev.processed_at is not None and ev.next_attempt_at is None


async def test_claim_takes_a_lease_before_processing(session):
    ev = await add_event(session, payload=await post_payload(session))
    seen = {}

    async def peek(request):
        seen["lease"] = await session.scalar(select(OutboxEvent.next_attempt_at).where(OutboxEvent.id == ev.id))
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(peek)) as http:
        await process_outbox(make_ctx(session, http))
    assert seen["lease"] is not None
    assert timedelta(seconds=LEASE_SECONDS - 5) < seen["lease"] - utcnow() <= timedelta(seconds=LEASE_SECONDS)


async def test_old_category_gets_revalidated_too(session):
    new = await make_category(session, slug="sports")
    old = await make_category(session, slug="morang")
    payload = {
        "post_id": "p1", "category_id": new.id, "old_category_id": old.id, "slugs": {"ne": "x"},
        "redirects": [{"from": "/ne/morang/x", "to": "/ne/sports/x"}],
    }
    await add_event(session, "post.updated", payload)
    rec = await run(session)
    assert rec.body(0)["tags"] == ["post:p1", "home", "category:sports", "category:morang", "search", "feeds"]


async def test_empty_secret_with_url_is_skipped_and_processed(session, caplog):
    ev = await add_event(session, payload=await post_payload(session))
    with caplog.at_level("ERROR"):
        rec = await run(session, make_settings(revalidate_secret="", cf_zone_id=None))
    await session.refresh(ev)
    assert rec.requests == [] and ev.processed_at is not None


async def test_site_url_trailing_slash_and_error_hides_query(session):
    ev = await add_event(session, payload=await post_payload(session, slugs={"ne": "a"}))
    rec = await run(session, make_settings(site_url="https://mawapress.com/", revalidate_url=None))
    files = rec.body(0)["files"]
    assert files[0] == "https://mawapress.com/ne/morang/a" and "https://mawapress.com/" in files
    assert not any("//" in f.removeprefix("https://") for f in files)
    bad = await add_event(session, payload={**ev.payload, "slugs": {"ne": "b"}})
    await run(session, make_settings(revalidate_url="https://web.test/r?token=SECRET"), status=500)
    await session.refresh(bad)
    assert "SECRET" not in bad.last_error and "https://web.test/r" in bad.last_error


async def test_purge_covers_listings_sitemaps_and_feeds_for_both_categories_on_a_move(session):
    new = await make_category(session, slug="sports")
    old = await make_category(session, slug="morang")
    payload = {"post_id": "p1", "category_id": new.id, "old_category_id": old.id, "slugs": {"ne": "x"},
               "redirects": [{"from": "/ne/morang/x", "to": "/ne/sports/x"}]}
    await add_event(session, "post.updated", payload)
    rec = await run(session, make_settings(revalidate_url=None))
    files = [u for r in range(len(rec.requests)) for u in rec.body(r)["files"]]
    assert all(len(rec.body(r)["files"]) <= 30 for r in range(len(rec.requests)))
    for tail in ("/", "/ne", "/ne/sports", "/ne/sports/rss.xml", "/ne/morang", "/ne/morang/rss.xml",
                 "/sitemap.xml", "/news-sitemap.xml", "/rss.xml"):
        assert SITE + tail in files, tail
    assert len(files) == len(set(files))
    assert f"{SITE}/en" not in files


async def test_backoff_is_capped_at_one_hour(session):
    ev = await add_event(session, payload=await post_payload(session), attempts=MAX_ATTEMPTS - 2)
    before = utcnow()
    await run(session, status=500)
    await session.refresh(ev)
    assert ev.dead_at is None and ev.attempts == MAX_ATTEMPTS - 1
    assert ev.next_attempt_at - before <= timedelta(hours=1, seconds=5)
    assert ev.next_attempt_at - before >= timedelta(minutes=59)


def test_ten_attempts_before_dead_letter():
    assert MAX_ATTEMPTS == 10


async def test_overlapping_run_exits_while_the_lock_is_held(session, fake_redis):
    ev = await add_event(session, "post.sent_back")
    await fake_redis.set(OUTBOX_LOCK_KEY, "someone-else", px=60_000)
    rec = Recorder()
    async with rec.client() as http:
        ctx = {**make_ctx(session, http), "cache_redis": fake_redis}
        assert await process_outbox(ctx) == 0
    await session.refresh(ev)
    assert ev.processed_at is None and ev.attempts == 0
    assert await fake_redis.get(OUTBOX_LOCK_KEY) == "someone-else"  # not ours to release


async def test_lock_is_taken_with_a_lease_and_released_after_the_run(session, fake_redis):
    ev = await add_event(session, "post.sent_back")
    seen = {}
    orig = fake_redis.set

    async def spy(*args, **kwargs):
        seen["kwargs"] = kwargs
        return await orig(*args, **kwargs)

    fake_redis.set = spy
    rec = Recorder()
    async with rec.client() as http:
        assert await process_outbox({**make_ctx(session, http), "cache_redis": fake_redis}) == 1
    assert seen["kwargs"].get("nx") is True and seen["kwargs"].get("px") == LEASE_SECONDS * 1000
    assert await fake_redis.get(OUTBOX_LOCK_KEY) is None
    await session.refresh(ev)
    assert ev.processed_at is not None


async def test_lock_is_released_when_the_run_blows_up(session, fake_redis, monkeypatch):
    from app.worker import outbox

    async def boom(factory):
        raise RuntimeError("db gone")

    monkeypatch.setattr(outbox, "_claim", boom)
    rec = Recorder()
    async with rec.client() as http:
        try:
            await process_outbox({**make_ctx(session, http), "cache_redis": fake_redis})
        except RuntimeError:
            pass
    assert await fake_redis.get(OUTBOX_LOCK_KEY) is None
