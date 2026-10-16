import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.auth.deps import ROLE_RANK
from app.modules.posts.models import Post, PostRevision, PostStatus, PostTranslation, TranslationStatus
from app.modules.posts.render import render_html
from app.modules.posts.schemas import PostCreate, PostUpdate
from app.modules.seo.generator import SeoInput, build_seo, plain_text
from app.modules.seo.slug import make_slug
from app.modules.taxonomy import service as taxonomy_service
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
        alternates = {
            t.locale: t.slug
            for t in post.translations
            if t.locale != tr.locale and t.status == TranslationStatus.published
        }
        meta = build_seo(
            SeoInput(
                locale=tr.locale,
                title=tr.title,
                html=tr.content_html,
                slug=tr.slug,
                category_slug=category.slug,
                category_name=category.name_ne if tr.locale == "ne" else category.name_en,
                author_name=author.name,
                published_at=tr.published_at or post.published_at,
                modified_at=tr.updated_at,
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


async def _flush_with_slug_retry(
    session: AsyncSession,
    assign: Callable[[], Awaitable[None]],
    *,
    refresh_on_conflict: Sequence[object] = (),
) -> None:
    """Run assign() (which picks a slug and stages the row) and flush it inside a SAVEPOINT.

    unique_slug checks committed rows; a concurrent request can still win the race between
    our check and our INSERT/UPDATE. The SAVEPOINT lets us retry with a fresh check. A savepoint
    rollback expires the objects it touched, so persistent ones listed in refresh_on_conflict are
    reloaded before the next attempt.
    """
    for _ in range(SLUG_RETRY_ATTEMPTS):
        try:
            async with session.begin_nested():
                await assign()
                await session.flush()
        except IntegrityError as exc:
            if not _is_slug_conflict(exc):
                raise
            for obj in refresh_on_conflict:
                await session.refresh(obj)
            continue
        return
    raise AppError(409, "SLUG_TAKEN", "Could not allocate a unique slug; please retry")


async def create_post(session: AsyncSession, author: User, data: PostCreate) -> Post:
    if await session.get(Category, data.category_id) is None:
        raise AppError(422, "CATEGORY_NOT_FOUND", "Category does not exist")
    tags = await taxonomy_service.get_tags(session, data.tag_ids)
    base = make_slug(data.title)
    content_html = render_html(data.content_json)
    body_text = plain_text(content_html)
    post: Post

    async def assign() -> None:
        nonlocal post
        post = Post(author_id=author.id, category_id=data.category_id, status=PostStatus.draft, tags=list(tags))
        post.translations.append(
            PostTranslation(
                locale=data.locale,
                title=data.title,
                slug=await unique_slug(session, data.locale, base),
                content_json=data.content_json,
                content_html=content_html,
                body_text=body_text,
            )
        )
        session.add(post)

    await _flush_with_slug_retry(session, assign)
    return await _save(session, post)


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


def _set_content(tr: PostTranslation, content_json: dict) -> None:
    tr.content_json = content_json
    tr.content_html = render_html(content_json)
    tr.body_text = plain_text(tr.content_html)


REVISION_FIELDS = ("title", "slug", "content_json", "seo_title", "seo_description", "excerpt")


def _snapshot(tr: PostTranslation) -> dict:
    return {field: getattr(tr, field) for field in REVISION_FIELDS}


class UpdateResult(NamedTuple):
    post: Post
    public_changed: bool  # True when readers can see the change (live translation edited, or breaking flag on a live post)


async def update_post(
    session: AsyncSession, user: User, post_id: uuid.UUID, if_match: str | None, data: PostUpdate
) -> UpdateResult:
    post = await _get_post_for_update(session, post_id)
    own_draft = post.author_id == user.id and post.status == PostStatus.draft
    if not (_is_editor(user) or own_draft):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot edit this post")
    if data.is_breaking is not None and not _is_editor(user):
        raise AppError(403, "FORBIDDEN_ROLE", "Only editors can mark breaking news")
    _check_version(post, if_match)
    # Validate before changing anything, so a 422 leaves the post untouched.
    tags = await taxonomy_service.get_tags(session, data.tag_ids) if data.tag_ids is not None else None

    now = utcnow()
    tr = next((t for t in post.translations if t.locale == data.locale), None)
    public_changed = False
    # Readers have seen a published translation, so keep its current state before changing it.
    before = _snapshot(tr) if tr is not None and tr.status == TranslationStatus.published else None
    if tr is None:
        if data.title is None or data.content_json is None:
            raise AppError(422, "TRANSLATION_INCOMPLETE", "A new translation needs title and content_json")
        title, content_json = data.title, data.content_json
        content_html = render_html(content_json)
        new_tr: PostTranslation

        async def assign_new() -> None:
            nonlocal new_tr
            # Attached by post_id (not through post.translations) so a rolled-back attempt
            # leaves the post's collection untouched.
            new_tr = PostTranslation(
                post_id=post.id,
                locale=data.locale,
                title=title,
                slug=await unique_slug(session, data.locale, make_slug(title)),
                content_json=content_json,
                content_html=content_html,
                body_text=plain_text(content_html),
            )
            session.add(new_tr)

        post.updated_at = now
        await _flush_with_slug_retry(session, assign_new)
        tr = new_tr
        post.translations.append(tr)
    else:
        # Only an already-published translation of a live post is visible to readers.
        public_changed = post.status == PostStatus.published and tr.status == TranslationStatus.published
        changed = False
        retitle_draft = False
        if data.title is not None and data.title != tr.title:
            tr.title = data.title
            changed = True
            retitle_draft = tr.status != TranslationStatus.published
        if data.content_json is not None and data.content_json != tr.content_json:
            _set_content(tr, data.content_json)
            changed = True
        if changed:
            tr.updated_at = now
        post.updated_at = now
        await session.flush()
        if retitle_draft:
            tr_id, locale, title = tr.id, tr.locale, tr.title

            async def assign_retitle() -> None:
                tr.slug = await unique_slug(session, locale, make_slug(title), exclude_id=tr_id)

            await _flush_with_slug_retry(session, assign_retitle, refresh_on_conflict=[tr])

    meta_changed = False
    if "seo_title" in data.model_fields_set and (data.seo_title or None) != tr.seo_title:
        tr.seo_title = data.seo_title or None
        meta_changed = True
    if "seo_description" in data.model_fields_set and (data.seo_description or None) != tr.seo_description:
        tr.seo_description = data.seo_description or None
        meta_changed = True
    if "excerpt" in data.model_fields_set:
        excerpt = (data.excerpt or "").strip() or None
        if excerpt != tr.excerpt:
            tr.excerpt = excerpt
            meta_changed = True
    if meta_changed:
        tr.updated_at = now

    if data.is_breaking is not None and data.is_breaking != post.is_breaking:
        post.is_breaking = data.is_breaking
        if post.status == PostStatus.published:
            public_changed = True  # the home page's breaking strip changes
    if tags is not None:
        post.tags = tags
    post.updated_at = now

    if before is not None and _snapshot(tr) != before:
        session.add(PostRevision(post_id=post.id, locale=tr.locale, editor_id=user.id, **before))
    if public_changed:
        session.add(_post_event("post.updated", post))
    return UpdateResult(await _save(session, post), public_changed)


async def list_revisions(
    session: AsyncSession, user: User, post_id: uuid.UUID, locale: str | None = None
) -> list[PostRevision]:
    post = await get_post(session, post_id)
    if post.author_id != user.id and not _is_editor(user):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot view this post's revisions")
    stmt = select(PostRevision).where(PostRevision.post_id == post_id)
    if locale is not None:
        stmt = stmt.where(PostRevision.locale == locale)
    stmt = stmt.order_by(PostRevision.created_at.desc(), PostRevision.id.desc())
    return list((await session.scalars(stmt)).all())


async def restore_revision(
    session: AsyncSession, user: User, post_id: uuid.UUID, rev_id: int, if_match: str | None
) -> UpdateResult:
    """Write a revision's content back as an ordinary versioned save.

    update_post records the state being replaced as a new revision and emits post.updated if the
    translation is live. The slug is not restored: it changes only through the explicit slug field,
    which also writes redirects.
    """
    rev = await session.get(PostRevision, rev_id)
    if rev is None or rev.post_id != post_id:
        raise AppError(404, "REVISION_NOT_FOUND", "Revision not found")
    data = PostUpdate(
        locale=rev.locale,
        title=rev.title,
        content_json=rev.content_json,
        seo_title=rev.seo_title or "",
        seo_description=rev.seo_description or "",
        excerpt=rev.excerpt or "",
    )
    return await update_post(session, user, post_id, if_match, data)


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
    """Publish a draft or in-review post (editor+; the router enforces the role).

    Editors own publishing, so a draft does not need to be submitted first (decided in M2a part 2).
    Publishing publishes the translations that exist at this moment and bumps their updated_at,
    so dateModified is never earlier than datePublished.
    """
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status not in (PostStatus.draft, PostStatus.in_review):
        raise AppError(409, "INVALID_TRANSITION", f"Cannot publish a post that is {post.status.value}")
    now = utcnow()
    post.status = PostStatus.published
    post.published_at = post.published_at or now
    post.updated_at = now
    for tr in post.translations:  # only the translations that exist right now
        if tr.status != TranslationStatus.published:
            tr.status = TranslationStatus.published
            tr.published_at = now
            tr.updated_at = now
    session.add(_post_event("post.published", post))
    return await _save(session, post)


async def publish_translation(session: AsyncSession, post_id: uuid.UUID, locale: str, if_match: str | None) -> Post:
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status != PostStatus.published:
        raise AppError(409, "INVALID_TRANSITION", "Publish the post before publishing a single translation")
    tr = next((t for t in post.translations if t.locale == locale), None)
    if tr is None:
        raise AppError(404, "TRANSLATION_NOT_FOUND", f"Post has no '{locale}' translation")
    if tr.status == TranslationStatus.published:
        raise AppError(409, "INVALID_TRANSITION", f"The '{locale}' translation is already published")
    now = utcnow()
    tr.status = TranslationStatus.published
    tr.published_at = now
    tr.updated_at = now
    post.updated_at = now
    session.add(_post_event("post.updated", post))
    return await _save(session, post)


async def send_back_post(session: AsyncSession, editor: User, post_id: uuid.UUID, note: str | None) -> Post:
    """in_review → draft, so the reporter can edit again. The note travels in the outbox payload."""
    post = await _get_post_for_update(session, post_id)
    if post.status != PostStatus.in_review:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot send back a post that is {post.status.value}")
    post.status = PostStatus.draft
    post.updated_at = utcnow()
    session.add(OutboxEvent(
        topic="post.sent_back",
        payload={
            "post_id": str(post.id),
            "author_id": str(post.author_id),
            "editor_id": str(editor.id),
            "note": (note or "").strip() or None,
        },
    ))
    return await _save(session, post)


async def unpublish_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post:
    """published → archived. Translations keep their status (unarchive is M2b)."""
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status != PostStatus.published:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot unpublish a post that is {post.status.value}")
    post.status = PostStatus.archived
    post.updated_at = utcnow()
    session.add(_post_event("post.unpublished", post))
    return await _save(session, post)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_posts(
    session: AsyncSession,
    user: User,
    *,
    status: PostStatus | None = None,
    author_id: uuid.UUID | None = None,
    category_id: int | None = None,
    locale: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[tuple[Post, str]], int]:
    conditions = []
    if not _is_editor(user):
        conditions.append(Post.author_id == user.id)  # reporters only ever see their own posts
    if author_id is not None:
        conditions.append(Post.author_id == author_id)
    if status is not None:
        conditions.append(Post.status == status)
    if category_id is not None:
        conditions.append(Post.category_id == category_id)

    translation_conditions = []
    if locale is not None:
        translation_conditions.append(PostTranslation.locale == locale)
    q = q.strip() if q else None
    if q:
        translation_conditions.append(PostTranslation.title.ilike(f"%{_escape_like(q)}%", escape="\\"))
    if translation_conditions:
        conditions.append(exists().where(PostTranslation.post_id == Post.id, *translation_conditions))

    total = await session.scalar(select(func.count()).select_from(Post).where(*conditions))
    rows = await session.execute(
        select(Post, User.name)
        .join(User, User.id == Post.author_id)
        .where(*conditions)
        .order_by(Post.updated_at.desc(), Post.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [(post, author_name) for post, author_name in rows.all()], total or 0
