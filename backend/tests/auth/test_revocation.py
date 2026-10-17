from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.modules.auth.models import RefreshToken
from app.modules.users.models import Role
from tests.auth.test_auth import assert_invalid_token, forged
from tests.factories import auth_header, make_user

PASSWORD = "revoke-pass-1"


async def login_as(client, email: str):
    r = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def assert_all_dead(client, session, headers, user):
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"
    rows = (await session.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))).all()
    assert rows and all(row.revoked_at is not None for row in rows)
    refresh = await client.post(
        "/api/auth/refresh",
        headers={"X-CSRF-Token": "c", "Cookie": "mawa_csrf=c; mawa_refresh=" + client.cookies.get("mawa_refresh")},
    )
    assert refresh.status_code == 401


async def test_self_password_change_revokes_everything(client, session):
    user = await make_user(session, email="a@mawapress.com", password=PASSWORD)
    headers = await login_as(client, "a@mawapress.com")
    r = await client.patch(
        "/api/auth/me", json={"current_password": PASSWORD, "new_password": "brand-new-pass-2"}, headers=headers
    )
    assert r.status_code == 200
    await assert_all_dead(client, session, headers, user)


async def test_admin_password_reset_revokes_everything(client, session):
    admin = await make_user(session, role=Role.admin)
    user = await make_user(session, email="b@mawapress.com", password=PASSWORD)
    headers = await login_as(client, "b@mawapress.com")
    r = await client.post(
        f"/api/users/{user.id}/password", json={"password": "brand-new-pass-2"}, headers=auth_header(admin)
    )
    assert r.status_code == 204
    await assert_all_dead(client, session, headers, user)
    assert (await client.get("/api/auth/me", headers=auth_header(admin))).status_code == 200


@pytest.mark.parametrize("patch", [{"is_active": False}, {"role": "editor"}])
async def test_deactivation_and_role_change_revoke_everything(client, session, patch):
    admin = await make_user(session, role=Role.admin)
    user = await make_user(session, email="c@mawapress.com", password=PASSWORD, role=Role.reporter)
    headers = await login_as(client, "c@mawapress.com")
    r = await client.patch(f"/api/users/{user.id}", json=patch, headers=auth_header(admin))
    assert r.status_code == 200
    await assert_all_dead(client, session, headers, user)


async def test_unchanged_role_or_rename_keeps_sessions(client, session):
    admin = await make_user(session, role=Role.admin)
    user = await make_user(session, email="d@mawapress.com", password=PASSWORD, role=Role.reporter)
    headers = await login_as(client, "d@mawapress.com")
    r = await client.patch(f"/api/users/{user.id}", json={"name": "New", "role": "reporter"}, headers=auth_header(admin))
    assert r.status_code == 200
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 200


async def test_token_without_matching_tv_is_rejected(client, session):
    user = await make_user(session)
    now = utcnow()
    base = {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=15)}
    await assert_invalid_token(client, forged(base))
    await assert_invalid_token(client, forged({**base, "tv": user.token_version + 1}))
    await assert_invalid_token(client, forged({**base, "tv": "0"}))


async def test_pre_change_refresh_token_cannot_mint_after_password_change(client, session):
    from tests.auth.test_refresh import explicit

    user = await make_user(session, email="e@mawapress.com", password=PASSWORD)
    headers = await login_as(client, "e@mawapress.com")
    old = client.cookies.get("mawa_refresh")
    csrf = client.cookies.get("mawa_csrf")
    row = (await session.scalars(select(RefreshToken))).one()
    r = await client.patch(
        "/api/auth/me", json={"current_password": PASSWORD, "new_password": "brand-new-pass-2"}, headers=headers
    )
    assert r.status_code == 200
    # as if a racing rotation had left a live token minted before the change
    row.revoked_at = None
    await session.flush()
    out = await client.post("/api/auth/refresh", headers=explicit(old, csrf, csrf))
    assert out.status_code == 401
    assert out.json()["error"]["code"] == "INVALID_TOKEN"
    assert user.token_version >= 1
