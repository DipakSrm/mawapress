from datetime import timedelta

import jwt
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import get_session
from app.main import create_app
from app.modules.auth import router as auth_router
from app.modules.auth.deps import require_role
from app.modules.auth.security import ALGORITHM, DUMMY_PASSWORD_HASH
from app.modules.users.models import Role, User
from tests.factories import auth_header, make_user


async def test_login_returns_token_usable_on_me(client, session):
    await make_user(session, email="editor@mawapress.com", role=Role.editor, password="correct-horse-1")
    r = await client.post("/api/auth/login", json={"email": "Editor@Mawapress.com", "password": "correct-horse-1"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "editor@mawapress.com"
    assert me.json()["role"] == "editor"


async def test_wrong_password_unknown_email_and_inactive_all_401(client, session):
    await make_user(session, email="a@mawapress.com", password="right-pass-1")
    await make_user(session, email="off@mawapress.com", password="right-pass-1", is_active=False)
    for email, pw in [("a@mawapress.com", "nope"), ("ghost@mawapress.com", "x"), ("off@mawapress.com", "right-pass-1")]:
        r = await client.post("/api/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_me_requires_valid_token(client):
    assert (await client.get("/api/auth/me")).json()["error"]["code"] == "NOT_AUTHENTICATED"
    r = await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_require_role_blocks_lower_roles(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session

    @app.get("/editor-only")
    async def editor_only(user: User = Depends(require_role(Role.editor))):
        return {"ok": True}

    reporter = await make_user(session, role=Role.reporter)
    editor = await make_user(session, role=Role.editor)
    admin = await make_user(session, role=Role.admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        denied = await c.get("/editor-only", headers=auth_header(reporter))
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "FORBIDDEN_ROLE"
        assert (await c.get("/editor-only", headers=auth_header(editor))).status_code == 200
        assert (await c.get("/editor-only", headers=auth_header(admin))).status_code == 200


def forged(claims: dict, secret: str | None = None) -> dict[str, str]:
    token = jwt.encode(claims, secret or get_settings().jwt_secret, algorithm=ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


async def assert_invalid_token(client, headers):
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_expired_token_is_401(client, session):
    user = await make_user(session)
    past = utcnow() - timedelta(hours=1)
    await assert_invalid_token(client, forged({"sub": str(user.id), "iat": past, "exp": past + timedelta(minutes=15)}))


async def test_wrong_signature_is_401(client, session):
    user = await make_user(session)
    now = utcnow()
    claims = {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=15)}
    await assert_invalid_token(client, forged(claims, secret="another-secret-that-is-at-least-32-chars"))


async def test_deactivated_user_with_valid_token_is_401(client, session):
    user = await make_user(session, is_active=False)
    await assert_invalid_token(client, auth_header(user))


async def test_token_missing_required_claims_is_401(client, session):
    user = await make_user(session)
    now = utcnow()
    full = {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=15)}
    for missing in ("exp", "sub", "iat"):
        claims = {k: v for k, v in full.items() if k != missing}
        await assert_invalid_token(client, forged(claims))


async def test_non_string_or_malformed_sub_is_401_not_500(client, session):
    now = utcnow()
    for sub in (12345, ["x"], "not-a-uuid"):
        await assert_invalid_token(client, forged({"sub": sub, "iat": now, "exp": now + timedelta(minutes=15)}))


async def test_login_runs_password_hash_even_for_unknown_or_inactive_user(client, session, monkeypatch):
    await make_user(session, email="off2@mawapress.com", password="right-pass-1", is_active=False)
    seen: list[str] = []
    real_verify = auth_router.verify_password

    def spy(password: str, password_hash: str) -> bool:
        seen.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_router, "verify_password", spy)
    for email in ("ghost2@mawapress.com", "off2@mawapress.com"):
        r = await client.post("/api/auth/login", json={"email": email, "password": "right-pass-1"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert seen == [DUMMY_PASSWORD_HASH, DUMMY_PASSWORD_HASH]
