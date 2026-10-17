import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.auth.service import revoke_user_sessions
from app.modules.auth.security import hash_password, verify_password
from app.modules.users.models import Role, User
from app.modules.users.schemas import MeUpdate, UserCreate, UserUpdate


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_taken_error() -> AppError:
    return AppError(409, "EMAIL_TAKEN", "A user with this email already exists")


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.created_at, User.id))).all())


async def list_authors(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name, User.id))).all())


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
    changes_admin_standing = data.role is not None or data.is_active is not None
    active_admin_ids: list[uuid.UUID] = []
    if changes_admin_standing:
        # Lock every active admin row, always in id order, before touching the target. Two admins
        # demoting each other then serialise here instead of both seeing "another admin remains".
        active_admin_ids = list((await session.scalars(
            select(User.id)
            .where(User.role == Role.admin, User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )).all())
    user = await get_user(session, user_id)
    if changes_admin_standing:
        await session.refresh(user)  # re-read under the lock: role/is_active may have just changed
    if user.id == actor.id and (data.is_active is False or (data.role is not None and data.role != Role.admin)):
        raise AppError(409, "CANNOT_MODIFY_SELF", "Admins cannot deactivate or demote themselves")
    loses_admin = (
        user.role == Role.admin and user.is_active
        and (data.is_active is False or (data.role is not None and data.role != Role.admin))
    )
    if loses_admin and not any(admin_id != user.id for admin_id in active_admin_ids):
        raise AppError(409, "LAST_ADMIN", "At least one active admin must remain")
    revoke = (data.role is not None and data.role != user.role) or (data.is_active is False and user.is_active)
    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if revoke:
        await revoke_user_sessions(session, user)
    await session.commit()
    return user


async def set_password(session: AsyncSession, user_id: uuid.UUID, password: str) -> None:
    user = await get_user(session, user_id)
    user.password_hash = hash_password(password)
    await revoke_user_sessions(session, user)
    await session.commit()


async def update_me(session: AsyncSession, user: User, data: MeUpdate) -> User:
    if data.current_password is not None and data.new_password is None:
        raise AppError(422, "NEW_PASSWORD_REQUIRED", "new_password is required when current_password is given")
    if data.new_password is not None:
        if data.current_password is None or not verify_password(data.current_password, user.password_hash):
            raise AppError(403, "INVALID_CURRENT_PASSWORD", "Current password is incorrect")
        if data.new_password == data.current_password:
            raise AppError(422, "PASSWORD_UNCHANGED", "New password must differ from the current one")
        user.password_hash = hash_password(data.new_password)
        await revoke_user_sessions(session, user)
    if data.name is not None:
        user.name = data.name
    if "bio" in data.model_fields_set:
        user.bio = data.bio or None
    await session.commit()
    return user
