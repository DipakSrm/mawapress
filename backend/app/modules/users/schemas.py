import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.modules.users.models import Role

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Password = Annotated[str, Field(min_length=10, max_length=128)]
Bio = Annotated[str, Field(max_length=2000)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: Role
    is_active: bool
    bio: str | None
    created_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: Name
    role: Role
    password: Password
    bio: Bio | None = None


class UserUpdate(BaseModel):
    """Admin edit. Email is deliberately not editable here (extra fields are a 422)."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    role: Role | None = None
    is_active: bool | None = None


class PasswordSet(BaseModel):
    password: Password


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    bio: Bio | None = None
    current_password: str | None = Field(default=None, max_length=128)
    new_password: Password | None = None
