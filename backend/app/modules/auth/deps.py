import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.security import decode_access_token
from app.modules.users.models import Role, User

ROLE_RANK = {Role.reporter: 1, Role.editor: 2, Role.admin: 3}
_bearer = HTTPBearer(auto_error=False)


def _user_id_from_token(token: str) -> uuid.UUID | None:
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    sub = claims.get("sub")
    if not isinstance(sub, str):
        return None
    try:
        return uuid.UUID(sub)
    except ValueError:
        return None


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None:
        raise AppError(401, "NOT_AUTHENTICATED", "Login required")
    user_id = _user_id_from_token(creds.credentials)
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise AppError(401, "INVALID_TOKEN", "Token is invalid or expired")
    return user


def require_role(min_role: Role):
    async def dependency(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[min_role]:
            raise AppError(403, "FORBIDDEN_ROLE", f"Requires {min_role.value} role or higher")
        return user

    return dependency
