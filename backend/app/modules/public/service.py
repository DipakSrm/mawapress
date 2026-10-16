import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.posts.models import Post

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=86400"

# Every feed key (home, category pages, the category tree) embeds the current value of this
# counter. Invalidating all feeds is one INCR; the orphaned keys expire through their TTL.
FEED_GEN_KEY = "public:feeds:gen"


def post_cache_key(locale: str, slug: str) -> str:
    return f"public:post:{locale}:{slug}"


def categories_cache_key(gen: str) -> str:
    return f"public:categories:{gen}"


async def feed_generation(redis: Redis) -> str | None:
    """Current feed generation, or None when Redis is unavailable (callers then skip the cache)."""
    try:
        return await redis.get(FEED_GEN_KEY) or "0"
    except RedisError:
        logger.warning("Cache read failed; serving from database", exc_info=True)
        return None


async def cache_get(redis: Redis, key: str) -> str | None:
    try:
        return await redis.get(key)
    except RedisError:
        logger.warning("Cache read failed; serving from database", exc_info=True)
        return None


async def cache_set(redis: Redis, key: str, value: str, ttl: int = CACHE_TTL_SECONDS) -> None:
    try:
        await redis.set(key, value, ex=ttl)
    except RedisError:
        logger.warning("Cache write failed; response not cached", exc_info=True)


async def invalidate_post_cache(redis: Redis, post: Post) -> None:
    keys = [post_cache_key(t.locale, t.slug) for t in post.translations]
    if not keys:
        return
    try:
        await redis.delete(*keys)
    except RedisError:
        logger.warning("Cache invalidation failed; stale entries expire via TTL", exc_info=True)


async def invalidate_feeds(redis: Redis) -> None:
    try:
        await redis.incr(FEED_GEN_KEY)
    except RedisError:
        logger.warning("Feed invalidation failed; stale feeds expire via TTL", exc_info=True)


async def invalidate_public(redis: Redis, post: Post) -> None:
    """Everything a public change to this post can affect: its article keys and every feed."""
    await invalidate_post_cache(redis, post)
    await invalidate_feeds(redis)
