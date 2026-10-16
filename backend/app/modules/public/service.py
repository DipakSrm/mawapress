import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.posts.models import Post

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=86400"


def post_cache_key(locale: str, slug: str) -> str:
    return f"public:post:{locale}:{slug}"


async def invalidate_post_cache(redis: Redis, post: Post) -> None:
    keys = [post_cache_key(t.locale, t.slug) for t in post.translations]
    if not keys:
        return
    try:
        await redis.delete(*keys)
    except RedisError:
        logger.warning("Cache invalidation failed; stale entries expire via TTL", exc_info=True)
