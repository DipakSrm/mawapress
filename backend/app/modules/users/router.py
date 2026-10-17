import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import Enqueuer, enqueue_quietly, get_enqueuer
from app.db.session import get_session
from app.modules.auth.deps import require_role
from app.modules.users import service
from app.modules.users.models import Role, User
from app.modules.users.schemas import PasswordSet, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])
admins = require_role(Role.admin)


@router.get("", response_model=list[UserOut])
async def list_users(admin: User = Depends(admins), session: AsyncSession = Depends(get_session)) -> list[User]:
    return await service.list_users(session)


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate, admin: User = Depends(admins), session: AsyncSession = Depends(get_session)
) -> User:
    return await service.create_user(session, body)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    admin: User = Depends(admins),
    session: AsyncSession = Depends(get_session),
    enqueue: Enqueuer = Depends(get_enqueuer),
) -> User:
    user = await service.update_user(session, admin, user_id, body)
    if body.name is not None:  # stored SEO embeds the author name; refresh it off-request
        await enqueue_quietly(enqueue, "refresh_seo_for", "user", str(user.id))
    return user


@router.post("/{user_id}/password", status_code=204)
async def set_password(
    user_id: uuid.UUID, body: PasswordSet, admin: User = Depends(admins), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.set_password(session, user_id, body.password)
    return Response(status_code=204)
