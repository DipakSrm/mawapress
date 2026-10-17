"""Scheduled publishing: every 30 s, publish posts whose `scheduled_at` has passed.

Each post is published in its own short transaction through the same service path as a manual
publish (minus If-Match). A failing post is logged and backed off (2^n minutes, at most 60; after 10 failures it stays
scheduled with its error on the row) so it cannot block the others, and the row lock (SKIP LOCKED) plus a status re-check make overlapping runs safe.
"""

import logging
import time

from app.modules.posts import service
from app.modules.public.service import invalidate_public

log = logging.getLogger("mawa.worker.scheduler")

BATCH_SIZE = 50
SCHEDULER_TIMEOUT_SECONDS = 25  # under the 30 s tick
PROCESS_BUDGET_SECONDS = 20  # stop starting new posts after this; the rest wait for the next tick


async def _record_failure(factory, post_id, exc: Exception) -> None:
    try:
        async with factory() as session:
            await service.record_schedule_failure(session, post_id, exc)
    except Exception:
        log.exception("could not record the scheduling failure of post %s", post_id)


async def publish_due_posts(ctx: dict) -> int:
    """Cron entry point. ctx carries `session_factory` and `cache_redis`. Returns how many posts were published."""
    factory, redis = ctx["session_factory"], ctx["cache_redis"]
    async with factory() as session:
        ids = await service.due_post_ids(session, BATCH_SIZE)
    deadline = time.monotonic() + PROCESS_BUDGET_SECONDS
    published = 0
    for post_id in ids:
        if time.monotonic() > deadline:
            break
        try:
            async with factory() as session:
                post = await service.publish_due_post(session, post_id)
                if post is None:
                    continue
                await invalidate_public(redis, post)  # logs, never raises, on Redis errors
        except Exception as exc:
            log.exception("scheduled publish of post %s failed; backing off", post_id)
            await _record_failure(factory, post_id, exc)
            continue
        published += 1
    return published
