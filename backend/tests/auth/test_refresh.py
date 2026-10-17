from datetime import timedelta

from sqlalchemy import select

from app.db.base import utcnow
from app.modules.auth.models import RefreshToken
from app.modules.users.models import Role
from tests.factories import auth_header, make_user

EMAIL = "r@mawapress.com"
PASSWORD = "refresh-pass-1"


async def login(client):
    r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    return r


def csrf_headers(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("mawa_csrf")}


def explicit(refresh: str | None, csrf: str | None, header: str | None) -> dict[str, str]:
    """Headers that bypass the client's cookie jar (an explicit Cookie header wins)."""
    cookies = []
    if refresh is not None:
        cookies.append(f"mawa_refresh={refresh}")
    if csrf is not None:
        cookies.append(f"mawa_csrf={csrf}")
    headers = {"Cookie": "; ".join(cookies)} if cookies else {}
    if header is not None:
        headers["X-CSRF-Token"] = header
    return headers


async def test_login_sets_both_cookies_and_keeps_body(client, session):
    await make_user(session, email=EMAIL, password=PASSWORD)
    r = await login(client)
    assert set(r.json()) == {"access_token", "token_type"}
    set_cookies = r.headers.get_list("set-cookie")
    refresh = next(c for c in set_cookies if c.startswith("mawa_refresh="))
    csrf = next(c for c in set_cookies if c.startswith("mawa_csrf="))
    low = refresh.lower()
    assert "httponly" in low and "samesite=lax" in low and "path=/api/auth" in low
    assert f"max-age={14 * 86400}" in low
    assert "httponly" not in csrf.lower()
    assert client.cookies.get("mawa_refresh") and client.cookies.get("mawa_csrf")


async def test_refresh_token_is_stored_hashed(client, session):
    await make_user(session, email=EMAIL, password=PASSWORD)
    await login(client)
    row = (await session.scalars(select(RefreshToken))).one()
    assert row.token_hash != client.cookies.get("mawa_refresh")
    assert len(row.token_hash) == 64
    assert row.revoked_at is None


async def test_refresh_rotates_and_new_access_token_works(client, session):
    await make_user(session, email=EMAIL, password=PASSWORD, role=Role.editor)
    await login(client)
    old = client.cookies.get("mawa_refresh")
    csrf = client.cookies.get("mawa_csrf")
    r = await client.post("/api/auth/refresh", headers=csrf_headers(client))
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert client.cookies.get("mawa_refresh") != old
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == EMAIL
    # the old token is rejected after use
    again = await client.post("/api/auth/refresh", headers=explicit(old, csrf, csrf))
    assert again.status_code == 401


async def test_reusing_rotated_token_revokes_family(client, session):
    await make_user(session, email=EMAIL, password=PASSWORD)
    await login(client)
    first = client.cookies.get("mawa_refresh")
    await client.post("/api/auth/refresh", headers=csrf_headers(client))
    newest = client.cookies.get("mawa_refresh")
    csrf = client.cookies.get("mawa_csrf")

    reuse = await client.post("/api/auth/refresh", headers=explicit(first, csrf, csrf))
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "REFRESH_REUSED"

    dead = await client.post("/api/auth/refresh", headers=explicit(newest, csrf, csrf))
    assert dead.status_code == 401
    rows = (await session.scalars(select(RefreshToken))).all()
    assert len(rows) == 2 and all(row.revoked_at is not None for row in rows)
    assert len({row.family_id for row in rows}) == 1


async def test_logout_revokes_token_and_clears_cookie(client, session):
    await make_user(session, email=EMAIL, password=PASSWORD)
    await login(client)
    token = client.cookies.get("mawa_refresh")
    csrf = client.cookies.get("mawa_csrf")
    r = await client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204
    assert any(c.startswith("mawa_refresh=") and "max-age=0" in c.lower() for c in r.headers.get_list("set-cookie"))
    after = await client.post("/api/auth/refresh", headers=explicit(token, csrf, csrf))
    assert after.status_code == 401


async def test_missing_or_wrong_csrf_is_403(client, session):
    await make_user(session, email=EMAIL, password=PASSWORD)
    await login(client)
    token = client.cookies.get("mawa_refresh")
    csrf = client.cookies.get("mawa_csrf")
    for path in ("/api/auth/refresh", "/api/auth/logout"):
        for headers in (
            explicit(token, csrf, None),
            explicit(token, csrf, "wrong"),
            explicit(token, None, csrf),
        ):
            r = await client.post(path, headers=headers)
            assert r.status_code == 403, (path, headers)
            assert r.json()["error"]["code"] == "CSRF_FAILED"
    # the token survived all rejected attempts
    ok = await client.post("/api/auth/refresh", headers=explicit(token, csrf, csrf))
    assert ok.status_code == 200


async def test_refresh_without_cookie_is_401(client):
    r = await client.post("/api/auth/refresh", headers=explicit(None, "c", "c"))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_unknown_refresh_token_is_401(client):
    r = await client.post("/api/auth/refresh", headers=explicit("not-a-real-token", "c", "c"))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_expired_refresh_token_is_401(client, session):
    await make_user(session, email=EMAIL, password=PASSWORD)
    await login(client)
    row = (await session.scalars(select(RefreshToken))).one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    await session.flush()
    r = await client.post("/api/auth/refresh", headers=csrf_headers(client))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_bearer_calls_need_no_csrf(client, session):
    user = await make_user(session)
    assert (await client.get("/api/auth/me", headers=auth_header(user))).status_code == 200
