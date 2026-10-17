import io
import uuid
from contextlib import asynccontextmanager

from PIL import Image

from app.modules.media.variants import make_variants
from tests.factories import auth_header, make_user
from tests.media.conftest import files, image_bytes


def make_ctx(session, storage) -> dict:
    @asynccontextmanager
    async def factory():
        yield session

    return {"session_factory": factory, "storage": storage}


async def upload_and_make(mclient, session, storage, size):
    user = await make_user(session)
    r = await mclient.post("/api/media", files=files(image_bytes("PNG", size)), headers=auth_header(user))
    assert r.status_code == 201, r.text
    await make_variants(make_ctx(session, storage), r.json()["id"])
    return user, r.json()["id"]


async def size_of(storage, url: str) -> tuple[int, int, str]:
    img = Image.open(io.BytesIO(await storage.get(url.removeprefix("/"))))
    return img.width, img.height, img.format


async def test_large_image_gets_all_widths_and_og(mclient, session, storage):
    user, _ = await upload_and_make(mclient, session, storage, (2000, 1000))
    listing = (await mclient.get("/api/media", headers=auth_header(user))).json()
    variants = listing["items"][0]["variants"]
    assert set(variants) == {"w320", "w640", "w1024", "w1600", "og"}
    for name, width in [("w320", 320), ("w640", 640), ("w1024", 1024), ("w1600", 1600)]:
        assert await size_of(storage, variants[name]) == (width, width // 2, "WEBP")
    assert await size_of(storage, variants["og"]) == (1200, 630, "WEBP")


async def test_variants_never_upscale(mclient, session, storage):
    user, _ = await upload_and_make(mclient, session, storage, (700, 400))
    variants = (await mclient.get("/api/media", headers=auth_header(user))).json()["items"][0]["variants"]
    assert set(variants) == {"w320", "w640", "og"}
    assert (await size_of(storage, variants["w640"]))[0] == 640


async def test_make_variants_is_idempotent_and_ignores_missing_media(mclient, session, storage):
    user, media_id = await upload_and_make(mclient, session, storage, (900, 600))
    await make_variants(make_ctx(session, storage), media_id)
    await make_variants(make_ctx(session, storage), str(uuid.uuid4()))  # deleted meanwhile: no error
    variants = (await mclient.get("/api/media", headers=auth_header(user))).json()["items"][0]["variants"]
    assert set(variants) == {"w320", "w640", "og"}


def test_make_variants_is_registered_with_the_worker():
    from app.worker.settings import WorkerSettings

    assert make_variants in WorkerSettings.functions
