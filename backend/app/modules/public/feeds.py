"""Read-side queries for public cards. A card is a published translation of a published post."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.storage import get_storage
from app.modules.media.models import Media
from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
from app.modules.public.schemas import (
    CategoryFeedOut,
    HomeCategoryBlock,
    HomeOut,
    PublicCard,
    PublicCategory,
    PublicImage,
)
from app.modules.seo.generator import truncate_words
from app.modules.taxonomy import service as taxonomy_service
from app.modules.taxonomy.models import Category
from app.modules.users.models import User

EXCERPT_LEN = 200
PUBLISHED_AT = func.coalesce(PostTranslation.published_at, Post.published_at)


def card_excerpt(excerpt: str | None, body_text: str) -> str:
    return excerpt or truncate_words(body_text, EXCERPT_LEN)


def image_alt(locale: str, media: Media, title: str) -> str:
    return (media.alt_ne if locale == "ne" else media.alt_en) or media.caption or title


def public_image(locale: str, media: Media | None, title: str) -> PublicImage | None:
    if media is None:
        return None
    return PublicImage(
        url=media.url, width=media.width, height=media.height,
        alt=image_alt(locale, media, title), variants=media.variants,
    )


def card_query(locale: str) -> Select:
    alt_col = Media.alt_ne if locale == "ne" else Media.alt_en
    return (
        select(
            Post.id,
            PostTranslation.title,
            PostTranslation.slug,
            PostTranslation.excerpt,
            # Twice the excerpt length is plenty to cut a word-boundary excerpt from.
            func.left(PostTranslation.body_text, 2 * EXCERPT_LEN).label("body_head"),
            Category.slug.label("category_slug"),
            User.name.label("author_name"),
            PUBLISHED_AT.label("published_at"),
            Media.key.label("media_key"),
            Media.width.label("media_width"),
            Media.height.label("media_height"),
            Media.variant_keys.label("media_variant_keys"),
            func.coalesce(func.nullif(alt_col, ""), func.nullif(Media.caption, ""), PostTranslation.title).label("media_alt"),
        )
        .select_from(PostTranslation)
        .join(Post, Post.id == PostTranslation.post_id)
        .join(Category, Category.id == Post.category_id)
        .join(User, User.id == Post.author_id)
        .outerjoin(Media, Media.id == Post.featured_media_id)
        .where(
            PostTranslation.locale == locale,
            PostTranslation.status == TranslationStatus.published,
            Post.status == PostStatus.published,
        )
    )


def to_card(row) -> PublicCard:
    return PublicCard(
        id=row.id,
        title=row.title,
        slug=row.slug,
        excerpt=card_excerpt(row.excerpt, row.body_head),
        category_slug=row.category_slug,
        author_name=row.author_name,
        published_at=row.published_at,
        image=None if row.media_key is None else PublicImage(
            url=get_storage().url(row.media_key), width=row.media_width, height=row.media_height,
            alt=row.media_alt, variants={n: get_storage().url(k) for n, k in row.media_variant_keys.items()},
        ),
    )


HOME_BREAKING_LIMIT = 10
HOME_CATEGORY_POSTS = 6
NEWEST_FIRST = (PUBLISHED_AT.desc(), Post.id.desc())


def _public_category(cat: Category, locale: str) -> PublicCategory:
    return PublicCategory(
        id=cat.id,
        slug=cat.slug,
        name=cat.name_ne if locale == "ne" else cat.name_en,
        seo_description=cat.seo_description,
    )


async def _cards(session: AsyncSession, stmt: Select) -> list[PublicCard]:
    return [to_card(row) for row in await session.execute(stmt)]


async def home_feed(session: AsyncSession, locale: str) -> HomeOut:
    breaking = await _cards(
        session,
        card_query(locale).where(Post.is_breaking.is_(True)).order_by(*NEWEST_FIRST).limit(HOME_BREAKING_LIMIT),
    )
    cats = await taxonomy_service.all_categories(session)  # ordered by sort, id
    blocks: list[HomeCategoryBlock] = []
    # One small query per top-level category: a newsroom has about ten, and the result is cached.
    for root in (c for c in cats.values() if c.parent_id is None):
        ids = taxonomy_service.descendant_ids(cats, root.id)
        posts = await _cards(
            session,
            card_query(locale).where(Post.category_id.in_(ids)).order_by(*NEWEST_FIRST).limit(HOME_CATEGORY_POSTS),
        )
        if posts:
            blocks.append(HomeCategoryBlock(category=_public_category(root, locale), posts=posts))
    return HomeOut(breaking=breaking, categories=blocks)


async def category_feed(
    session: AsyncSession, slug: str, locale: str, *, limit: int, offset: int
) -> CategoryFeedOut:
    cats = await taxonomy_service.all_categories(session)
    cat = next((c for c in cats.values() if c.slug == slug), None)
    if cat is None:
        raise AppError(404, "CATEGORY_NOT_FOUND", "Category not found")
    base = card_query(locale).where(Post.category_id.in_(taxonomy_service.descendant_ids(cats, cat.id)))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    items = await _cards(session, base.order_by(*NEWEST_FIRST).limit(limit).offset(offset))
    return CategoryFeedOut(
        category=_public_category(cat, locale), items=items, total=total or 0, limit=limit, offset=offset
    )
