"""Enqueue background (arq) jobs from the API. Injectable so tests can capture or run jobs inline."""

import logging
from collections.abc import Awaitable, Callable

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

log = logging.getLogger("mawa.jobs")

Enqueuer = Callable[..., Awaitable[None]]  # await enqueue("job_name", *args)

_pool: ArqRedis | None = None


async def _enqueue(name: str, *args) -> None:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    await _pool.enqueue_job(name, *args)


def get_enqueuer() -> Enqueuer:
    return _enqueue


async def enqueue_quietly(enqueue: Enqueuer, name: str, *args) -> None:
    """Best-effort enqueue: the caller's work already succeeded and the job can be re-run later."""
    try:
        await enqueue(name, *args)
    except Exception:
        log.warning("could not enqueue %s%r; run it again later", name, args, exc_info=True)
