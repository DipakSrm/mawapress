import io

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.cache import get_redis
from app.core.jobs import get_enqueuer
from app.core.storage import MAX_UPLOAD_BYTES, get_storage
from app.db.session import get_session
from app.main import create_app
from tests.factories import auth_header, make_user
from tests.media.conftest import files, image_bytes


async def upload(mclient, user, data, **kw):
    return await mclient.post("/api/media", files=files(data, **kw), headers=auth_header(user))


async def test_png_upload_records_dimensions_and_enqueues_variants(mclient, session, storage, jobs):
    user = await make_user(session)
    r = await upload(mclient, user, image_bytes("PNG", (400, 300)))
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["width"], body["height"]) == (400, 300)
    assert body["url"].startswith("/media/20") and body["url"].endswith(".png")
    assert body["variants"] == {}
    assert set(body) == {"id", "url", "width", "height", "alt_ne", "alt_en", "caption", "variants"}
    assert jobs == [("make_variants", (body["id"],))]
    assert len(await storage.get(body["url"].removeprefix("/"))) > 0


async def test_jpeg_upload_strips_exif(mclient, session, storage):
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    data = image_bytes("JPEG", (320, 200), exif=exif.tobytes())
    assert Image.open(io.BytesIO(data)).getexif().get(0x010F) == "SecretCameraMaker"
    user = await make_user(session)
    r = await upload(mclient, user, data, name="p.jpg", content_type="image/jpeg")
    assert r.status_code == 201, r.text
    stored = await storage.get(r.json()["url"].removeprefix("/"))
    assert b"SecretCameraMaker" not in stored
    assert len(Image.open(io.BytesIO(stored)).getexif()) == 0
    assert (r.json()["width"], r.json()["height"]) == (320, 200)


@pytest.mark.parametrize("fmt,ext", [("WEBP", "webp"), ("GIF", "gif"), ("JPEG", "jpg")])
async def test_other_allowed_formats(mclient, session, fmt, ext):
    user = await make_user(session)
    r = await upload(mclient, user, image_bytes(fmt), name="x.bin", content_type="application/octet-stream")
    assert r.status_code == 201, r.text
    assert r.json()["url"].endswith(f".{ext}")


async def test_oversize_file_is_413(mclient, session, jobs):
    user = await make_user(session)
    r = await upload(mclient, user, b"x" * (MAX_UPLOAD_BYTES + 1))
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert jobs == []


async def test_text_renamed_to_jpg_is_415(mclient, session):
    user = await make_user(session)
    r = await upload(mclient, user, b"just some text, not an image", name="evil.jpg", content_type="image/jpeg")
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "UNSUPPORTED_MEDIA"


async def test_unallowed_image_format_is_415(mclient, session):
    user = await make_user(session)
    r = await upload(mclient, user, image_bytes("BMP"), name="a.png")
    assert r.status_code == 415


async def test_decompression_bomb_is_rejected(mclient, session):
    buf = io.BytesIO()
    Image.new("L", (7000, 7000)).save(buf, "PNG")  # 49 megapixels, tiny on disk
    user = await make_user(session)
    r = await upload(mclient, user, buf.getvalue())
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "IMAGE_TOO_LARGE"


async def test_upload_requires_login(mclient):
    r = await mclient.post("/api/media", files=files(image_bytes()))
    assert r.status_code == 401


async def test_upload_survives_enqueue_failure(session, fake_redis, storage):
    async def broken(name, *args):
        raise ConnectionError("redis down")

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_enqueuer] = lambda: broken
    user = await make_user(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/media", files=files(image_bytes()), headers=auth_header(user))
    assert r.status_code == 201
