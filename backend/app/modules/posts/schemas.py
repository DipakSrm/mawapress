import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.posts.models import PostStatus, TranslationStatus

Locale = Literal["ne", "en"]


class PostCreate(BaseModel):
    locale: Locale
    title: str = Field(min_length=1, max_length=300)
    content_json: dict
    category_id: int


class PostUpdate(BaseModel):
    locale: Locale
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content_json: dict | None = None
    seo_title: str | None = Field(default=None, max_length=120)
    seo_description: str | None = Field(default=None, max_length=320)


class TranslationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    title: str
    slug: str
    status: TranslationStatus
    published_at: datetime | None
    content_json: dict
    content_html: str
    seo_title: str | None
    seo_description: str | None
    seo_auto: dict


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: PostStatus
    author_id: uuid.UUID
    category_id: int
    published_at: datetime | None
    updated_at: datetime
    translations: list[TranslationOut]


class TranslationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: str
    title: str
    slug: str
    status: TranslationStatus


class PostSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: PostStatus
    category_id: int
    author_id: uuid.UUID
    author_name: str
    updated_at: datetime
    published_at: datetime | None
    translations: list[TranslationSummary]


class PostListOut(BaseModel):
    items: list[PostSummary]
    total: int
    limit: int
    offset: int
