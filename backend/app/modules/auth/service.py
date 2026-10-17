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


ROTATION_GRACE = timedelta(seconds=10)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_token(user: User, family_id: uuid.UUID) -> tuple[str, RefreshToken]:
    raw = secrets.token_urlsafe(48)
    row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_version=user.token_version,
        token_hash=hash_token(raw),
        family_id=family_id,
        expires_at=utcnow() + timedelta(days=get_settings().refresh_days),
    )
    return raw, row


async def issue_refresh_token(session: AsyncSession, user: User) -> str:
    """Start a new token family (a fresh login). Commits."""
    raw, row = _new_token(user, uuid.uuid4())
    session.add(row)
    await session.commit()
    return raw


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def rotate_refresh_token(session: AsyncSession, raw: str) -> tuple[User, str]:
    """Validate `raw`, revoke it and issue its successor in the same family. Commits.

    Lock order is user row, then token row (revoke_user_sessions takes the user row too), so a
    rotation can never commit a live successor after a password/role/deactivation revocation.

    Presenting an already-revoked token means it leaked or was replayed: the family is revoked and
    REFRESH_REUSED returned. A token rotated only moments ago is a second tab that lost the race:
    it gets REFRESH_STALE and the family is left alone."""
    token_hash = hash_token(raw)
    user_id = await session.scalar(select(RefreshToken.user_id).where(RefreshToken.token_hash == token_hash))
    if user_id is None:
        raise AppError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired")
    user = await session.scalar(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    )
    row = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or user is None:
        raise AppError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired")
    now = utcnow()
    if row.revoked_at is not None:
        if row.replaced_by is not None and now - row.revoked_at <= ROTATION_GRACE:
            raise AppError(401, "REFRESH_STALE", "Refresh token was just rotated; retry with the new cookie")
        await _revoke_family(session, row.family_id)
        await session.commit()
        raise AppError(401, "REFRESH_REUSED", "Refresh token was already used; please sign in again")
    if row.token_version != user.token_version:
        await _revoke_family(session, row.family_id)
        await session.commit()
        raise AppError(401, "INVALID_TOKEN", "Token is invalid or expired")
    if row.expires_at <= now or not user.is_active:
        raise AppError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired")
    new_raw, new_row = _new_token(user, row.family_id)
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
    # Take the user row lock (and read the committed version) so a concurrent rotation either
    # finishes first, and is revoked below, or waits and then fails the token_version check.
    current = await session.scalar(select(User.token_version).where(User.id == user.id).with_for_update())
    user.token_version = (current if current is not None else user.token_version) + 1
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
