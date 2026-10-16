import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, TypeAdapter
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.errors import AppError
from app.db.session import get_session
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
from app.modules.public.service import (
    CACHE_CONTROL,
    CACHE_TTL_SECONDS,
    cache_get,
    cache_set,
    categories_cache_key,
    feed_generation,
    post_cache_key,
)
from app.modules.taxonomy import service as taxonomy_service
from app.modules.taxonomy.models import Category
from app.modules.taxonomy.schemas import CategoryNode
from app.modules.users.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public", tags=["public"])

SUPPORTED_LOCALES = ("ne", "en")
_category_tree = TypeAdapter(list[CategoryNode])


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
    locale: str,
    slug: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> PublicPostOut:
    # An unknown locale is just a page that does not exist: same 404 as a missing slug.
    if locale not in SUPPORTED_LOCALES:
        raise AppError(404, "POST_NOT_FOUND", "Post not found")
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
        .where(
            PostTranslation.locale == locale,
            PostTranslation.slug == slug,
            PostTranslation.status == TranslationStatus.published,
            Post.status == PostStatus.published,
        )
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
        published_at=tr.published_at or post.published_at,
        updated_at=tr.updated_at,
        seo=tr.seo_auto,
        alternates={
            t.locale: t.slug
            for t in post.translations
            if t.locale != tr.locale and t.status == TranslationStatus.published
        },
    )
    try:
        await redis.set(key, out.model_dump_json(), ex=CACHE_TTL_SECONDS)
    except RedisError:
        logger.warning("Cache write failed; response not cached", exc_info=True)
    response.headers["X-Cache"] = "MISS"
    return out


@router.get("/categories", response_model=list[CategoryNode])
async def public_categories(
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> list[CategoryNode]:
    response.headers["Cache-Control"] = CACHE_CONTROL
    gen = await feed_generation(redis)
    key = categories_cache_key(gen) if gen is not None else None
    cached = await cache_get(redis, key) if key else None
    if cached:
        response.headers["X-Cache"] = "HIT"
        return _category_tree.validate_json(cached)
    tree = await taxonomy_service.category_tree(session)
    if key:
        await cache_set(redis, key, _category_tree.dump_json(tree).decode())
    response.headers["X-Cache"] = "MISS"
    return tree
