from datetime import timedelta

from sqlalchemy import delete, or_

from app.db.base import utcnow
from app.modules.auth.models import RefreshToken

REFRESH_TOKEN_GRACE = timedelta(days=7)


async def purge_refresh_tokens(ctx: dict) -> int:
    """Daily: drop refresh tokens that expired, or were revoked, more than 7 days ago."""
    cutoff = utcnow() - REFRESH_TOKEN_GRACE
    async with ctx["session_factory"]() as session:
        result = await session.execute(
            delete(RefreshToken).where(or_(RefreshToken.expires_at < cutoff, RefreshToken.revoked_at < cutoff))
        )
        await session.commit()
    return result.rowcount
