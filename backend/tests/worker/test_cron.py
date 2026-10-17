import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy import select

from app.db.base import utcnow
from app.modules.auth.models import RefreshToken
from app.worker.maintenance import purge_refresh_tokens
from app.worker.outbox import process_outbox
from app.worker.settings import WorkerSettings
from tests.factories import make_user


async def _token(session, user, *, expires, revoked=None) -> RefreshToken:
    t = RefreshToken(
        user_id=user.id, token_hash=uuid.uuid4().hex + uuid.uuid4().hex, family_id=uuid.uuid4(),
        expires_at=expires, revoked_at=revoked,
    )
    session.add(t)
    await session.flush()
    return t


async def test_purge_refresh_tokens_removes_only_old_dead_tokens(session):
    user = await make_user(session)
    now = utcnow()
    old_expired = await _token(session, user, expires=now - timedelta(days=8))
    old_revoked = await _token(session, user, expires=now + timedelta(days=5), revoked=now - timedelta(days=8))
    recent_expired = await _token(session, user, expires=now - timedelta(days=2))
    recent_revoked = await _token(session, user, expires=now + timedelta(days=5), revoked=now - timedelta(days=1))
    live = await _token(session, user, expires=now + timedelta(days=5))

    @asynccontextmanager
    async def factory():
        yield session

    await purge_refresh_tokens({"session_factory": factory})
    remaining = set((await session.scalars(select(RefreshToken.id))).all())
    assert remaining == {recent_expired.id, recent_revoked.id, live.id}
    assert old_expired.id not in remaining and old_revoked.id not in remaining


def test_worker_settings_register_jobs():
    names = {c.name for c in WorkerSettings.cron_jobs}
    assert {"cron:process_outbox", "cron:purge_refresh_tokens"} <= names
    assert process_outbox in {c.coroutine for c in WorkerSettings.cron_jobs}
    assert WorkerSettings.redis_settings.host
