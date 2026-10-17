import hashlib
import ipaddress
import logging

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.cache import get_redis
from app.core.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

LOGIN_PER_IP_EMAIL = 5
LOGIN_PER_IP = 20
SEARCH_PER_IP = 30
VIEW_PER_IP = 60


async def hit(redis: Redis, key: str, limit: int, window_seconds: int) -> bool:
    """Count one hit in a fixed window. True if the request is within `limit`.

    Fails open (returns True, logs a warning) when Redis is unavailable."""
    try:
        pipe = redis.pipeline(transaction=True)
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = await pipe.execute()
        if ttl < 0:  # first hit, or a key that lost its expiry
            await redis.expire(key, window_seconds)
        return int(count) <= limit
    except RedisError:
        logger.warning("Rate limiter unavailable, allowing request for %s", key, exc_info=True)
        return True


async def _retry_after(redis: Redis, key: str, window_seconds: int) -> int:
    try:
        ttl = await redis.ttl(key)
    except RedisError:
        return window_seconds
    return max(int(ttl), 1) if ttl and ttl > 0 else window_seconds


async def enforce(redis: Redis, key: str, limit: int) -> None:
    window = get_settings().rate_limit_window_seconds
    if not await hit(redis, key, limit, window):
        retry = await _retry_after(redis, key, window)
        raise AppError(
            429, "RATE_LIMITED", "Too many requests, try again later", headers={"Retry-After": str(retry)}
        )


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """The caller's IP. Behind a trusted proxy: the configured header (CF-Connecting-IP by default) if it holds
    a valid IP, else the right-most valid X-Forwarded-For entry (the hop our own proxy appended; anything to its
    left is client-supplied and spoofable), else the socket peer."""
    settings = get_settings()
    if settings.trust_proxy:
        direct = _valid_ip(request.headers.get(settings.client_ip_header, ""))
        if direct is not None:
            return direct
        for entry in reversed(request.headers.get("x-forwarded-for", "").split(",")):
            ip = _valid_ip(entry)
            if ip is not None:
                return ip
    return request.client.host if request.client else "unknown"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


async def limit_search(request: Request, redis: Redis = Depends(get_redis)) -> None:
    await enforce(redis, f"rl:search:{client_ip(request)}", SEARCH_PER_IP)


async def limit_view(request: Request, redis: Redis = Depends(get_redis)) -> None:
    await enforce(redis, f"rl:view:{client_ip(request)}", VIEW_PER_IP)
