import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.media.schemas import MediaOut
from app.modules.posts.models import PostStatus, TranslationStatus
from app.modules.taxonomy.schemas import TagOut

Locale = Literal["ne", "en"]


class PostCreate(BaseModel):
    locale: Locale
    title: str = Field(min_length=1, max_length=300)
    content_json: dict
    category_id: int
    tag_ids: list[int] = Field(default_factory=list, max_length=20)
    featured_media_id: uuid.UUID | None = None


class SendBackIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ScheduleIn(BaseModel):
    scheduled_at: AwareDatetime


class PostUpdate(BaseModel):
    locale: Locale
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content_json: dict | None = None
    seo_title: str | None = Field(default=None, max_length=120)
    seo_description: str | None = Field(default=None, max_length=320)
    tag_ids: list[int] | None = Field(default=None, max_length=20)  # None = unchanged, [] = clear
    excerpt: str | None = Field(default=None, max_length=300)  # "" clears the override
    is_breaking: bool | None = None  # editor+ only
    slug: str | None = None  # length checked in the service (INVALID_SLUG); editor+, published translations only; writes a 301
    category_id: int | None = None  # moves the post; published translations get a 301 from their old path
    featured_media_id: uuid.UUID | None = None  # omitted = unchanged, null = clear


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
    excerpt: str | None
    seo_auto: dict


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: PostStatus
    is_breaking: bool
    view_count: int
    author_id: uuid.UUID
    category_id: int
    featured_media_id: uuid.UUID | None
    featured_media: MediaOut | None
    published_at: datetime | None
    scheduled_at: datetime | None
    schedule_attempts: int
    schedule_last_error: str | None
    updated_at: datetime
    translations: list[TranslationOut]
    tags: list[TagOut]


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
    view_count: int
    updated_at: datetime
    published_at: datetime | None
    scheduled_at: datetime | None
    translations: list[TranslationSummary]


class PostListOut(BaseModel):
    items: list[PostSummary]
    total: int
    limit: int
    offset: int


class RevisionSummary(BaseModel):
    """A revision as listed: without content_json, which can be large."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    locale: str
    title: str
    slug: str
    seo_title: str | None
    seo_description: str | None
    excerpt: str | None
    editor_id: uuid.UUID
    created_at: datetime


class RevisionOut(RevisionSummary):
    content_json: dict


class RevisionListOut(BaseModel):
    items: list[RevisionSummary]
    total: int
    limit: int
    offset: int
