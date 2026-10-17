import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.outbox import OutboxEvent
from app.modules.auth.deps import ROLE_RANK
from app.modules.media.models import Media
from app.modules.posts.models import Post, PostRevision, PostStatus, PostTranslation, TranslationStatus
from app.modules.posts.render import render_html
from app.modules.posts.schemas import PostCreate, PostUpdate
from app.modules.seo.generator import SeoInput, build_seo, plain_text
from app.modules.seo import service as seo_service
from app.modules.seo.service import SlugChange
from app.modules.seo.slug import is_valid_slug, make_slug
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


def _og_image_url(media: Media | None, site_url: str) -> str | None:
    if media is None:
        return None
    url = media.variants.get("og") or media.url
    return f"{site_url}{url}" if url.startswith("/") else url  # social crawlers need an absolute URL


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
                image_url=_og_image_url(post.featured_media, site_url),
                seo_title=tr.seo_title,
                seo_description=tr.seo_description,
                alternate_slugs=alternates,
            ),
            site_url,
        )
        tr.seo_auto = meta.to_dict()


async def touch_posts_for_media(session: AsyncSession, media_id: uuid.UUID, *, refresh_seo: bool) -> list[Post]:
    """A featured media's public data changed: refresh seo_auto (when it feeds in) and queue `post.updated`
    for the live posts using it. Returns those live posts so the caller can invalidate caches after commit.
    Does not bump updated_at, so editors' If-Match versions stay valid."""
    posts = (await session.scalars(select(Post).where(Post.featured_media_id == media_id))).all()
    live: list[Post] = []
    for post in posts:
        if refresh_seo:
            await _refresh_all_seo(session, post)
        if post.status == PostStatus.published:
            session.add(_post_event("post.updated", post))
            live.append(post)
    return live


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


async def _get_featured_media(session: AsyncSession, media_id: uuid.UUID | None) -> Media | None:
    if media_id is None:
        return None
    # FOR SHARE: a concurrent media DELETE (FOR UPDATE) must wait for this transaction, then see the post.
    media = await session.scalar(
        select(Media).where(Media.id == media_id).with_for_update(read=True).execution_options(populate_existing=True)
    )
    if media is None:
        raise AppError(422, "MEDIA_NOT_FOUND", "Featured image does not exist")
    return media


async def create_post(session: AsyncSession, author: User, data: PostCreate) -> Post:
    if await session.get(Category, data.category_id) is None:
        raise AppError(422, "CATEGORY_NOT_FOUND", "Category does not exist")
    featured = await _get_featured_media(session, data.featured_media_id)
    tags = await taxonomy_service.get_tags(session, data.tag_ids)
    base = make_slug(data.title)
    content_html = render_html(data.content_json)
    body_text = plain_text(content_html)
    post: Post

    async def assign() -> None:
        nonlocal post
        post = Post(
            author_id=author.id, category_id=data.category_id, status=PostStatus.draft, tags=list(tags),
            featured_media=featured,
        )
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
    public_changed: bool  # True when readers can see the change (live translation edited, or breaking flag / featured image on a live post)
    slug_changes: Sequence[SlugChange] = ()  # one per translation whose public path moved and got a redirect


