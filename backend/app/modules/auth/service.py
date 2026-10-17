import hashlib
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.base import utcnow
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_token(user_id: uuid.UUID, family_id: uuid.UUID) -> tuple[str, RefreshToken]:
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=hash_token(raw),
        family_id=family_id,
        expires_at=utcnow() + timedelta(days=get_settings().refresh_days),
    )
    return raw, row


async def issue_refresh_token(session: AsyncSession, user: User) -> str:
    """Start a new token family (a fresh login). Commits."""
    raw, row = _new_token(user.id, uuid.uuid4())
    session.add(row)
    await session.commit()
    return raw


async def rotate_refresh_token(session: AsyncSession, raw: str) -> tuple[User, str]:
    """Validate `raw`, revoke it and issue its successor in the same family. Commits.

    Presenting an already-revoked token means it leaked (or was replayed): the whole
    family is revoked and REFRESH_REUSED is returned."""
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update()
    )
    if row is None:
        raise AppError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired")
    now = utcnow()
    if row.revoked_at is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        raise AppError(401, "REFRESH_REUSED", "Refresh token was already used; please sign in again")
    user = await session.get(User, row.user_id)
    if row.expires_at <= now or user is None or not user.is_active:
        raise AppError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired")
    new_raw, new_row = _new_token(user.id, row.family_id)
    session.add(new_row)
    row.revoked_at = now
    row.replaced_by = new_row.id
    await session.commit()
    return user, new_raw


async def revoke_refresh_token(session: AsyncSession, raw: str) -> None:
    """Revoke a single token (logout). Unknown or already-revoked tokens are a no-op. Commits."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await session.commit()


async def revoke_user_sessions(session: AsyncSession, user: User) -> None:
    """Invalidate every access token (token_version bump) and refresh token of `user`.

    Does not commit: callers do so together with the change that triggered it."""
    user.token_version += 1
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
