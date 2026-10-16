import logging
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.errors import AppError
from app.db.session import get_session
from app.modules.posts.models import Post, PostStatus, PostTranslation
from app.modules.public.service import CACHE_CONTROL, CACHE_TTL_SECONDS, post_cache_key
from app.modules.taxonomy.models import Category
from app.modules.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public", tags=["public"])


class PublicPostOut(BaseModel):
    id: uuid.UUID
    locale: str
    title: str
    slug: str
    content_html: str
    category_slug: str
    author_name: str
    published_at: datetime | None
    updated_at: datetime
    seo: dict
    alternates: dict[str, str]


@router.get("/posts/{locale}/{slug}", response_model=PublicPostOut)
async def get_public_post(
    locale: Literal["ne", "en"],
    slug: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> PublicPostOut:
    response.headers["Cache-Control"] = CACHE_CONTROL
    key = post_cache_key(locale, slug)
    cached = None
    try:
        cached = await redis.get(key)
    except RedisError:
        logger.warning("Cache read failed; serving from database", exc_info=True)
    if cached:
        response.headers["X-Cache"] = "HIT"
        return PublicPostOut.model_validate_json(cached)

    row = (await session.execute(
        select(PostTranslation, Post)
        .join(Post, PostTranslation.post_id == Post.id)
        .where(PostTranslation.locale == locale, PostTranslation.slug == slug, Post.status == PostStatus.published)
    )).first()
    if row is None:
        raise AppError(404, "POST_NOT_FOUND", "Post not found")
    tr, post = row
    category = await session.get(Category, post.category_id)
    author = await session.get(User, post.author_id)

    out = PublicPostOut(
        id=post.id,
        locale=tr.locale,
        title=tr.title,
        slug=tr.slug,
        content_html=tr.content_html,
        category_slug=category.slug,
        author_name=author.name,
        published_at=post.published_at,
        updated_at=post.updated_at,
        seo=tr.seo_auto,
        alternates={t.locale: t.slug for t in post.translations if t.locale != tr.locale},
    )
    try:
        await redis.set(key, out.model_dump_json(), ex=CACHE_TTL_SECONDS)
    except RedisError:
        logger.warning("Cache write failed; response not cached", exc_info=True)
    response.headers["X-Cache"] = "MISS"
    return out