def _requested_slug(user: User, tr: PostTranslation | None, slug: str) -> str | None:
    """Validate an explicit slug change before anything is modified. None means 'no change'."""
    if tr is not None and slug == tr.slug:
        return None
    if not _is_editor(user):
        raise AppError(403, "FORBIDDEN_ROLE", "Only editors can change a slug")
    if tr is None or tr.status != TranslationStatus.published:
        raise AppError(422, "SLUG_NOT_EDITABLE", "Only a published translation's slug can be changed; a draft's slug follows its title")
    if not is_valid_slug(slug):
        raise AppError(422, "INVALID_SLUG", "Slug must be lower-case letters, digits and single hyphens, at most 80 chars")
    return slug


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
    new_category: Category | None = None
    if data.category_id is not None and data.category_id != post.category_id:
        new_category = await session.get(Category, data.category_id)
        if new_category is None:
            raise AppError(422, "CATEGORY_NOT_FOUND", "Category does not exist")
    tags = await taxonomy_service.get_tags(session, data.tag_ids) if data.tag_ids is not None else None
    featured_requested = "featured_media_id" in data.model_fields_set
    new_featured = await _get_featured_media(session, data.featured_media_id) if featured_requested else None

    tr = next((t for t in post.translations if t.locale == data.locale), None)
    new_slug = _requested_slug(user, tr, data.slug) if data.slug is not None else None
    if new_slug is not None and await _slug_taken(session, tr.locale, new_slug, tr.id):
        raise AppError(409, "SLUG_TAKEN", "That slug is already used by another article in this language")

    now = utcnow()
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

    slug_changes: list[SlugChange] = []
    redirects: list[dict[str, str]] = []
    redirect: dict[str, str] | None = None
    if new_slug is not None:
        category = await session.get(Category, post.category_id)
        old_slug = tr.slug
        old_path = seo_service.article_path(tr.locale, category.slug, old_slug)
        new_path = seo_service.article_path(tr.locale, category.slug, new_slug)
        try:
            async with session.begin_nested():  # a concurrent save can still take the slug
                tr.slug = new_slug
                await session.flush()
        except IntegrityError as exc:
            if not _is_slug_conflict(exc):
                raise
            raise AppError(409, "SLUG_TAKEN", "That slug is already used by another article in this language") from exc
        tr.updated_at = now
        paths = await seo_service.record_slug_change(session, old_path, new_path)
        slug_changes.append(SlugChange(tr.locale, old_slug, paths))
        redirect = {"from": old_path, "to": new_path}
        redirects.append(redirect)

    category_moved_publicly = False
    old_category_id: int | None = None
    if new_category is not None:
        old_category = await session.get(Category, post.category_id)
        old_category_id = old_category.id
        post.category_id = new_category.id
        if post.status == PostStatus.published:
            for t in post.translations:
                if t.status != TranslationStatus.published:
                    continue
                old_path = seo_service.article_path(t.locale, old_category.slug, t.slug)
                new_path = seo_service.article_path(t.locale, new_category.slug, t.slug)
                paths = await seo_service.record_slug_change(session, old_path, new_path)
                slug_changes.append(SlugChange(t.locale, t.slug, paths))
                redirects.append({"from": old_path, "to": new_path})
                t.updated_at = now  # the canonical URL changed
                category_moved_publicly = True

    breaking_changed = data.is_breaking is not None and data.is_breaking != post.is_breaking
    if breaking_changed:
        post.is_breaking = data.is_breaking
    featured_changed = featured_requested and data.featured_media_id != post.featured_media_id
    if featured_changed:
        post.featured_media = new_featured
    if tags is not None:
        post.tags = tags
    post.updated_at = now

    # `before` exists only for an already-published translation, and the snapshot covers every
    # public field of it, so one comparison drives both the revision and the public side.
    translation_changed = before is not None and _snapshot(tr) != before
    if translation_changed:
        session.add(PostRevision(post_id=post.id, locale=tr.locale, editor_id=user.id, **before))
    # Tags are not public yet. The breaking flag and the featured image show on cards whichever translation is edited.
    public_changed = post.status == PostStatus.published and (
        translation_changed or breaking_changed or category_moved_publicly or featured_changed
    )
    if public_changed:
        event = _post_event("post.updated", post)
        if old_category_id is not None:  # lets the worker revalidate the category it left
            event.payload = {**event.payload, "old_category_id": old_category_id}
        if redirects:  # lets the worker purge the old URLs
            event.payload = {**event.payload, "redirects": redirects}
            if redirect is not None:
                event.payload["redirect"] = redirect
        session.add(event)
    return UpdateResult(await _save(session, post), public_changed, slug_changes)


async def _revisions_viewable_post(session: AsyncSession, user: User, post_id: uuid.UUID) -> Post:
    post = await get_post(session, post_id)
    if post.author_id != user.id and not _is_editor(user):
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot view this post's revisions")
    return post


async def list_revisions(
    session: AsyncSession, user: User, post_id: uuid.UUID, locale: str | None = None,
    *, limit: int = 20, offset: int = 0,
) -> tuple[list[PostRevision], int]:
    """One page of revisions, newest first, without content_json (get_revision has that)."""
    await _revisions_viewable_post(session, user, post_id)
    where = [PostRevision.post_id == post_id]
    if locale is not None:
        where.append(PostRevision.locale == locale)
    total = await session.scalar(select(func.count()).select_from(PostRevision).where(*where))
    stmt = (
        select(PostRevision)
        .options(defer(PostRevision.content_json))
        .where(*where)
        .order_by(PostRevision.created_at.desc(), PostRevision.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(stmt)).all()), total or 0


async def _load_revision(session: AsyncSession, post_id: uuid.UUID, rev_id: int) -> PostRevision:
    # populate_existing: a list query in the same session may have loaded this row without content_json.
    rev = await session.scalar(
        select(PostRevision)
        .where(PostRevision.id == rev_id, PostRevision.post_id == post_id)
        .execution_options(populate_existing=True)
    )
    if rev is None:
        raise AppError(404, "REVISION_NOT_FOUND", "Revision not found")
    return rev


async def get_revision(session: AsyncSession, user: User, post_id: uuid.UUID, rev_id: int) -> PostRevision:
    await _revisions_viewable_post(session, user, post_id)
    return await _load_revision(session, post_id, rev_id)


