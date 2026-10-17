"""arq job: derive the WebP size ladder and the OG crop for an uploaded image."""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.modules.media.models import Media
from app.modules.media.processing import render_variants
from app.modules.posts import service as posts_service
from app.modules.public.service import invalidate_public

log = logging.getLogger("mawa.worker.media")


def variant_key(original_key: str, name: str) -> str:
    return f"{original_key.rsplit('.', 1)[0]}-{name}.webp"


async def make_variants(ctx: dict, media_id: str) -> None:
    """ctx carries `session_factory`, `storage` and (optionally) `redis`.

    No database transaction is open while Pillow or storage work runs. Safe to re-run; a media row
    deleted meanwhile is skipped (and its freshly written variant files are removed).
    """
    storage, factory = ctx["storage"], ctx["session_factory"]
    mid = uuid.UUID(media_id)
    async with factory() as session:
        original_key = await session.scalar(select(Media.key).where(Media.id == mid))
    if original_key is None:
        log.info("media %s no longer exists; skipping variants", media_id)
        return

    rendered = await asyncio.to_thread(render_variants, await storage.get(original_key))
    keys: dict[str, str] = {}
    for name, data in rendered.items():
        keys[name] = variant_key(original_key, name)
        await storage.put(keys[name], data, "image/webp")

    async with factory() as session:
        media = await session.scalar(
            select(Media).where(Media.id == mid).with_for_update().execution_options(populate_existing=True)
        )
        if media is None:
            live = None
        else:
            media.variant_keys = keys
            # og_image in seo_auto now points at the og variant; live pages and feeds must follow.
            live = await posts_service.touch_posts_for_media(session, mid, refresh_seo=True)
            await session.commit()
    if live is None:
        log.info("media %s was deleted while its variants were built; removing them", media_id)
        for key in keys.values():
            try:
                await storage.delete(key)
            except Exception:
                log.warning("could not delete orphaned variant %s", key, exc_info=True)
        return
    redis = ctx.get("redis")
    if redis is not None:
        for post in live:
            await invalidate_public(redis, post)
