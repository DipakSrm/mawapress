import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.auth.security import hash_password, verify_password
from app.modules.users.models import Role, User
from app.modules.users.schemas import MeUpdate, UserCreate, UserUpdate


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_taken_error() -> AppError:
    return AppError(409, "EMAIL_TAKEN", "A user with this email already exists")


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.created_at, User.id))).all())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(404, "USER_NOT_FOUND", "User not found")
    return user


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    email = normalize_email(data.email)
    if await session.scalar(select(User.id).where(User.email == email)) is not None:
        raise _email_taken_error()
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        name=data.name,
        role=data.role,
        bio=data.bio or None,
    )
    try:
        async with session.begin_nested():  # a concurrent create can still win the race
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise _email_taken_error() from exc
    await session.commit()
    return user


async def update_user(session: AsyncSession, actor: User, user_id: uuid.UUID, data: UserUpdate) -> User:
    user = await get_user(session, user_id)
    if user.id == actor.id and (data.is_active is False or (data.role is not None and data.role != Role.admin)):
        raise AppError(409, "CANNOT_MODIFY_SELF", "Admins cannot deactivate or demote themselves")
    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    await session.commit()
    return user


async def set_password(session: AsyncSession, user_id: uuid.UUID, password: str) -> None:
    user = await get_user(session, user_id)
    user.password_hash = hash_password(password)
    await session.commit()


async def update_me(session: AsyncSession, user: User, data: MeUpdate) -> User:
    if data.new_password is not None:
        if data.current_password is None or not verify_password(data.current_password, user.password_hash):
            raise AppError(403, "INVALID_CURRENT_PASSWORD", "Current password is incorrect")
        user.password_hash = hash_password(data.new_password)
    if data.name is not None:
        user.name = data.name
    if "bio" in data.model_fields_set:
        user.bio = data.bio or None
    await session.commit()
    return user
