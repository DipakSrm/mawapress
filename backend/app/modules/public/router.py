import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.errors import AppError
from app.db.session import get_session
from app.modules.posts.models import Post, PostStatus, PostTranslation
from app.modules.taxonomy.models import Category
from app.modules.users.models import User

router = APIRouter(prefix="/api/public", tags=["public"])
CACHE_TTL_SECONDS = 60
CACHE_CONTROL = "public, s-maxage=60, stale-while-revalidate=86400"


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


def post_cache_key(locale: str, slug: str) -> str:
    return f"public:post:{locale}:{slug}"


async def invalidate_post_cache(redis: Redis, post: Post) -> None:
    keys = [post_cache_key(t.locale, t.slug) for t in post.translations]
    if keys:
        await redis.delete(*keys)


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
    if cached := await redis.get(key):
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
    await redis.set(key, out.model_dump_json(), ex=CACHE_TTL_SECONDS)
    response.headers["X-Cache"] = "MISS"
    return out
