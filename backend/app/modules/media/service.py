import asyncio
import logging
import uuid

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.storage import MAX_UPLOAD_BYTES, Storage
from app.db.base import utcnow
from app.modules.auth.deps import ROLE_RANK
from app.modules.media.models import Media
from app.modules.media.processing import NotAnImage, TooManyPixels, clean_upload
from app.modules.media.schemas import MediaPatch
from app.modules.posts import service as posts_service
from app.modules.posts.models import Post
from app.modules.users.models import Role, User

log = logging.getLogger("mawa.media")


async def upload(session: AsyncSession, storage: Storage, user: User, raw: bytes) -> Media:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "Files can be at most 10 MB")
    try:
        cleaned = await asyncio.to_thread(clean_upload, raw)
    except NotAnImage:
        raise AppError(415, "UNSUPPORTED_MEDIA", "Only JPEG, PNG, WebP and GIF images are accepted") from None
    except TooManyPixels:
        raise AppError(413, "IMAGE_TOO_LARGE", "Images can be at most 40 megapixels") from None
    media_id = uuid.uuid4()
    now = utcnow()
    key = f"media/{now:%Y}/{now:%m}/{media_id}.{cleaned.ext}"
    await storage.put(key, cleaned.data, cleaned.mime)
    media = Media(
        id=media_id, key=key, mime=cleaned.mime, width=cleaned.width, height=cleaned.height,
        size_bytes=len(cleaned.data), uploader_id=user.id, variant_keys={},
    )
    session.add(media)
    try:
        await session.commit()
    except Exception:
        await storage.delete(key)
        raise
    return media


async def get_media(session: AsyncSession, media_id: uuid.UUID) -> Media:
    media = await session.get(Media, media_id)
    if media is None:
        raise AppError(404, "MEDIA_NOT_FOUND", "Media not found")
    return media


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_media(session: AsyncSession, *, q: str | None, limit: int, offset: int) -> tuple[list[Media], int]:
    stmt = select(Media)
    if q:
        pattern = f"%{_escape_like(q)}%"
        stmt = stmt.where(or_(*(c.ilike(pattern, escape="\\") for c in (Media.alt_ne, Media.alt_en, Media.caption))))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(stmt.order_by(Media.created_at.desc(), Media.id.desc()).limit(limit).offset(offset))
    return list(rows), total or 0


async def patch_media(
    session: AsyncSession, user: User, media_id: uuid.UUID, data: MediaPatch
) -> tuple[Media, list[Post]]:
    """Returns the media and the live posts whose public pages changed (the caller invalidates their caches)."""
    # FOR UPDATE: a concurrent delete either finishes first (404 here) or waits for this commit.
    media = await session.scalar(
        select(Media).where(Media.id == media_id).with_for_update().execution_options(populate_existing=True)
    )
    if media is None:
        raise AppError(404, "MEDIA_NOT_FOUND", "Media not found")
    if media.uploader_id != user.id and ROLE_RANK[user.role] < ROLE_RANK[Role.editor]:
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot edit this media")
    changed = False
    for field in data.model_fields_set:
        if getattr(media, field) != getattr(data, field):
            setattr(media, field, getattr(data, field))
            changed = True
    live: list[Post] = []
    if changed:  # alt and caption show on cards and pages, not in seo_auto
        live = await posts_service.touch_posts_for_media(session, media_id, refresh_seo=False)
    await session.commit()
    return media, live


async def delete_media(session: AsyncSession, storage: Storage, media_id: uuid.UUID) -> None:
    # Lock the row first: post create/update take FOR SHARE on it, so no post can adopt this media
    # between the in-use check and the delete (the FK's SET NULL would silently drop its image).
    media = await session.scalar(
        select(Media).where(Media.id == media_id).with_for_update().execution_options(populate_existing=True)
    )
    if media is None:
        raise AppError(404, "MEDIA_NOT_FOUND", "Media not found")
    if await session.scalar(select(exists().where(Post.featured_media_id == media_id))):
        raise AppError(409, "MEDIA_IN_USE", "This media is the featured image of a post")
    keys = [media.key, *media.variant_keys.values()]
    await session.delete(media)
    await session.commit()
    for key in keys:  # the row is gone; a leftover file is garbage, not an error
        try:
            await storage.delete(key)
        except Exception:
            log.warning("could not delete stored file %s", key, exc_info=True)
