import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, TypeVar

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, TypeAdapter
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.ratelimit import client_ip, limit_search, limit_view
from app.db.session import get_session
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
from app.modules.public.service import (
    CACHE_CONTROL,
    CACHE_TTL_SECONDS,
    XML_CACHE_CONTROL,
    XML_CACHE_TTL_SECONDS,
    xml_cache_key,
    NEGATIVE_TTL_SECONDS,
    NOT_FOUND_MARKER,
    cache_get,
    cache_set,
    cached_model,
    parse_cached,
    categories_cache_key,
    category_feed_cache_key,
    feed_generation,
    home_cache_key,
    post_cache_key,
    redirect_cache_key,
)
from app.modules.public.feeds import category_feed, home_feed, public_image
from app.modules.public.schemas import CardPage, CategoryFeedOut, HomeOut, PublicCard, PublicImage
from app.modules.public import xmlfeeds
from app.modules.public import stats
from app.modules.public.search import search_posts
from app.modules.seo import service as seo_service
from app.modules.taxonomy import service as taxonomy_service
from app.modules.taxonomy.models import Category
from app.modules.taxonomy.schemas import CategoryNode
from app.modules.users.models import User

router = APIRouter(prefix="/api/public", tags=["public"])

logger = logging.getLogger(__name__)

SUPPORTED_LOCALES = ("ne", "en")
POST_SLUG_PATTERN = re.compile(r"[a-z0-9-]{1,100}")  # anything else cannot exist; never cache its 404
MAX_OFFSET = 1000  # deep pages are expensive and nobody reads them
_category_tree = TypeAdapter(list[CategoryNode])  # dumping only; reads go through cached_model


def _require_locale(locale: str) -> None:
    # Public routes treat an unknown locale as a page that does not exist (M2a1 ruling).
    if locale not in SUPPORTED_LOCALES:
        raise AppError(404, "LOCALE_NOT_FOUND", "Unknown locale")


M = TypeVar("M", bound=BaseModel)


async def _cached_feed(
    response: Response,
    redis: Redis,
    make_key: Callable[[str], str],
    model: type[M],
    build: Callable[[], Awaitable[M]],
) -> M:
    """Serve a feed from Redis under the current feed generation, or build and store it."""
    response.headers["Cache-Control"] = CACHE_CONTROL
    gen = await feed_generation(redis)
    key = make_key(gen) if gen is not None else None
    cached = await cached_model(redis, key, model) if key else None
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached
    out = await build()
    if key:
        await cache_set(redis, key, out.model_dump_json())
    response.headers["X-Cache"] = "MISS"
    return out


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
    image: PublicImage | None = None


class RedirectOut(BaseModel):
    to_path: str
    code: int


def _post_not_found() -> AppError:
    return AppError(404, "POST_NOT_FOUND", "Post not found")


@router.get("/posts/{locale}/{slug}", response_model=PublicPostOut)
async def get_public_post(
    locale: str,
    slug: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> PublicPostOut:
    # An unknown locale is just a page that does not exist: same 404 as a missing slug.
    if locale not in SUPPORTED_LOCALES or POST_SLUG_PATTERN.fullmatch(slug) is None:
        raise _post_not_found()
    response.headers["Cache-Control"] = CACHE_CONTROL
    key = post_cache_key(locale, slug)
    cached = await cache_get(redis, key)
    if cached == NOT_FOUND_MARKER:
        raise _post_not_found()
    hit = parse_cached(cached, PublicPostOut, key) if cached else None
    if hit is not None:
        response.headers["X-Cache"] = "HIT"
        return hit

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
        await cache_set(redis, key, NOT_FOUND_MARKER, ttl=NEGATIVE_TTL_SECONDS)
        raise _post_not_found()
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
        image=public_image(locale, post.featured_media, tr.title),
    )
    await cache_set(redis, key, out.model_dump_json())
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
    cached = await cached_model(redis, key, list[CategoryNode]) if key else None
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached
    tree = await taxonomy_service.category_tree(session)
    if key:
        await cache_set(redis, key, _category_tree.dump_json(tree).decode())
    response.headers["X-Cache"] = "MISS"
    return tree


