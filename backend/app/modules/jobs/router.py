from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.outbox import OutboxEvent
from app.db.session import get_session
from app.modules.auth.deps import require_role
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api/admin/jobs", tags=["jobs"])
admins = require_role(Role.admin)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic: str
    attempts: int
    last_error: str | None
    payload: dict
    created_at: datetime
    next_attempt_at: datetime | None
    dead_at: datetime | None


class RetryDeadOut(BaseModel):
    requeued: int


@router.get("", response_model=list[JobOut])
async def list_jobs(
    state: Literal["dead", "pending"] = "pending",
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(admins),
    session: AsyncSession = Depends(get_session),
) -> list[OutboxEvent]:
    query = select(OutboxEvent).where(OutboxEvent.processed_at.is_(None))
    query = query.where(OutboxEvent.dead_at.is_not(None) if state == "dead" else OutboxEvent.dead_at.is_(None))
    return list((await session.scalars(query.order_by(OutboxEvent.id.desc()).limit(limit))).all())


@router.post("/retry-dead", response_model=RetryDeadOut)
async def retry_dead_jobs(admin: User = Depends(admins), session: AsyncSession = Depends(get_session)) -> RetryDeadOut:
    """Re-queue every dead-lettered event (attempts reset, due immediately)."""
    result = await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.dead_at.is_not(None), OutboxEvent.processed_at.is_(None))
        .values(dead_at=None, next_attempt_at=None, attempts=0)
    )
    await session.commit()
    return RetryDeadOut(requeued=result.rowcount)


@router.post("/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: int, admin: User = Depends(admins), session: AsyncSession = Depends(get_session)
) -> OutboxEvent:
    event = await session.get(OutboxEvent, job_id, with_for_update=True)
    if event is None:
        raise AppError(404, "JOB_NOT_FOUND", "Job not found")
    if event.processed_at is not None:
        raise AppError(409, "JOB_ALREADY_PROCESSED", "Job has already been processed")
    event.dead_at = None
    event.next_attempt_at = None
    event.attempts = 0
    await session.commit()
    return event
