import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow

if TYPE_CHECKING:
    from app.modules.media.models import Media
    from app.modules.taxonomy.models import Tag


class PostStatus(StrEnum):
    draft = "draft"
    in_review = "in_review"
    scheduled = "scheduled"
    published = "published"
    archived = "archived"


class TranslationStatus(StrEnum):
    draft = "draft"
    published = "published"


# Title outranks body. 'simple' (no stemming) works for both Nepali and English.
SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('simple'::regconfig, title), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, body_text), 'B')"
)


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_status_published_at", "status", "published_at"),
        Index("ix_posts_category_published_at", "category_id", "published_at"),
        Index("ix_posts_featured_media_id", "featured_media_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, name="post_status"), default=PostStatus.draft, server_default=PostStatus.draft.value
    )
    featured_media_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media.id", ondelete="SET NULL"))
    is_breaking: Mapped[bool] = mapped_column(default=False, server_default=false())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    translations: Mapped[list["PostTranslation"]] = relationship(
        back_populates="post", lazy="selectin", cascade="all, delete-orphan", order_by="PostTranslation.id"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary="post_tags", lazy="selectin", order_by="Tag.id")
    featured_media: Mapped["Media | None"] = relationship(lazy="selectin")


class PostTranslation(Base):
    __tablename__ = "post_translations"
    __table_args__ = (
        UniqueConstraint("locale", "slug", name="uq_translation_locale_slug"),
        UniqueConstraint("post_id", "locale", name="uq_translation_post_locale"),
        Index("ix_post_translations_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_post_translations_title_trgm", "title",
            postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"},
        ),
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
    excerpt: Mapped[str | None] = mapped_column(String(300))  # editor override; cards fall back to body_text
    body_text: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))  # plain text of content_html
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR_SQL, persisted=True), deferred=True
    )
    status: Mapped[TranslationStatus] = mapped_column(
        Enum(TranslationStatus, name="translation_status"),
        default=TranslationStatus.draft,
        server_default=TranslationStatus.draft.value,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    post: Mapped[Post] = relationship(back_populates="translations")


class PostRevision(Base):
    """Prior state of a published translation, saved before an edit replaced it."""

    __tablename__ = "post_revisions"
    __table_args__ = (Index("ix_post_revisions_post_id_created_at", "post_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(String(2))
    title: Mapped[str] = mapped_column(String(300))
    slug: Mapped[str] = mapped_column(String(100))
    content_json: Mapped[dict] = mapped_column(JSONB)
    seo_title: Mapped[str | None] = mapped_column(String(120))
    seo_description: Mapped[str | None] = mapped_column(String(320))
    excerpt: Mapped[str | None] = mapped_column(String(300))
    editor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))  # whose save replaced this state
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
