"""refresh_seo_for(kind, id): re-run the SEO build for every post a renamed category or author belongs to.

Enqueued by the API after the rename commits, so the request stays fast. Posts are handled in batches of
100 (keyset by id), each in its own transaction. Live posts also get a `post.updated` outbox event so the
web app revalidates and the CDN purges them; their cache keys and the feeds are dropped after each commit.
"""

import logging
import uuid

from sqlalchemy import select

from app.db.outbox import OutboxEvent
from app.modules.posts import service as posts_service
from app.modules.posts.models import Post, PostStatus
from app.modules.public.service import invalidate_feeds, invalidate_post_cache

log = logging.getLogger("mawa.worker.seo")

BATCH_SIZE = 100
KINDS = {"category": Post.category_id, "user": Post.author_id}


def _parse_id(kind: str, raw: str):
    return int(raw) if kind == "category" else uuid.UUID(raw)


async def refresh_seo_for(ctx: dict, kind: str, id: str) -> int:
    """arq job. Returns how many posts were refreshed."""
    column = KINDS.get(kind)
    if column is None:
        log.warning("refresh_seo_for: unknown kind %r", kind)
        return 0
    try:
        owner_id = _parse_id(kind, id)
    except ValueError:
        log.warning("refresh_seo_for: bad %s id %r", kind, id)
        return 0
    factory, redis = ctx["session_factory"], ctx["cache_redis"]
    refreshed, last_id, any_live = 0, None, False
    while True:
        async with factory() as session:
            stmt = select(Post).where(column == owner_id).order_by(Post.id).limit(BATCH_SIZE)
            if last_id is not None:
                stmt = stmt.where(Post.id > last_id)
            posts = list((await session.scalars(stmt.execution_options(populate_existing=True))).all())
            if not posts:
                break
            live = []
            for post in posts:
                await posts_service._refresh_all_seo(session, post)
                if post.status == PostStatus.published:
                    session.add(posts_service._post_event("post.updated", post))
                    live.append(post)
            last_id = posts[-1].id
            await session.commit()
            refreshed += len(posts)
            for post in live:
                await invalidate_post_cache(redis, post)  # logs, never raises, on Redis errors
            any_live = any_live or bool(live)
    if any_live:
        await invalidate_feeds(redis)
    return refreshed
