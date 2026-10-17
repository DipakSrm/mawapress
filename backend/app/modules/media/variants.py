"""arq job: derive the WebP size ladder and the OG crop for an uploaded image."""

import asyncio
import logging
import uuid

from app.modules.media.models import Media
from app.modules.media.processing import render_variants

log = logging.getLogger("mawa.worker.media")


def variant_key(original_key: str, name: str) -> str:
    return f"{original_key.rsplit('.', 1)[0]}-{name}.webp"


async def make_variants(ctx: dict, media_id: str) -> None:
    """ctx carries `session_factory` and `storage`. Safe to re-run; a media row deleted meanwhile is skipped."""
    storage = ctx["storage"]
    async with ctx["session_factory"]() as session:
        media = await session.get(Media, uuid.UUID(media_id))
        if media is None:
            log.info("media %s no longer exists; skipping variants", media_id)
            return
        original = await storage.get(media.key)
        rendered = await asyncio.to_thread(render_variants, original)
        urls: dict[str, str] = {}
        for name, data in rendered.items():
            key = variant_key(media.key, name)
            await storage.put(key, data, "image/webp")
            urls[name] = storage.url(key)
        media.variants = urls
        await session.commit()
