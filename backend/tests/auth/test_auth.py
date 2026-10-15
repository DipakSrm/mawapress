from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.main import create_app
from app.modules.auth.deps import require_role
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
