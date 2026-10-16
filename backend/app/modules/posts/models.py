import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow


class PostStatus(StrEnum):
    draft = "draft"
    in_review = "in_review"
    scheduled = "scheduled"
    published = "published"
    archived = "archived"


class TranslationStatus(StrEnum):
    draft = "draft"
    published = "published"


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_status_published_at", "status", "published_at"),
        Index("ix_posts_category_published_at", "category_id", "published_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, name="post_status"), default=PostStatus.draft, server_default=PostStatus.draft.value
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    translations: Mapped[list["PostTranslation"]] = relationship(
        back_populates="post", lazy="selectin", cascade="all, delete-orphan", order_by="PostTranslation.id"
    )


class PostTranslation(Base):
    __tablename__ = "post_translations"
    __table_args__ = (
        UniqueConstraint("locale", "slug", name="uq_translation_locale_slug"),
        UniqueConstraint("post_id", "locale", name="uq_translation_post_locale"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(String(2))
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(100))
    content_json: Mapped[dict] = mapped_column(JSONB)
    content_html: Mapped[str] = mapped_column(Text)
    seo_title: Mapped[str | None] = mapped_column(String(120))
    seo_description: Mapped[str | None] = mapped_column(String(320))
    seo_auto: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    status: Mapped[TranslationStatus] = mapped_column(
        Enum(TranslationStatus, name="translation_status"),
        default=TranslationStatus.draft,
        server_default=TranslationStatus.draft.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    post: Mapped[Post] = relationship(back_populates="translations")
