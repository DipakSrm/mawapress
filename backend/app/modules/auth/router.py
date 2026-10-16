import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.deps import current_user
from app.modules.auth.security import DUMMY_PASSWORD_HASH, create_access_token, verify_password
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: Role


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active:
        verify_password(body.password, DUMMY_PASSWORD_HASH)  # same cost as a real check
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
    if not verify_password(body.password, user.password_hash):
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
    return TokenOut(access_token=create_access_token(user.id, user.role.value))


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(current_user)) -> User:
    return user
