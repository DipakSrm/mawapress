import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.security import create_access_token, hash_password
from app.modules.taxonomy.models import Category
from app.modules.users.models import Role, User


async def make_user(
    session: AsyncSession,
    *,
    role: Role = Role.reporter,
    email: str | None = None,
    password: str = "secret-pass-1",
    name: str = "Test User",
    is_active: bool = True,
) -> User:
    user = User(
        email=(email or f"{uuid.uuid4().hex[:10]}@mawapress.com").lower(),
        password_hash=hash_password(password),
        name=name,
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


async def make_category(session: AsyncSession, slug: str = "morang", name_ne: str = "मोरङ", name_en: str = "Morang") -> Category:
    cat = Category(slug=slug, name_ne=name_ne, name_en=name_en)
    session.add(cat)
    await session.flush()
    return cat


def auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.value)}"}


def auth_if_match(user: User, updated_at: str) -> dict[str, str]:
    return {**auth_header(user), "If-Match": updated_at}
