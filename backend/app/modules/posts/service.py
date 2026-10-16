import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.auth.deps import ROLE_RANK
from app.modules.posts.models import Post, PostStatus, PostTranslation
from app.modules.posts.render import render_html
from app.modules.posts.schemas import PostCreate, PostUpdate
from app.modules.seo.generator import SeoInput, build_seo
from app.modules.seo.slug import make_slug
from app.modules.taxonomy.models import Category
from app.modules.users.models import Role, User


def _is_editor(user: User) -> bool:
    return ROLE_RANK[user.role] >= ROLE_RANK[Role.editor]


MAX_SLUG_LEN = 80
SLUG_RETRY_ATTEMPTS = 3
SLUG_CONSTRAINT = "uq_translation_locale_slug"


def _is_slug_conflict(exc: IntegrityError) -> bool:
    return SLUG_CONSTRAINT in str(exc.orig)


def _trim_base(base: str, max_len: int) -> str:
    if len(base) <= max_len:
        return base
    cut = base[:max_len]
    if "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return cut.rstrip("-") or base[:max_len]


async def _slug_taken(session: AsyncSession, locale: str, slug: str, exclude_id: int | None) -> bool:
    stmt = select(PostTranslation.id).where(PostTranslation.locale == locale, PostTranslation.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(PostTranslation.id != exclude_id)
    return (await session.scalar(stmt.limit(1))) is not None


async def unique_slug(session: AsyncSession, locale: str, base: str, exclude_id: int | None = None) -> str:
    """Return base, or base-N trimmed so the result never exceeds MAX_SLUG_LEN."""
    if not await _slug_taken(session, locale, base, exclude_id):
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = _trim_base(base, MAX_SLUG_LEN - len(suffix)) + suffix
        if not await _slug_taken(session, locale, candidate, exclude_id):
            return candidate
        n += 1


def _post_event(topic: str, post: Post) -> OutboxEvent:
    return OutboxEvent(
        topic=topic,
        payload={
            "post_id": str(post.id),
            "category_id": post.category_id,
            "slugs": {t.locale: t.slug for t in post.translations},
        },
    )


async def _refresh_all_seo(session: AsyncSession, post: Post) -> None:
    category = await session.get(Category, post.category_id)
    author = await session.get(User, post.author_id)
    site_url = get_settings().site_url
    for tr in post.translations:
        alternates = {t.locale: t.slug for t in post.translations if t.locale != tr.locale}
        meta = build_seo(
            SeoInput(
                locale=tr.locale,
                title=tr.title,
                html=tr.content_html,
                slug=tr.slug,
                category_slug=category.slug,
                category_name=category.name_ne if tr.locale == "ne" else category.name_en,
                author_name=author.name,
                published_at=post.published_at,
                modified_at=post.updated_at,
                seo_title=tr.seo_title,
                seo_description=tr.seo_description,
                alternate_slugs=alternates,
            ),
            site_url,
        )
        tr.seo_auto = meta.to_dict()


async def _save(session: AsyncSession, post: Post) -> Post:
    await session.flush()
    await _refresh_all_seo(session, post)
    await session.commit()
    return post


async def get_post(session: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await session.get(Post, post_id)
    if post is None:
        raise AppError(404, "POST_NOT_FOUND", "Post not found")
    return post


async def _get_post_for_update(session: AsyncSession, post_id: uuid.UUID) -> Post:
    stmt = select(Post).where(Post.id == post_id).with_for_update().execution_options(populate_existing=True)
    post = await session.scalar(stmt)
    if post is None:
        raise AppError(404, "POST_NOT_FOUND", "Post not found")
    return post


async def create_post(session: AsyncSession, author: User, data: PostCreate) -> Post:
    if await session.get(Category, data.category_id) is None:
        raise AppError(422, "CATEGORY_NOT_FOUND", "Category does not exist")
    base = make_slug(data.title)
    content_html = render_html(data.content_json)
    for _ in range(SLUG_RETRY_ATTEMPTS):
        # unique_slug checks committed rows; a concurrent create can still win the race
        # between our check and our INSERT. The SAVEPOINT lets us retry with a fresh check.
        slug = await unique_slug(session, data.locale, base)
        post = Post(author_id=author.id, category_id=data.category_id, status=PostStatus.draft)
        post.translations.append(
            PostTranslation(
                locale=data.locale,
                title=data.title,
                slug=slug,
                content_json=data.content_json,
                content_html=content_html,
            )
        )
        try:
            async with session.begin_nested():
                session.add(post)
                await session.flush()
        except IntegrityError as exc:
            if not _is_slug_conflict(exc):
                raise
            continue
        return await _save(session, post)
    raise AppError(409, "SLUG_TAKEN", "Could not allocate a unique slug; please retry")


def _check_version(post: Post, if_match: str | None) -> None:
    if if_match is None:
        raise AppError(428, "PRECONDITION_REQUIRED", "If-Match header with updated_at is required")
    try:
        sent = datetime.fromisoformat(if_match.strip('"'))
    except ValueError:
        sent = None
    if sent != post.updated_at:
        raise AppError(412, "VERSION_CONFLICT", "Post was changed by someone else",
                       {"current_updated_at": post.updated_at.isoformat()})


async def update_post(session: AsyncSession, user: User, post_id: uuid.UUID, if_match: str | None, data: PostUpdate) -> Post:
    post = await _get_post_for_update(session, post_id)
    own_draft = post.author_id == user.id and post.status == PostStatus.draft
    if not (_is_editor(user) or own_draft):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot edit this post")
    _check_version(post, if_match)

    tr = next((t for t in post.translations if t.locale == data.locale), None)
    if tr is None:
        if data.title is None or data.content_json is None:
            raise AppError(422, "TRANSLATION_INCOMPLETE", "A new translation needs title and content_json")
        tr = PostTranslation(
            locale=data.locale,
            title=data.title,
            slug=await unique_slug(session, data.locale, make_slug(data.title)),
            content_json=data.content_json,
            content_html=render_html(data.content_json),
        )
        post.translations.append(tr)
    else:
        if data.title is not None and data.title != tr.title:
            tr.title = data.title
            if post.status != PostStatus.published:
                tr.slug = await unique_slug(session, tr.locale, make_slug(data.title), exclude_id=tr.id)
        if data.content_json is not None:
            tr.content_json = data.content_json
            tr.content_html = render_html(data.content_json)
    if "seo_title" in data.model_fields_set:
        tr.seo_title = data.seo_title or None
    if "seo_description" in data.model_fields_set:
        tr.seo_description = data.seo_description or None

    post.updated_at = utcnow()
    if post.status == PostStatus.published:
        session.add(_post_event("post.updated", post))
    return await _save(session, post)


async def submit_post(session: AsyncSession, user: User, post_id: uuid.UUID) -> Post:
    post = await _get_post_for_update(session, post_id)
    if not (_is_editor(user) or post.author_id == user.id):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot submit this post")
    if post.status != PostStatus.draft:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot submit a post that is {post.status.value}")
    post.status = PostStatus.in_review
    post.updated_at = utcnow()
    return await _save(session, post)


async def publish_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post:
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status not in (PostStatus.draft, PostStatus.in_review):
        raise AppError(409, "INVALID_TRANSITION", f"Cannot publish a post that is {post.status.value}")
    now = utcnow()
    post.status = PostStatus.published
    post.published_at = post.published_at or now
    post.updated_at = now
    session.add(_post_event("post.published", post))
    return await _save(session, post)
