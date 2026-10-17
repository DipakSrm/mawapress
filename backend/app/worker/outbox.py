"""Outbox processor: claims `outbox` rows, then fans each event out to its handlers.

Claim-then-process: a short transaction leases a batch (next_attempt_at = now + LEASE), then every
event is handled with no transaction open and its result recorded in its own short transaction.
Overlapping runs are safe because a leased row is invisible to other claims until the lease
expires; a crashed or cancelled run simply lets the lease lapse and the row is retried.
"""

import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import or_, select, update

from app.core.config import Settings
from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.seo.service import article_path
from app.modules.taxonomy.models import Category

log = logging.getLogger("mawa.worker.outbox")

BATCH_SIZE = 20
LEASE_SECONDS = 120
PROCESS_BUDGET_SECONDS = 90  # stop starting new events after this; keep the cron timeout between this and the lease
CRON_TIMEOUT_SECONDS = 110
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 10
ERROR_MAX_LEN = 500
CF_PURGE_BATCH = 30
CF_PURGE_URL = "https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache"
HTTP_TIMEOUT = 5.0  # set once on the client; the client's timeout is the only source

SessionFactory = Callable[[], object]


@dataclass(frozen=True)
class Targets:
    post_id: str
    tags: list[str]
    paths: list[str]


Handler = Callable[[httpx.AsyncClient, Settings, Targets], Awaitable[None]]


def new_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


async def resolve_targets(session, payload: dict) -> Targets:
    """Tags and public paths an event touches, derived from its payload (reads the DB)."""
    tags = [f"post:{payload['post_id']}", "home"]
    paths: list[str] = []
    category_id = payload.get("category_id")
    category = await session.get(Category, category_id) if category_id is not None else None
    if category is not None:
        tags.append(f"category:{category.slug}")
        paths += [article_path(locale, category.slug, slug) for locale, slug in sorted((payload.get("slugs") or {}).items())]
    old_id = payload.get("old_category_id")
    old = await session.get(Category, old_id) if old_id is not None else None
    if old is not None:
        tags.append(f"category:{old.slug}")
    tags.append("search")
    redirects = list(payload.get("redirects") or [])
    if payload.get("redirect"):
        redirects.append(payload["redirect"])
    for r in redirects:
        paths += [r["from"], r["to"]]
    return Targets(str(payload["post_id"]), _unique(tags), _unique(paths))


_warned_empty_secret = False


async def revalidate(http: httpx.AsyncClient, settings: Settings, targets: Targets) -> None:
    global _warned_empty_secret
    if not settings.revalidate_url:
        return
    if not settings.revalidate_secret:
        if not _warned_empty_secret:
            _warned_empty_secret = True
            log.error("MAWA_REVALIDATE_URL is set but MAWA_REVALIDATE_SECRET is empty; skipping revalidation")
        return
    resp = await http.post(
        settings.revalidate_url,
        headers={"x-revalidate-secret": settings.revalidate_secret},
        json={"tags": targets.tags, "paths": targets.paths},
    )
    resp.raise_for_status()


async def purge_cdn(http: httpx.AsyncClient, settings: Settings, targets: Targets) -> None:
    if not (settings.cf_zone_id and settings.cf_api_token):
        return
    base = settings.site_url.rstrip("/")
    urls = [base + p for p in targets.paths]
    for i in range(0, len(urls), CF_PURGE_BATCH):
        resp = await http.post(
            CF_PURGE_URL.format(zone=settings.cf_zone_id),
            headers={"Authorization": f"Bearer {settings.cf_api_token}"},
            json={"files": urls[i : i + CF_PURGE_BATCH]},
        )
        resp.raise_for_status()


_PUBLIC_CHANGE: list[Handler] = [revalidate, purge_cdn]

# Register new topics (and later tasks' handlers) here. Handlers get no DB session on purpose.
HANDLERS: dict[str, list[Handler]] = {
    "post.published": _PUBLIC_CHANGE,
    "post.updated": _PUBLIC_CHANGE,
    "post.unpublished": _PUBLIC_CHANGE,
    "post.sent_back": [],  # nothing external to call
}


def _safe_url(url) -> str:
    parts = urlsplit(str(url))
    return f"{parts.scheme}://{parts.hostname}{parts.path}"  # never the query or credentials


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        text = f"HTTP {exc.response.status_code} from {_safe_url(exc.request.url)}"
    else:
        text = f"{type(exc).__name__}: {exc}"
    return text[:ERROR_MAX_LEN]


async def _claim(factory: SessionFactory) -> list[tuple[int, str, dict]]:
    now = utcnow()
    async with factory() as session:
        rows = (await session.execute(
            select(OutboxEvent.id, OutboxEvent.topic, OutboxEvent.payload)
            .where(
                OutboxEvent.processed_at.is_(None),
                OutboxEvent.dead_at.is_(None),
                or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
            )
            .order_by(OutboxEvent.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )).all()
        claimed = [(r.id, r.topic, r.payload) for r in rows]
        if claimed:
            await session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id.in_([c[0] for c in claimed]))
                .values(next_attempt_at=now + timedelta(seconds=LEASE_SECONDS))
            )
        await session.commit()
    return claimed


async def _release(factory: SessionFactory, ids: list[int]) -> None:
    async with factory() as session:
        await session.execute(update(OutboxEvent).where(OutboxEvent.id.in_(ids)).values(next_attempt_at=None))
        await session.commit()


async def _handle(factory: SessionFactory, http: httpx.AsyncClient, settings: Settings, topic: str, payload: dict) -> None:
    handlers = HANDLERS.get(topic)
    if handlers is None:
        log.warning("outbox event has unknown topic %r; marking processed", topic)
        return
    if not handlers:
        return
    async with factory() as session:  # short read-only session, closed before any HTTP call
        targets = await resolve_targets(session, payload)
    for handler in handlers:
        await handler(http, settings, targets)


async def _record_success(factory: SessionFactory, event_id: int) -> None:
    async with factory() as session:
        event = await session.get(OutboxEvent, event_id, populate_existing=True)
        event.processed_at = utcnow()
        event.next_attempt_at = None
        await session.commit()


async def _record_failure(factory: SessionFactory, event_id: int, exc: Exception) -> None:
    async with factory() as session:
        event = await session.get(OutboxEvent, event_id, populate_existing=True)
        event.attempts += 1
        event.last_error = _describe(exc)
        if event.attempts >= MAX_ATTEMPTS:
            event.dead_at = utcnow()
            event.next_attempt_at = None
            log.error("outbox event %s dead-lettered: %s", event_id, event.last_error)
        else:
            event.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_BASE_SECONDS * 2**event.attempts)
        await session.commit()


async def process_outbox(ctx: dict) -> int:
    """Cron entry point (every 10 s). ctx carries `session_factory`, `http` and `settings`."""
    factory, http, settings = ctx["session_factory"], ctx["http"], ctx["settings"]
    claimed = await _claim(factory)
    deadline = time.monotonic() + PROCESS_BUDGET_SECONDS
    done = 0
    for i, (event_id, topic, payload) in enumerate(claimed):
        if time.monotonic() > deadline:  # out of time: hand the rest back instead of holding the lease
            await _release(factory, [c[0] for c in claimed[i:]])
            break
        try:
            await _handle(factory, http, settings, topic, payload)
        except Exception as exc:  # any failure, including a DB error, counts against this event only
            await _record_failure(factory, event_id, exc)
        else:
            await _record_success(factory, event_id)
        done += 1
    return done