async def restore_revision(
    session: AsyncSession, user: User, post_id: uuid.UUID, rev_id: int, if_match: str | None
) -> UpdateResult:
    """Write a revision's content back as an ordinary versioned save.

    update_post records the state being replaced as a new revision and emits post.updated if the
    translation is live. The slug is not restored: it changes only through the explicit slug field,
    which also writes redirects.
    """
    rev = await _load_revision(session, post_id, rev_id)
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
    """Publish a draft, in-review or scheduled post (editor+; the router enforces the role).

    Editors own publishing, so a draft does not need to be submitted first (decided in M2a part 2).
    Publishing publishes the translations that exist at this moment and bumps their updated_at,
    so dateModified is never earlier than datePublished.
    """
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status not in (PostStatus.draft, PostStatus.in_review, PostStatus.scheduled):
        raise AppError(409, "INVALID_TRANSITION", f"Cannot publish a post that is {post.status.value}")
    now = utcnow()
    _apply_publish(session, post, now, now)
    return await _save(session, post)


def _apply_publish(session: AsyncSession, post: Post, now: datetime, published_at: datetime) -> None:
    """Shared by manual and scheduled publishing; the caller holds the row lock, checked the status and saves.

    `published_at` is when the post counts as published (the scheduled time for a scheduled post);
    updated_at is `now`, so it is never earlier than a published date.
    """
    post.status = PostStatus.published
    post.published_at = post.published_at or published_at
    post.scheduled_at = None
    post.updated_at = now
    for tr in post.translations:  # only the translations that exist right now
        if tr.status != TranslationStatus.published:
            tr.status = TranslationStatus.published
            tr.published_at = published_at
            tr.updated_at = now
    session.add(_post_event("post.published", post))


SCHEDULE_MIN_LEAD = timedelta(seconds=60)
SCHEDULE_MAX_AHEAD = timedelta(days=365)


async def schedule_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None, when: datetime) -> Post:
    """draft | in_review | scheduled → scheduled (rescheduling allowed). Editor+; the router enforces the role."""
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status not in (PostStatus.draft, PostStatus.in_review, PostStatus.scheduled):
        raise AppError(409, "INVALID_TRANSITION", f"Cannot schedule a post that is {post.status.value}")
    now = utcnow()
    if when < now + SCHEDULE_MIN_LEAD:
        raise AppError(422, "INVALID_SCHEDULE_TIME", "scheduled_at must be at least 60 seconds in the future")
    if when > now + SCHEDULE_MAX_AHEAD:
        raise AppError(422, "INVALID_SCHEDULE_TIME", "scheduled_at must be at most one year ahead")
    post.status = PostStatus.scheduled
    post.scheduled_at = when
    post.updated_at = now
    return await _save(session, post)


async def unschedule_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post:
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status != PostStatus.scheduled:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot unschedule a post that is {post.status.value}")
    post.status = PostStatus.draft
    post.scheduled_at = None
    post.updated_at = utcnow()
    return await _save(session, post)


async def due_post_ids(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    stmt = (
        select(Post.id)
        .where(Post.status == PostStatus.scheduled, Post.scheduled_at <= utcnow())
        .order_by(Post.scheduled_at, Post.id)
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def publish_due_post(session: AsyncSession, post_id: uuid.UUID) -> Post | None:
    """Internal (no If-Match): publish one scheduled post whose time has come, committing in the caller's session.

    Returns None when the post is no longer due (published, unscheduled, rescheduled) or another
    worker holds its row lock (SKIP LOCKED), so overlapping runs never double-publish.
    """
    stmt = (
        select(Post)
        .where(Post.id == post_id, Post.status == PostStatus.scheduled, Post.scheduled_at <= utcnow())
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    post = await session.scalar(stmt)
    if post is None:
        return None
    _apply_publish(session, post, utcnow(), post.scheduled_at)
    return await _save(session, post)


async def unarchive_post(session: AsyncSession, post_id: uuid.UUID, if_match: str | None) -> Post:
    """archived → published. Translation statuses were kept on unpublish, so published ones are visible again."""
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
    if post.status != PostStatus.archived:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot unarchive a post that is {post.status.value}")
    if not any(t.status == TranslationStatus.published for t in post.translations):
        raise AppError(409, "NO_PUBLISHED_TRANSLATION", "No translation is published; publish one before unarchiving")
    post.status = PostStatus.published
    post.updated_at = utcnow()
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


async def send_back_post(
    session: AsyncSession, editor: User, post_id: uuid.UUID, if_match: str | None, note: str | None
) -> Post:
    """in_review → draft, so the reporter can edit again. The note travels in the outbox payload."""
    post = await _get_post_for_update(session, post_id)
    _check_version(post, if_match)
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
    """published → archived. Translations keep their status, so unarchive can restore them."""
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
