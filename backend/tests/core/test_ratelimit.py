import asyncio
import logging

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core import ratelimit
from app.core.config import get_settings
from tests.factories import make_user


async def attempt(client, email="x@mawapress.com", headers=None):
    return await client.post("/api/auth/login", json={"email": email, "password": "nope-nope-1"}, headers=headers)


async def test_hit_counts_within_a_fixed_window(fake_redis):
    results = [await ratelimit.hit(fake_redis, "k", 3, 60) for _ in range(5)]
    assert results == [True, True, True, False, False]
    assert await ratelimit.hit(fake_redis, "other", 3, 60) is True


async def test_login_limited_per_ip_and_email_after_five_attempts(client, session):
    await make_user(session, email="x@mawapress.com", password="right-pass-1")
    for _ in range(5):
        assert (await attempt(client)).status_code == 401
    blocked = await attempt(client)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) >= 1
    # a different email from the same IP is not blocked by the per-email bucket
    assert (await attempt(client, email="y@mawapress.com")).status_code == 401


async def test_login_limit_resets_after_the_window(client, fake_redis):
    # Seed the counter at the limit with a 2s TTL so timing on slow machines cannot matter.
    key = f"rl:login:127.0.0.1:{ratelimit.digest('x@mawapress.com')}"
    await fake_redis.set(key, ratelimit.LOGIN_PER_IP_EMAIL, ex=2)
    blocked = await attempt(client)
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 2
    await asyncio.sleep(2.3)
    assert (await attempt(client)).status_code == 401


async def test_login_limited_per_ip(client):
    for i in range(20):
        assert (await attempt(client, email=f"u{i}@mawapress.com")).status_code == 401
    blocked = await attempt(client, email="u99@mawapress.com")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"


async def test_forwarded_for_ignored_unless_trusted(client, monkeypatch):
    for i in range(5):
        await attempt(client, headers={"X-Forwarded-For": f"9.9.9.{i}"})
    assert (await attempt(client, headers={"X-Forwarded-For": "9.9.9.200"})).status_code == 429

    monkeypatch.setattr(get_settings(), "trust_proxy", True)
    assert (await attempt(client, email="z@mawapress.com", headers={"X-Forwarded-For": "7.7.7.7"})).status_code == 401
    for _ in range(5):
        await attempt(client, headers={"X-Forwarded-For": "8.8.8.8, 10.0.0.2"})
    assert (await attempt(client, headers={"X-Forwarded-For": "8.8.8.8, 10.0.0.9"})).status_code == 429
    assert (await attempt(client, headers={"X-Forwarded-For": "7.7.7.7"})).status_code == 401


async def test_search_limited(client):
    params = {"q": "flood", "locale": "ne"}
    for _ in range(30):
        assert (await client.get("/api/public/search", params=params)).status_code == 200
    blocked = await client.get("/api/public/search", params=params)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in blocked.headers


class BrokenRedis:
    def pipeline(self, *args, **kwargs):
        raise RedisConnectionError("down")


async def test_limiter_fails_open_when_redis_is_down(caplog):
    with caplog.at_level(logging.WARNING, logger="app.core.ratelimit"):
        assert await ratelimit.hit(BrokenRedis(), "k", 1, 60) is True
        assert await ratelimit.hit(BrokenRedis(), "k", 1, 60) is True
    assert "rate limiter" in caplog.text.lower()


async def test_invalid_forwarded_for_falls_back_to_client_host(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "trust_proxy", True)
    for junk in ("not-an-ip", "1.2.3.4.5", "<script>", "999.1.1.1", "also-bad"):
        await attempt(client, headers={"X-Forwarded-For": junk})
    # all five attempts landed in the 127.0.0.1 bucket
    assert (await attempt(client, headers={"X-Forwarded-For": "bad again"})).status_code == 429


async def test_valid_ipv6_forwarded_for_is_used(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "trust_proxy", True)
    for _ in range(5):
        await attempt(client, headers={"X-Forwarded-For": "2001:db8::1"})
    assert (await attempt(client, headers={"X-Forwarded-For": "2001:db8::1"})).status_code == 429
    assert (await attempt(client, headers={"X-Forwarded-For": "2001:db8::2"})).status_code == 401
