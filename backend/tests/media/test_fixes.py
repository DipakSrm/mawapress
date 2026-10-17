import io
from contextlib import asynccontextmanager

import pytest
from PIL import Image
from sqlalchemy import select, text

from app.core.config import Settings
from app.core.storage import LocalStorage
from app.db.outbox import OutboxEvent
from app.modules.media.models import Media
from app.modules.media.variants import make_variants
from app.modules.public.service import FEED_GEN_KEY, post_cache_key
from app.modules.users.models import Role
from tests.factories import auth_header, create_post_via_api, make_category, make_user, publish_via_api
from tests.media.conftest import files, image_bytes


def ctx_for(session, storage, redis=None) -> dict:
    @asynccontextmanager
    async def factory():
        yield session

    return {"session_factory": factory, "storage": storage, "cache_redis": redis}


async def upload(mclient, user, data):
    r = await mclient.post("/api/media", files=files(data), headers=auth_header(user))
    assert r.status_code == 201, r.text
    return r.json()


# ---- body limits ----------------------------------------------------------------------------

async def test_declared_oversize_content_length_is_413_without_auth(mclient):
    r = await mclient.post(
        "/api/media", content=b"x" * 10, headers={"Content-Length": str(12 * 1024 * 1024), "Content-Type": "text/plain"}
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_chunked_oversize_body_is_413_without_auth(mclient):
    async def body():
        yield b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.png"\r\n\r\n'
        for _ in range(13):
            yield b"x" * (1024 * 1024)
        yield b"\r\n--b--\r\n"

    r = await mclient.post("/api/media", content=body(), headers={"Content-Type": "multipart/form-data; boundary=b"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_other_routes_cap_bodies_at_1mb(mclient):
    r = await mclient.post("/api/auth/login", content=b"x" * (1024 * 1024 + 1), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    r = await mclient.post("/api/auth/login", json={"email": "a@b.co", "password": "x" * 100})
    assert r.status_code != 413


# ---- MPO ------------------------------------------------------------------------------------

async def test_mpo_phone_photo_is_accepted_as_jpeg(mclient, session, storage):
    buf = io.BytesIO()
    first, second = Image.new("RGB", (320, 200), (10, 20, 30)), Image.new("RGB", (320, 200), (200, 0, 0))
    first.save(buf, "MPO", save_all=True, append_images=[second])
    assert Image.open(io.BytesIO(buf.getvalue())).format == "MPO"
    user = await make_user(session)
    media = await upload(mclient, user, buf.getvalue())
    assert media["url"].endswith(".jpg")
    stored = Image.open(io.BytesIO(await storage.get(media["url"].removeprefix("/"))))
    assert stored.format == "JPEG" and stored.size == (320, 200)
    row = await session.scalar(select(Media))
    assert row.mime == "image/jpeg"


# ---- GIF ------------------------------------------------------------------------------------

def gif(frames: int, size=(4, 4), durations=None) -> bytes:
    imgs = [Image.new("RGB", size, (i % 256, (i * 7) % 256, (i * 13) % 256)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, "GIF", save_all=True, append_images=imgs[1:], duration=durations or 100, loop=0)
    return buf.getvalue()


async def test_gif_keeps_per_frame_durations(mclient, session, storage):
    user = await make_user(session)
    media = await upload(mclient, user, gif(3, durations=[50, 200, 400]))
    out = Image.open(io.BytesIO(await storage.get(media["url"].removeprefix("/"))))
    assert out.n_frames == 3
    seen = []
    for i in range(3):
        out.seek(i)
        seen.append(out.info["duration"])
    assert seen == [50, 200, 400]


async def test_gif_with_too_many_frames_is_413(mclient, session):
    user = await make_user(session)
    r = await mclient.post("/api/media", files=files(gif(301)), headers=auth_header(user))
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "IMAGE_TOO_LARGE"


async def test_gif_with_too_many_total_pixels_is_413(mclient, session):
    user = await make_user(session)
    r = await mclient.post("/api/media", files=files(gif(260, size=(700, 600))), headers=auth_header(user))  # 109 MP
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "IMAGE_TOO_LARGE"


# ---- variants -------------------------------------------------------------------------------

async def test_variant_keys_are_stored_not_urls(mclient, session, storage):
    user = await make_user(session)
    media = await upload(mclient, user, image_bytes("PNG", (900, 500)))
    await make_variants(ctx_for(session, storage), media["id"])
    row = await session.scalar(select(Media))
    await session.refresh(row)
    assert set(row.variant_keys) == {"w320", "w640", "og"}
    assert all(v.startswith("media/") and not v.startswith("/") for v in row.variant_keys.values())
    assert row.variants["w320"] == "/" + row.variant_keys["w320"]  # URL derived at read time


async def test_og_variant_never_upscales_small_sources(mclient, session, storage):
    user = await make_user(session)
    media = await upload(mclient, user, image_bytes("PNG", (700, 400)))
    await make_variants(ctx_for(session, storage), media["id"])
    row = await session.scalar(select(Media))
    og = Image.open(io.BytesIO(await storage.get(row.variant_keys["og"])))
    assert og.size == (700, 367)  # cover crop, 1200:630 aspect, largest that fits


async def test_og_variant_for_tall_small_source(mclient, session, storage):
    user = await make_user(session)
    media = await upload(mclient, user, image_bytes("PNG", (300, 600)))
    await make_variants(ctx_for(session, storage), media["id"])
    row = await session.scalar(select(Media))
    og = Image.open(io.BytesIO(await storage.get(row.variant_keys["og"])))
    assert og.size == (300, 157)


class DeletingStorage(LocalStorage):
    """Deletes the media row the first time a variant is written, as a concurrent DELETE would."""

    def __init__(self, inner: LocalStorage, session):
        super().__init__(inner.root, inner.base_url)
        self.session, self.fired = session, False

    async def put(self, key, data, content_type):
        await super().put(key, data, content_type)
        if not self.fired:
            self.fired = True
            row = await self.session.scalar(select(Media))
            await self.session.delete(row)
            await self.session.flush()


async def test_media_deleted_mid_job_removes_written_variants(mclient, session, storage):
    user = await make_user(session)
    media = await upload(mclient, user, image_bytes("PNG", (900, 500)))
    original_key = media["url"].removeprefix("/")
    racing = DeletingStorage(storage, session)
    await make_variants(ctx_for(session, racing), media["id"])
    stem = original_key.rsplit(".", 1)[0]
    for name in ("w320", "w640", "og"):
        with pytest.raises(FileNotFoundError):
            await storage.get(f"{stem}-{name}.webp")


async def test_variants_refresh_seo_events_and_caches_of_live_posts(mclient, session, storage, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor, image_bytes("PNG", (2000, 1000)))
    post = await create_post_via_api(mclient, editor, cat, featured_media_id=media["id"])
    await publish_via_api(mclient, editor, post)
    before = (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()
    assert before["seo"]["og_image"].endswith(".png")
    gen = await fake_redis.get(FEED_GEN_KEY)
    await make_variants(ctx_for(session, storage, fake_redis), media["id"])
    assert await fake_redis.get(post_cache_key("ne", "badhi-samachar")) is None
    assert await fake_redis.get(FEED_GEN_KEY) != gen
    after = (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()
    assert after["seo"]["og_image"].endswith("-og.webp")
    events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()
    assert len(events) == 1 and events[0].payload["post_id"] == post["id"]


async def test_variants_for_unused_or_draft_media_emit_nothing(mclient, session, storage, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor, image_bytes("PNG", (900, 500)))
    await create_post_via_api(mclient, editor, cat, featured_media_id=media["id"])  # a draft
    gen = await fake_redis.get(FEED_GEN_KEY)
    await make_variants(ctx_for(session, storage, fake_redis), media["id"])
    assert await fake_redis.get(FEED_GEN_KEY) == gen
    assert (await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all() == []


# ---- alt/caption patch ----------------------------------------------------------------------

async def test_patching_alt_of_live_featured_media_invalidates_and_emits(mclient, session, fake_redis):
    editor = await make_user(session, role=Role.editor)
    cat = await make_category(session)
    media = await upload(mclient, editor, image_bytes("PNG", (400, 300)))
    post = await create_post_via_api(mclient, editor, cat, featured_media_id=media["id"])
    await publish_via_api(mclient, editor, post)
    assert (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()["image"]["alt"] == "बाढी समाचार"
    gen = await fake_redis.get(FEED_GEN_KEY)
    r = await mclient.patch(f"/api/media/{media['id']}", json={"alt_ne": "नयाँ"}, headers=auth_header(editor))
    assert r.status_code == 200
    assert await fake_redis.get(FEED_GEN_KEY) != gen
    assert (await mclient.get("/api/public/posts/ne/badhi-samachar")).json()["image"]["alt"] == "नयाँ"
    assert len((await session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "post.updated"))).all()) == 1
    # an unchanged patch is not a public change
    gen = await fake_redis.get(FEED_GEN_KEY)
    await mclient.patch(f"/api/media/{media['id']}", json={"alt_ne": "नयाँ"}, headers=auth_header(editor))
    assert await fake_redis.get(FEED_GEN_KEY) == gen


# ---- config ---------------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["s3_endpoint", "s3_bucket", "s3_access_key", "s3_secret_key", "media_base_url"])
def test_s3_storage_requires_all_settings(missing):
    full = dict(storage="s3", s3_endpoint="https://x", s3_bucket="b", s3_access_key="a", s3_secret_key="s",
                media_base_url="https://cdn.example.com")
    assert Settings(**full).storage == "s3"
    full[missing] = "" if missing == "media_base_url" else None
    with pytest.raises(ValueError):
        Settings(**full)


def test_unknown_storage_is_rejected():
    with pytest.raises(ValueError):
        Settings(storage="gcs")


# ---- patch vs. concurrent delete -----------------------------------------------------------

async def test_patch_waits_for_a_concurrent_delete_and_then_404s(engine, tmp_path):
    """patch_media takes the media row FOR UPDATE: it queues behind an in-flight delete and sees a 404,
    instead of loading the row, losing it to the delete and failing the UPDATE with a 500."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.errors import AppError
    from app.modules.media import service
    from app.modules.media.schemas import MediaPatch

    async with AsyncSession(engine, expire_on_commit=False) as s:
        user = await make_user(s, role=Role.editor)
        media = Media(key=f"media/race/{uuid_hex()}.png", mime="image/png", width=1, height=1, size_bytes=1,
                      uploader_id=user.id, variant_keys={})
        s.add(media)
        await s.commit()
        media_id, user_id = media.id, user.id

    deleter = AsyncSession(engine)
    patcher = AsyncSession(engine, expire_on_commit=False)
    try:
        await deleter.execute(select(Media).where(Media.id == media_id).with_for_update())  # the delete is in flight
        patcher_user = await patcher.get(type(user), user_id)
        task = asyncio.create_task(service.patch_media(patcher, patcher_user, media_id, MediaPatch(alt_ne="x")))
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done, "patch_media must block on the row lock while a delete is in flight"
        await deleter.delete(await deleter.get(Media, media_id))
        await deleter.commit()
        with pytest.raises(AppError) as exc:
            await asyncio.wait_for(task, timeout=5)
        assert exc.value.status == 404
    finally:
        await deleter.close()
        await patcher.close()
        async with AsyncSession(engine) as s:
            await s.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            await s.commit()


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex
