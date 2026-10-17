"""Every 60 s: drain the Redis view counters into posts.view_count.

Counts are taken with MULTI(GET, DEL), which is atomic on any Redis server and on fakeredis (GETDEL
needs Redis 6.2 and a Lua script needs a scripting engine). A view arriving after the DEL simply
starts a new counter. If the database update fails the taken counts are added back, so nothing is lost.
"""

import logging
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import BigInteger, Uuid, column, update, values

from app.modules.posts.models import Post
from app.modules.public.stats import PENDING_PREFIX, pending_key

log = logging.getLogger("mawa.worker.views")

FLUSH_TIMEOUT_SECONDS = 50  # under the 60 s tick
BATCH_SIZE = 500


async def _take(redis: Redis, key: str) -> int:
    pipe = redis.pipeline(transaction=True)
    pipe.get(key)
    pipe.delete(key)
    raw, _ = await pipe.execute()
    return int(raw or 0)


async def _restore(redis: Redis, counts: dict[uuid.UUID, int]) -> None:
    for post_id, n in counts.items():
        try:
            await redis.incrby(pending_key(post_id), n)
        except RedisError:
            log.error("could not restore %s pending views for post %s; they are lost", n, post_id, exc_info=True)


async def _apply(factory, counts: dict[uuid.UUID, int]) -> set[uuid.UUID]:
    """One UPDATE for the whole batch. Returns the ids that exist (the rest were deleted meanwhile)."""
    v = values(column("id", Uuid), column("n", BigInteger), name="v").data(list(counts.items()))
    stmt = update(Post).where(Post.id == v.c.id).values(view_count=Post.view_count + v.c.n).returning(Post.id)
    async with factory() as session:
        updated = set((await session.scalars(stmt)).all())
        await session.commit()
    return updated


async def flush_views(ctx: dict) -> int:
    """Cron entry point. ctx carries `session_factory` and `cache_redis`. Returns the views taken from Redis
    and applied (counts for posts that no longer exist are dropped)."""
    factory, redis = ctx["session_factory"], ctx["cache_redis"]
    flushed = 0
    batch: dict[uuid.UUID, int] = {}

    async def commit_batch() -> None:
        nonlocal flushed, batch
        if not batch:
            return
        taken, batch = batch, {}
        try:
            updated = await _apply(factory, taken)
        except Exception:
            log.exception("view flush failed; %d posts' counts returned to Redis", len(taken))
            await _restore(redis, taken)
            return
        flushed += sum(n for pid, n in taken.items() if pid in updated)

    try:
        async for key in redis.scan_iter(match=f"{PENDING_PREFIX}*", count=BATCH_SIZE):
            try:
                post_id = uuid.UUID(key.removeprefix(PENDING_PREFIX))
            except ValueError:
                await redis.delete(key)  # not ours to keep
                continue
            n = await _take(redis, key)
            if n > 0:
                batch[post_id] = n
            if len(batch) >= BATCH_SIZE:
                await commit_batch()
    except RedisError:
        log.warning("view flush could not read Redis; retrying next tick", exc_info=True)
    await commit_batch()
    return flushed