@router.get("/search", response_model=CardPage)
async def public_search(
    response: Response,
    q: str = Query(max_length=200),
    locale: str = Query(),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=MAX_OFFSET),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(limit_search),
) -> CardPage:
    _require_locale(locale)
    q = q.strip()
    if len(q) < 2:
        raise AppError(422, "QUERY_TOO_SHORT", "Search needs at least 2 characters")
    response.headers["Cache-Control"] = CACHE_CONTROL
    items, total = await search_posts(session, locale, q, limit=limit, offset=offset)
    return CardPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/home", response_model=HomeOut)
async def public_home(
    response: Response,
    locale: str = Query(),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> HomeOut:
    _require_locale(locale)
    return await _cached_feed(
        response, redis, lambda gen: home_cache_key(gen, locale), HomeOut, lambda: home_feed(session, locale)
    )


@router.get("/category/{slug}", response_model=CategoryFeedOut)
async def public_category(
    slug: str,
    response: Response,
    locale: str = Query(),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=MAX_OFFSET),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> CategoryFeedOut:
    _require_locale(locale)
    return await _cached_feed(
        response,
        redis,
        lambda gen: category_feed_cache_key(gen, slug, locale, limit, offset),
        CategoryFeedOut,
        lambda: category_feed(session, slug, locale, limit=limit, offset=offset),
    )


def _redirect_not_found() -> AppError:
    return AppError(404, "REDIRECT_NOT_FOUND", "No redirect for this path")


@router.get("/redirects/resolve", response_model=RedirectOut)
async def resolve_redirect(
    response: Response,
    path: str = Query(),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> RedirectOut:
    """Used by the Next.js middleware before it renders a 404."""
    if not path.startswith("/") or len(path) > seo_service.MAX_PATH_LENGTH:
        raise AppError(422, "INVALID_PATH", f"path must start with '/' and be at most {seo_service.MAX_PATH_LENGTH} characters")
    response.headers["Cache-Control"] = CACHE_CONTROL
    normalized = seo_service.normalize_article_path(path)
    if normalized is None:  # cannot be an article path: no lookup, and nothing worth caching
        raise _redirect_not_found()
    path = normalized
    key = redirect_cache_key(path)
    cached = await cache_get(redis, key)
    if cached == NOT_FOUND_MARKER:
        raise _redirect_not_found()
    hit = parse_cached(cached, RedirectOut, key) if cached else None
    if hit is not None:
        response.headers["X-Cache"] = "HIT"
        return hit
    row = await seo_service.resolve_redirect(session, path)
    if row is None:
        await cache_set(redis, key, NOT_FOUND_MARKER, ttl=CACHE_TTL_SECONDS)
        raise _redirect_not_found()
    out = RedirectOut(to_path=row.to_path, code=row.code)
    await cache_set(redis, key, out.model_dump_json())
    response.headers["X-Cache"] = "MISS"
    return out


async def _cached_xml(
    redis: Redis, name: str, media_type: str, build: Callable[[], Awaitable[str]]
) -> Response:
    """Serve an XML document from Redis under the current feed generation, or build and store it."""
    headers = {"Cache-Control": XML_CACHE_CONTROL}
    gen = await feed_generation(redis)
    key = xml_cache_key(gen, name) if gen is not None else None
    cached = await cache_get(redis, key) if key else None
    if cached is not None:
        return Response(cached, media_type=media_type, headers={**headers, "X-Cache": "HIT"})
    body = await build()
    if key:
        await cache_set(redis, key, body, ttl=XML_CACHE_TTL_SECONDS)
    return Response(body, media_type=media_type, headers={**headers, "X-Cache": "MISS"})


def _site() -> str:
    return get_settings().site_url.rstrip("/")


@router.get("/sitemap.xml")
async def sitemap_index(
    session: AsyncSession = Depends(get_session), redis: Redis = Depends(get_redis)
) -> Response:
    return await _cached_xml(redis, "index", "application/xml", lambda: xmlfeeds.sitemap_index(session, _site()))


@router.get("/sitemaps/categories.xml")
async def categories_sitemap(
    session: AsyncSession = Depends(get_session), redis: Redis = Depends(get_redis)
) -> Response:
    return await _cached_xml(
        redis, "categories", "application/xml", lambda: xmlfeeds.categories_sitemap(session, _site())
    )


@router.get("/sitemaps/posts-{month}.xml")
async def posts_sitemap(
    month: str, session: AsyncSession = Depends(get_session), redis: Redis = Depends(get_redis)
) -> Response:
    window = xmlfeeds.parse_month(month)  # only real YYYY-MM values may become cache keys
    if window is None:
        raise AppError(404, "SITEMAP_NOT_FOUND", "No such sitemap")
    return await _cached_xml(
        redis, f"posts:{month}", "application/xml", lambda: xmlfeeds.month_sitemap(session, _site(), *window)
    )


@router.get("/news-sitemap.xml")
async def news_sitemap(
    session: AsyncSession = Depends(get_session), redis: Redis = Depends(get_redis)
) -> Response:
    return await _cached_xml(redis, "news", "application/xml", lambda: xmlfeeds.news_sitemap(session, _site()))


@router.get("/rss.xml")
async def rss(
    locale: str = Query(),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Response:
    _require_locale(locale)
    return await _cached_xml(
        redis, f"rss:{locale}", "application/rss+xml", lambda: xmlfeeds.rss_feed(session, _site(), locale, None)
    )


@router.get("/category/{slug}/rss.xml")
async def category_rss(
    slug: str,
    locale: str = Query(),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Response:
    _require_locale(locale)
    return await _cached_xml(
        redis,
        f"rss:{locale}:{slug}",
        "application/rss+xml",
        lambda: xmlfeeds.rss_feed(session, _site(), locale, slug),
    )


class ViewIn(BaseModel):
    post_id: uuid.UUID
    locale: Literal["ne", "en"]


@router.post("/stats/view", status_code=204)
async def count_view(
    body: ViewIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _: None = Depends(limit_view),
) -> Response:
    """Always 204, so the endpoint never reveals whether a post exists or whether the view counted."""
    if await stats.is_countable(session, body.post_id, body.locale):
        try:
            await stats.record_view(redis, body.post_id, body.locale, client_ip(request))
        except RedisError:
            logger.warning("View not counted; Redis unavailable", exc_info=True)
    return Response(status_code=204)


_cards = TypeAdapter(list[PublicCard])
TRENDING_PADDED_TTL = 15
TRENDING_PADDED_CONTROL = "public, s-maxage=15"


@router.get("/trending", response_model=list[PublicCard])
async def public_trending(
    response: Response,
    locale: str = Query(),
    limit: int = Query(default=10, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> list[PublicCard]:
    _require_locale(locale)
    gen = await feed_generation(redis)  # None: Redis unavailable, so no cache read or write
    for padded in (False, True):
        if gen is None:
            break
        cached = await cached_model(redis, stats.trending_cache_key(gen, locale, limit, padded), list[PublicCard])
        if cached is not None:
            response.headers["X-Cache"] = "HIT"
            response.headers["Cache-Control"] = TRENDING_PADDED_CONTROL if padded else CACHE_CONTROL
            return cached
    try:
        out = await stats.top_by_redis(session, redis, locale, limit)
    except RedisError:
        logger.warning("Trending unavailable from Redis; falling back to view_count", exc_info=True)
        response.headers["X-Cache"] = "BYPASS"
        response.headers["Cache-Control"] = TRENDING_PADDED_CONTROL
        return await stats.top_by_view_count(session, locale, limit)
    padded = len(out) < limit  # a quiet day: top up from the most-viewed recent posts, Redis ranking first
    if padded:
        out += await stats.top_by_view_count(session, locale, limit - len(out), exclude={c.id for c in out})
    response.headers["Cache-Control"] = TRENDING_PADDED_CONTROL if padded else CACHE_CONTROL
    if gen is not None:
        await cache_set(
            redis, stats.trending_cache_key(gen, locale, limit, padded), _cards.dump_json(out).decode(),
            ttl=TRENDING_PADDED_TTL if padded else CACHE_TTL_SECONDS,
        )
    response.headers["X-Cache"] = "MISS"
    return out
