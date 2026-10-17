"""View counting and trending, backed by Redis.

Keys:
  view:{post_id}:{ip_hash}          SET NX, 30 min  - one count per client per window
  views:pending:{post_id}           INCR            - drained into posts.view_count by the flush cron
  trending:{locale}:{yyyymmddhh}    ZINCRBY, 25 h   - one sorted set per UTC hour; trending unions the last 24
"""

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.base import utcnow
from app.modules.posts.models import Post
from app.modules.public.feeds import NEWEST_FIRST, card_query, to_card, visible
from app.modules.public.schemas import PublicCard

logger = logging.getLogger(__name__)

DEDUP_TTL_SECONDS = 30 * 60
BUCKET_TTL_SECONDS = 25 * 3600
TRENDING_HOURS = 24
TRENDING_OVERFETCH = 3  # ids taken beyond `limit`, to absorb posts that stopped being public
FALLBACK_DAYS = 7
PENDING_PREFIX = "views:pending:"


def pending_key(post_id: uuid.UUID | str) -> str:
    return f"{PENDING_PREFIX}{post_id}"


def hour_bucket_key(locale: str, when: datetime) -> str:
    return f"trending:{locale}:{when:%Y%m%d%H}"


def trending_cache_key(locale: str, limit: int, padded: bool = False) -> str:
    return f"public:trending{':padded' if padded else ''}:{locale}:{limit}"


def daily_salt(day: str) -> bytes:
    """Derived from a server secret and the UTC date, so it rotates daily and cannot be rebuilt without the secret."""
    s = get_settings()
    secret = s.stats_salt or s.jwt_secret
    return hmac.new(secret.encode(), f"stats-salt:{day}".encode(), hashlib.sha256).digest()


def ip_hash(ip: str, now: datetime) -> str:
    return hashlib.sha256(ip.encode() + daily_salt(f"{now:%Y-%m-%d}")).hexdigest()


async def is_countable(session: AsyncSession, post_id: uuid.UUID, locale: str) -> bool:
    """A published post with a published translation in `locale` (the shared public-visibility rule)."""
    stmt = (
        select(Post.id)
        .select_from(Post)
        .join(Post.translations)
        .where(Post.id == post_id, *visible(locale))
        .limit(1)
    )
    return await session.scalar(stmt) is not None


async def record_view(redis: Redis, post_id: uuid.UUID, locale: str, ip: str) -> bool:
    """Count a view unless this client already counted it within the dedup window. Raises RedisError."""
    now = utcnow()
    first = await redis.set(f"view:{post_id}:{ip_hash(ip, now)}", "1", nx=True, ex=DEDUP_TTL_SECONDS)
    if not first:
        return False
    bucket = hour_bucket_key(locale, now)
    pipe = redis.pipeline(transaction=True)
    pipe.incr(pending_key(post_id))
    pipe.zincrby(bucket, 1, str(post_id))
    pipe.expire(bucket, BUCKET_TTL_SECONDS)
    await pipe.execute()
    return True


async def trending_ids(redis: Redis, locale: str, count: int, now: datetime) -> list[uuid.UUID]:
    """Top post ids over the last 24 hourly buckets, most viewed first. Raises RedisError."""
    buckets = [hour_bucket_key(locale, now - timedelta(hours=h)) for h in range(TRENDING_HOURS)]
    tmp = f"trending:tmp:{uuid.uuid4().hex}"
    pipe = redis.pipeline(transaction=True)
    pipe.zunionstore(tmp, buckets)
    pipe.zrevrange(tmp, 0, count - 1)
    pipe.delete(tmp)  # a short-lived key by construction; it never outlives this transaction
    _, members, _ = await pipe.execute()
    ids = []
    for m in members:
        try:
            ids.append(uuid.UUID(m))
        except ValueError:
            continue
    return ids


async def cards_in_order(session: AsyncSession, locale: str, ids: list[uuid.UUID], limit: int) -> list[PublicCard]:
    """Public cards for `ids`, keeping the given ranking; ids that are no longer public are skipped."""
    if not ids:
        return []
    rows = {row.id: row for row in await session.execute(card_query(locale).where(Post.id.in_(ids)))}
    return [to_card(rows[i]) for i in ids if i in rows][:limit]


async def top_by_redis(session: AsyncSession, redis: Redis, locale: str, limit: int) -> list[PublicCard]:
    ids = await trending_ids(redis, locale, limit * TRENDING_OVERFETCH, utcnow())
    return await cards_in_order(session, locale, ids, limit)


async def top_by_view_count(
    session: AsyncSession, locale: str, limit: int, exclude: set[uuid.UUID] = frozenset()
) -> list[PublicCard]:
    """The most-viewed posts published in the last 7 days (Redis-down fallback, and top-up for quiet days)."""
    since = utcnow() - timedelta(days=FALLBACK_DAYS)
    stmt = (
        card_query(locale)
        .where(Post.published_at >= since, Post.id.not_in(list(exclude)))
        .order_by(Post.view_count.desc(), *NEWEST_FIRST)
        .limit(limit)
    )
    return [to_card(row) for row in await session.execute(stmt)]
