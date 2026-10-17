import logging
from functools import cache
from typing import Any, TypeVar

from pydantic import TypeAdapter
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.modules.posts.models import Post
from app.modules.seo.service import SlugChange

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=86400"
XML_CACHE_TTL_SECONDS = 300
XML_CACHE_CONTROL = "public, s-maxage=300"
NEGATIVE_TTL_SECONDS = 30
# Stored under a post key when the article does not exist. Every action that can make a slug
# public (publish, translation publish, slug change) deletes that post's keys, marker included.
NOT_FOUND_MARKER = "__404__"

# Every feed key (home, category pages, the category tree) embeds the current value of this
# counter. Invalidating all feeds is one INCR; the orphaned keys expire through their TTL.
FEED_GEN_KEY = "public:feeds:gen"


def post_cache_key(locale: str, slug: str) -> str:
    return f"public:post:{locale}:{slug}"


def categories_cache_key(gen: str) -> str:
    return f"public:categories:{gen}"


def home_cache_key(gen: str, locale: str) -> str:
    return f"public:home:{gen}:{locale}"


def category_feed_cache_key(gen: str, slug: str, locale: str, limit: int, offset: int) -> str:
    return f"public:category:{gen}:{slug}:{locale}:{limit}:{offset}"


def xml_cache_key(gen: str, name: str) -> str:
    return f"public:xml:{gen}:{name}"


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


T = TypeVar("T")


@cache
def _adapter(model: Any) -> TypeAdapter:
    return TypeAdapter(model)


def parse_cached(raw: str, model: type[T], key: str) -> T | None:
    """Parse a cached JSON string; an entry that no longer fits the model (an older deploy wrote
    it, or it is corrupt) is a cache miss, never an error. `model` may be any pydantic-validatable type."""
    try:
        return _adapter(model).validate_json(raw)
    except ValueError:  # pydantic.ValidationError and malformed JSON are both ValueErrors
        logger.warning("Ignoring unreadable cache entry %s", key, exc_info=True)
        return None


async def cached_model(redis: Redis, key: str, model: type[T]) -> T | None:
    """The cached value under key as `model`, or None on a miss, a Redis error or a stale shape."""
    raw = await cache_get(redis, key)
    return parse_cached(raw, model, key) if raw else None


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


def redirect_cache_key(path: str) -> str:
    return f"public:redirect:{path}"


async def invalidate_slug_change(redis: Redis, change: SlugChange) -> None:
    """Drop the old article key and every redirect answer the change touched (404 markers included)."""
    keys = [post_cache_key(change.locale, change.old_slug), *(redirect_cache_key(p) for p in change.redirect_paths)]
    try:
        await redis.delete(*keys)
    except RedisError:
        logger.warning("Cache invalidation failed; stale entries expire via TTL", exc_info=True)
