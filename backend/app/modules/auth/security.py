import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.db.base import utcnow

_hasher = PasswordHasher()
ALGORITHM = "HS256"
REQUIRED_CLAIMS = ["exp", "sub", "iat"]

# Verified against when the email is unknown or the user is inactive, so a failed
# login costs one argon2 verify either way and response time does not leak which
# emails exist.
DUMMY_PASSWORD_HASH = _hasher.hash("mawapress-timing-equaliser")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, role: str, token_version: int) -> str:
    settings = get_settings()
    now = utcnow()
    claims = {"sub": str(user_id), "role": role, "tv": token_version, "iat": now, "exp": now + timedelta(minutes=settings.jwt_access_minutes)}
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate. Raises jwt.PyJWTError on any problem, including a missing
    exp/sub/iat claim or a non-string sub (PyJWT >= 2.10 validates sub's type)."""
    return jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=[ALGORITHM],
        options={"require": REQUIRED_CLAIMS},
    )
