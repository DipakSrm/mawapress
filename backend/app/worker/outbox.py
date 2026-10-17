"""Outbox processor: drains `outbox` rows and fans each event out to its handlers."""

import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.seo.service import article_path
from app.modules.taxonomy.models import Category

log = logging.getLogger("mawa.worker.outbox")

BATCH_SIZE = 50
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 10
ERROR_MAX_LEN = 500
CF_PURGE_BATCH = 30
CF_PURGE_URL = "https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache"
HTTP_TIMEOUT = 5.0

Handler = Callable[[AsyncSession, httpx.AsyncClient, Settings, dict], Awaitable[None]]


def new_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


async def _category(session: AsyncSession, payload: dict) -> Category | None:
    category_id = payload.get("category_id")
    return await session.get(Category, category_id) if category_id else None


async def article_paths(session: AsyncSession, payload: dict) -> list[str]:
    """Public paths an event touches: the live article paths plus every redirect source and target."""
    paths: list[str] = []
    category = await _category(session, payload)
    if category is not None:
        paths += [article_path(locale, category.slug, slug) for locale, slug in sorted((payload.get("slugs") or {}).items())]
    redirects = list(payload.get("redirects") or [])
    if payload.get("redirect"):
        redirects.append(payload["redirect"])
    for r in redirects:
        paths += [r["from"], r["to"]]
    return _unique(paths)


async def revalidate(session: AsyncSession, http: httpx.AsyncClient, settings: Settings, payload: dict) -> None:
    if not settings.revalidate_url:
        return
    tags = [f"post:{payload['post_id']}", "home"]
    category = await _category(session, payload)
    if category is not None:
        tags.append(f"category:{category.slug}")
    tags.append("search")
    resp = await http.post(
        settings.revalidate_url,
        headers={"x-revalidate-secret": settings.revalidate_secret or ""},
        json={"tags": tags, "paths": await article_paths(session, payload)},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()


async def purge_cdn(session: AsyncSession, http: httpx.AsyncClient, settings: Settings, payload: dict) -> None:
    if not (settings.cf_zone_id and settings.cf_api_token):
        return
    urls = [settings.site_url + p for p in await article_paths(session, payload)]
    for i in range(0, len(urls), CF_PURGE_BATCH):
        resp = await http.post(
            CF_PURGE_URL.format(zone=settings.cf_zone_id),
            headers={"Authorization": f"Bearer {settings.cf_api_token}"},
            json={"files": urls[i : i + CF_PURGE_BATCH]},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()


_PUBLIC_CHANGE: list[Handler] = [revalidate, purge_cdn]

# Register new topics (and later tasks' handlers) here.
HANDLERS: dict[str, list[Handler]] = {
    "post.published": _PUBLIC_CHANGE,
    "post.updated": _PUBLIC_CHANGE,
    "post.unpublished": _PUBLIC_CHANGE,
    "post.sent_back": [],  # nothing external to call
}


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        text = f"HTTP {exc.response.status_code} from {exc.request.url}"
    else:
        text = f"{type(exc).__name__}: {exc}"
    return text[:ERROR_MAX_LEN]


async def _dispatch(session: AsyncSession, http: httpx.AsyncClient, settings: Settings, event: OutboxEvent) -> None:
    handlers = HANDLERS.get(event.topic)
    if handlers is None:
        log.warning("outbox event %s has unknown topic %r; marking processed", event.id, event.topic)
        return
    for handler in handlers:
        await handler(session, http, settings, event.payload)


async def run_batch(session: AsyncSession, http: httpx.AsyncClient, settings: Settings) -> int:
    now = utcnow()
    events = (await session.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.processed_at.is_(None),
            OutboxEvent.dead_at.is_(None),
            or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
        )
        .order_by(OutboxEvent.id)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )).all()
    for event in events:
        try:
            await _dispatch(session, http, settings, event)
        except Exception as exc:  # one bad event must not block the rest of the batch
            event.attempts += 1
            event.last_error = _describe(exc)
            if event.attempts >= MAX_ATTEMPTS:
                event.dead_at = utcnow()
                log.error("outbox event %s dead-lettered: %s", event.id, event.last_error)
            else:
                event.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_BASE_SECONDS * 2**event.attempts)
        else:
            event.processed_at = utcnow()
    return len(events)


async def process_outbox(ctx: dict) -> int:
    """Cron entry point (every 10 s). ctx carries `session_factory`, `http` and `settings`."""
    async with ctx["session_factory"]() as session:
        count = await run_batch(session, ctx["http"], ctx["settings"])
        await session.commit()
    return count
