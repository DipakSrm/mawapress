from app.modules.users.models import Role
from tests.factories import auth_header, make_user


async def login(client, email: str, password: str):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def create_user(client, admin, **overrides):
    body = {"email": "asha@mawapress.com", "name": "Asha Rai", "role": "reporter", "password": "long-enough-1"}
    body.update(overrides)
    return await client.post("/api/users", json=body, headers=auth_header(admin))


async def test_only_admins_reach_user_admin(client, session):
    editor = await make_user(session, role=Role.editor)
    assert (await client.get("/api/users")).status_code == 401
    denied = await client.get("/api/users", headers=auth_header(editor))
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_admin_creates_user_with_lowercased_email_and_it_can_log_in(client, session):
    admin = await make_user(session, role=Role.admin)
    r = await create_user(client, admin, email="Asha.Rai@Mawapress.com", bio="Biratnagar desk")
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "asha.rai@mawapress.com"
    assert body["role"] == "reporter"
    assert body["is_active"] is True
    assert body["bio"] == "Biratnagar desk"
    assert "password_hash" not in body and "password" not in body

    ok = await login(client, "ASHA.RAI@mawapress.com", "long-enough-1")
    assert ok.status_code == 200


async def test_duplicate_email_any_case_is_409(client, session):
    admin = await make_user(session, role=Role.admin)
    assert (await create_user(client, admin, email="asha@mawapress.com")).status_code == 201
    dup = await create_user(client, admin, email="Asha@MAWAPRESS.com")
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_create_validates_password_role_and_name(client, session):
    admin = await make_user(session, role=Role.admin)
    assert (await create_user(client, admin, password="short-9ch")).status_code == 422
    assert (await create_user(client, admin, role="owner")).status_code == 422
    assert (await create_user(client, admin, name="   ")).status_code == 422
    assert (await create_user(client, admin, email="not-an-email")).status_code == 422


async def test_list_users_includes_everyone(client, session):
    admin = await make_user(session, role=Role.admin, name="Admin")
    await make_user(session, name="Reporter One")
    r = await client.get("/api/users", headers=auth_header(admin))
    assert r.status_code == 200
    names = {u["name"] for u in r.json()}
    assert {"Admin", "Reporter One"} <= names


async def test_admin_updates_name_role_and_deactivates(client, session):
    admin = await make_user(session, role=Role.admin)
    target = await make_user(session, name="Old Name")
    r = await client.patch(
        f"/api/users/{target.id}",
        json={"name": "  New Name ", "role": "editor", "is_active": False},
        headers=auth_header(admin),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"
    assert r.json()["role"] == "editor"
    assert r.json()["is_active"] is False
    # A deactivated user's existing token stops working.
    assert (await client.get("/api/auth/me", headers=auth_header(target))).status_code == 401


async def test_admin_cannot_deactivate_or_demote_self(client, session):
    admin = await make_user(session, role=Role.admin)
    url = f"/api/users/{admin.id}"
    for patch in ({"is_active": False}, {"role": "editor"}):
        r = await client.patch(url, json=patch, headers=auth_header(admin))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "CANNOT_MODIFY_SELF"
    renamed = await client.patch(url, json={"name": "Still Admin", "role": "admin"}, headers=auth_header(admin))
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Still Admin"


async def test_patch_rejects_unknown_fields_and_unknown_user(client, session):
    admin = await make_user(session, role=Role.admin)
    target = await make_user(session)
    bad = await client.patch(f"/api/users/{target.id}", json={"email": "x@mawapress.com"}, headers=auth_header(admin))
    assert bad.status_code == 422
    missing = await client.patch(
        "/api/users/00000000-0000-0000-0000-000000000000", json={"name": "x"}, headers=auth_header(admin)
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_admin_sets_password(client, session):
    admin = await make_user(session, role=Role.admin)
    target = await make_user(session, email="pw@mawapress.com", password="old-password-1")
    url = f"/api/users/{target.id}/password"
    short = await client.post(url, json={"password": "123456789"}, headers=auth_header(admin))
    assert short.status_code == 422
    r = await client.post(url, json={"password": "new-password-1"}, headers=auth_header(admin))
    assert r.status_code == 204
    assert (await login(client, "pw@mawapress.com", "old-password-1")).status_code == 401
    assert (await login(client, "pw@mawapress.com", "new-password-1")).status_code == 200
