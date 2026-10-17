import secrets
import uuid

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.cache import get_redis
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_session
from app.modules.auth.deps import current_user
from app.modules.auth import service
from app.modules.auth.security import DUMMY_PASSWORD_HASH, create_access_token, verify_password
from app.modules.users import service as users_service
from app.modules.users.models import Role, User
from app.modules.users.schemas import MeUpdate

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "mawa_refresh"
CSRF_COOKIE = "mawa_csrf"


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
    bio: str | None


class MeUpdateOut(MeOut):
    access_token: str | None = None  # present only after a password change


def _set_session_cookies(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    max_age = settings.refresh_days * 86400
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, max_age=max_age, httponly=True,
        secure=settings.cookie_secure, samesite="lax", path="/api/auth",
    )
    # Readable by the frontend so it can echo the value in X-CSRF-Token (double submit).
    response.set_cookie(
        CSRF_COOKIE, secrets.token_urlsafe(32), max_age=max_age, httponly=False,
        secure=settings.cookie_secure, samesite="lax", path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")


def require_csrf(
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    if not csrf_cookie or not csrf_header or not secrets.compare_digest(
        csrf_cookie.encode("utf-8", "surrogatepass"), csrf_header.encode("utf-8", "surrogatepass")
    ):
        raise AppError(403, "CSRF_FAILED", "CSRF token missing or invalid")


async def login_rate_limit(
    body: LoginIn, request: Request, redis: Redis = Depends(get_redis)
) -> None:
    ip = ratelimit.client_ip(request)
    await ratelimit.enforce(redis, f"rl:login:{ip}:{ratelimit.digest(body.email.lower())}", ratelimit.LOGIN_PER_IP_EMAIL)
    await ratelimit.enforce(redis, f"rl:login-ip:{ip}", ratelimit.LOGIN_PER_IP)
    await ratelimit.enforce_account_not_capped(redis, body.email)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(login_rate_limit)])
async def login(
    body: LoginIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> TokenOut:
    user = await session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active:
        verify_password(body.password, DUMMY_PASSWORD_HASH)  # same cost as a real check
        await ratelimit.record_failed_login(redis, body.email)
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
    if not verify_password(body.password, user.password_hash):
        await ratelimit.record_failed_login(redis, body.email)
        raise AppError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
    _set_session_cookies(response, await service.issue_refresh_token(session, user))
    return TokenOut(access_token=create_access_token(user.id, user.role.value, user.token_version))


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(require_csrf)])
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    if not refresh_token:
        raise AppError(401, "NOT_AUTHENTICATED", "Login required")
    user, new_token = await service.rotate_refresh_token(session, refresh_token)
    _set_session_cookies(response, new_token)
    return TokenOut(access_token=create_access_token(user.id, user.role.value, user.token_version))


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
async def logout(
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if refresh_token:
        await service.revoke_refresh_token(session, refresh_token)
    response = Response(status_code=204)
    _clear_session_cookies(response)
    return response


@router.get("/me", response_model=MeOut)
async def me(user: User = Depends(current_user)) -> User:
    return user


@router.patch("/me", response_model=MeUpdateOut)
async def update_me(
    body: MeUpdate,
    response: Response,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeUpdateOut:
    """A password change revokes every session; this one is replaced with a fresh token family
    (new refresh and CSRF cookies, new access token in the body) so the caller stays signed in."""
    user = await users_service.update_me(session, user, body)
    out = MeUpdateOut.model_validate(user)
    if body.new_password is not None:
        _set_session_cookies(response, await service.issue_refresh_token(session, user))
        out.access_token = create_access_token(user.id, user.role.value, user.token_version)
    return out
