"""Read-side queries for public cards. A card is a published translation of a published post."""

from sqlalchemy import Select, func, select

from app.modules.posts.models import Post, PostStatus, PostTranslation, TranslationStatus
from app.modules.public.schemas import PublicCard
from app.modules.seo.generator import truncate_words
from app.modules.taxonomy.models import Category
from app.modules.users.models import User

EXCERPT_LEN = 200
PUBLISHED_AT = func.coalesce(PostTranslation.published_at, Post.published_at)


def card_excerpt(excerpt: str | None, body_text: str) -> str:
    return excerpt or truncate_words(body_text, EXCERPT_LEN)


def card_query(locale: str) -> Select:
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
        )
        .select_from(PostTranslation)
        .join(Post, Post.id == PostTranslation.post_id)
        .join(Category, Category.id == Post.category_id)
        .join(User, User.id == Post.author_id)
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
    )
