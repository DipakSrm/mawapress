from tests.factories import auth_header, make_user


async def test_me_includes_bio(client, session):
    user = await make_user(session)
    r = await client.get("/api/auth/me", headers=auth_header(user))
    assert r.status_code == 200
    assert r.json()["bio"] is None


async def test_update_own_name_and_bio(client, session):
    user = await make_user(session, name="Old")
    r = await client.patch(
        "/api/auth/me", json={"name": "  Sita Rai ", "bio": "Covers Urlabari"}, headers=auth_header(user)
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Sita Rai"
    assert r.json()["bio"] == "Covers Urlabari"

    cleared = await client.patch("/api/auth/me", json={"bio": ""}, headers=auth_header(user))
    assert cleared.json()["bio"] is None
    assert cleared.json()["name"] == "Sita Rai"


async def test_change_own_password_requires_current_password(client, session):
    user = await make_user(session, email="me@mawapress.com", password="first-password-1")
    url, headers = "/api/auth/me", auth_header(user)

    missing = await client.patch(url, json={"new_password": "second-password-2"}, headers=headers)
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    wrong = await client.patch(
        url, json={"current_password": "nope", "new_password": "second-password-2"}, headers=headers
    )
    assert wrong.status_code == 403

    ok = await client.patch(
        url, json={"current_password": "first-password-1", "new_password": "second-password-2"}, headers=headers
    )
    assert ok.status_code == 200
    login = await client.post("/api/auth/login", json={"email": "me@mawapress.com", "password": "second-password-2"})
    assert login.status_code == 200


async def test_me_cannot_change_role_or_use_short_password(client, session):
    user = await make_user(session, password="first-password-1")
    headers = auth_header(user)
    assert (await client.patch("/api/auth/me", json={"role": "admin"}, headers=headers)).status_code == 422
    short = await client.patch(
        "/api/auth/me", json={"current_password": "first-password-1", "new_password": "short"}, headers=headers
    )
    assert short.status_code == 422


async def test_me_update_requires_login(client):
    assert (await client.patch("/api/auth/me", json={"name": "x"})).status_code == 401


async def test_current_password_alone_is_422_new_password_required(client, session):
    user = await make_user(session, password="first-password-1")
    r = await client.patch("/api/auth/me", json={"current_password": "first-password-1"}, headers=auth_header(user))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "NEW_PASSWORD_REQUIRED"


async def test_new_password_equal_to_current_is_422_password_unchanged(client, session):
    user = await make_user(session, password="first-password-1")
    r = await client.patch(
        "/api/auth/me",
        json={"current_password": "first-password-1", "new_password": "first-password-1"},
        headers=auth_header(user),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PASSWORD_UNCHANGED"
    assert user.token_version == 0  # nothing was revoked
