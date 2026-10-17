import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.deps import ROLE_RANK, require_role
from app.modules.posts import service
from app.modules.posts.models import Post, PostStatus
from app.modules.posts.schemas import (
    Locale,
    PostCreate,
    PostListOut,
    PostOut,
    PostSummary,
    PostUpdate,
    RevisionListOut,
    RevisionOut,
    ScheduleIn,
    SendBackIn,
    TranslationSummary,
)
from app.modules.public.service import invalidate_public, invalidate_slug_change
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api/posts", tags=["posts"])
RevisionId = Annotated[int, Path(ge=1, le=2**63 - 1)]  # revision ids are BIGINT; anything larger would be a 500
any_staff = require_role(Role.reporter)
editors = require_role(Role.editor)


def _summary(post: Post, author_name: str) -> PostSummary:
    return PostSummary(
        id=post.id,
        status=post.status,
        category_id=post.category_id,
        author_id=post.author_id,
        author_name=author_name,
        view_count=post.view_count,
        updated_at=post.updated_at,
        published_at=post.published_at,
        scheduled_at=post.scheduled_at,
        translations=[TranslationSummary.model_validate(t) for t in post.translations],
    )


@router.post("", response_model=PostOut, status_code=201)
async def create_post(body: PostCreate, user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)) -> Post:
    return await service.create_post(session, user, body)


@router.get("", response_model=PostListOut)
async def list_posts(
    status: PostStatus | None = None,
    author_id: uuid.UUID | None = None,
    category_id: int | None = None,
    locale: Locale | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
) -> PostListOut:
    posts, total = await service.list_posts(
        session, user,
        status=status, author_id=author_id, category_id=category_id, locale=locale, q=q,
        limit=limit, offset=offset,
    )
    return PostListOut(
        items=[_summary(p, author_name) for p, author_name in posts], total=total, limit=limit, offset=offset
    )


@router.get("/{post_id}", response_model=PostOut)
async def get_post(post_id: uuid.UUID, user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)) -> Post:
    post = await service.get_post(session, post_id)
    if post.author_id != user.id and ROLE_RANK[user.role] < ROLE_RANK[Role.editor]:
        raise AppError(403, "FORBIDDEN_ROLE", "You cannot view this post")
    return post


@router.patch("/{post_id}", response_model=PostOut)
async def update_post(
    post_id: uuid.UUID,
    body: PostUpdate,
    if_match: str | None = Header(default=None),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    result = await service.update_post(session, user, post_id, if_match, body)
    if result.public_changed:
        await invalidate_public(redis, result.post)
    for change in result.slug_changes:
        await invalidate_slug_change(redis, change)
    return result.post


@router.post("/{post_id}/submit", response_model=PostOut)
async def submit_post(post_id: uuid.UUID, user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)) -> Post:
    return await service.submit_post(session, user, post_id)


@router.post("/{post_id}/publish", response_model=PostOut)
async def publish_post(
    post_id: uuid.UUID,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.publish_post(session, post_id, if_match)
    await invalidate_public(redis, post)
    return post


@router.post("/{post_id}/schedule", response_model=PostOut)
async def schedule_post(
    post_id: uuid.UUID,
    body: ScheduleIn,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
) -> Post:
    return await service.schedule_post(session, post_id, if_match, body.scheduled_at)


@router.post("/{post_id}/unschedule", response_model=PostOut)
async def unschedule_post(
    post_id: uuid.UUID,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
) -> Post:
    return await service.unschedule_post(session, post_id, if_match)


@router.post("/{post_id}/unarchive", response_model=PostOut)
async def unarchive_post(
    post_id: uuid.UUID,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.unarchive_post(session, post_id, if_match)
    await invalidate_public(redis, post)
    return post


@router.post("/{post_id}/translations/{locale}/publish", response_model=PostOut)
async def publish_translation(
    post_id: uuid.UUID,
    locale: Locale,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.publish_translation(session, post_id, locale, if_match)
    await invalidate_public(redis, post)
    return post


@router.post("/{post_id}/send-back", response_model=PostOut)
async def send_back_post(
    post_id: uuid.UUID,
    body: SendBackIn | None = None,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
) -> Post:
    return await service.send_back_post(session, user, post_id, if_match, body.note if body else None)


@router.post("/{post_id}/unpublish", response_model=PostOut)
async def unpublish_post(
    post_id: uuid.UUID,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    post = await service.unpublish_post(session, post_id, if_match)
    await invalidate_public(redis, post)
    return post


@router.get("/{post_id}/revisions", response_model=RevisionListOut)
async def list_revisions(
    post_id: uuid.UUID,
    locale: Locale | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
) -> RevisionListOut:
    items, total = await service.list_revisions(session, user, post_id, locale, limit=limit, offset=offset)
    return RevisionListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{post_id}/revisions/{rev_id}", response_model=RevisionOut)
async def get_revision(
    post_id: uuid.UUID,
    rev_id: RevisionId,
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
):
    return await service.get_revision(session, user, post_id, rev_id)


@router.post("/{post_id}/revisions/{rev_id}/restore", response_model=PostOut)
async def restore_revision(
    post_id: uuid.UUID,
    rev_id: RevisionId,
    if_match: str | None = Header(default=None),
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Post:
    result = await service.restore_revision(session, user, post_id, rev_id, if_match)
    if result.public_changed:
        await invalidate_public(redis, result.post)
    return result.post
