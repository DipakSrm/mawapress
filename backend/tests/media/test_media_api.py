from httpx import ASGITransport, AsyncClient

from app.core.cache import get_redis
from app.core.config import get_settings
from app.db.session import get_session
from app.main import create_app
from app.modules.posts.render import render_html
from app.modules.users.models import Role
from tests.factories import auth_header, create_post_via_api, make_category, make_user
from tests.media.conftest import files, image_bytes


async def upload(mclient, user, **kw):
    r = await mclient.post("/api/media", files=files(image_bytes(**kw)), headers=auth_header(user))
    assert r.status_code == 201, r.text
    return r.json()


async def test_list_is_staff_only_newest_first_and_searchable(mclient, session):
    reporter = await make_user(session)
    first = await upload(mclient, reporter)
    second = await upload(mclient, reporter)
    await mclient.patch(f"/api/media/{first['id']}", json={"caption": "Koshi flood"}, headers=auth_header(reporter))
    assert (await mclient.get("/api/media")).status_code == 401
    r = await mclient.get("/api/media", headers=auth_header(reporter))
    assert [m["id"] for m in r.json()["items"]] == [second["id"], first["id"]]
    assert r.json()["total"] == 2
    found = await mclient.get("/api/media", params={"q": "koshi"}, headers=auth_header(reporter))
    assert [m["id"] for m in found.json()["items"]] == [first["id"]]
    page = await mclient.get("/api/media", params={"limit": 1, "offset": 1}, headers=auth_header(reporter))
    assert [m["id"] for m in page.json()["items"]] == [first["id"]]


async def test_patch_alt_and_caption_authz(mclient, session):
    owner = await make_user(session)
    other = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    media = await upload(mclient, owner)
    body = {"alt_ne": "बाढी", "alt_en": "Flood", "caption": "River"}
    url = f"/api/media/{media['id']}"
    assert (await mclient.patch(url, json=body)).status_code == 401
    assert (await mclient.patch(url, json=body, headers=auth_header(other))).status_code == 403
    ok = await mclient.patch(url, json=body, headers=auth_header(owner))
    assert ok.status_code == 200
    assert (ok.json()["alt_ne"], ok.json()["alt_en"], ok.json()["caption"]) == ("बाढी", "Flood", "River")
    assert (await mclient.patch(url, json={"caption": "Edited"}, headers=auth_header(editor))).json()["caption"] == "Edited"
    missing = "/api/media/00000000-0000-0000-0000-000000000000"
    assert (await mclient.patch(missing, json=body, headers=auth_header(editor))).status_code == 404


async def test_delete_requires_editor_and_removes_files(mclient, session, storage):
    reporter = await make_user(session)
    editor = await make_user(session, role=Role.editor)
    media = await upload(mclient, reporter)
    key = media["url"].removeprefix("/")
    url = f"/api/media/{media['id']}"
    assert (await mclient.delete(url)).status_code == 401
    assert (await mclient.delete(url, headers=auth_header(reporter))).status_code == 403
    assert (await mclient.delete(url, headers=auth_header(editor))).status_code == 204
    assert (await mclient.get("/api/media", headers=auth_header(editor))).json()["total"] == 0
    try:
        await storage.get(key)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("file should be gone")
    assert (await mclient.delete(url, headers=auth_header(editor))).status_code == 404


async def test_delete_media_in_use_is_409(mclient, session, storage):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor)
    await create_post_via_api(mclient, editor, cat, featured_media_id=media["id"])
    r = await mclient.delete(f"/api/media/{media['id']}", headers=auth_header(editor))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "MEDIA_IN_USE"
    assert len(await storage.get(media["url"].removeprefix("/"))) > 0


async def test_local_storage_urls_pass_the_renderer(mclient, session):
    media = await upload(mclient, await make_user(session))
    html = render_html({"type": "doc", "content": [{"type": "image", "attrs": {"src": media["url"], "alt": "x"}}]})
    assert f'src="{media["url"]}"' in html


async def test_local_files_are_served_from_media_mount(session, fake_redis, tmp_path):
    settings = get_settings()
    old = settings.media_local_dir
    settings.media_local_dir = str(tmp_path)
    try:
        app = create_app()
    finally:
        settings.media_local_dir = old
    (tmp_path / "media" / "2026").mkdir(parents=True)
    (tmp_path / "media" / "2026" / "a.txt").write_bytes(b"hello")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/media/2026/a.txt")
    assert r.status_code == 200 and r.content == b"hello"
