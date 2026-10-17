import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.storage import get_storage
from app.db.base import Base, utcnow


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (Index("ix_media_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(200), unique=True)  # storage key of the original
    mime: Mapped[str] = mapped_column(String(50))
    width: Mapped[int]
    height: Mapped[int]
    size_bytes: Mapped[int] = mapped_column("bytes", BigInteger)
    alt_ne: Mapped[str | None] = mapped_column(String(300))
    alt_en: Mapped[str | None] = mapped_column(String(300))
    caption: Mapped[str | None] = mapped_column(Text)
    uploader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    variant_keys: Mapped[dict] = mapped_column(
        "variants", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )  # name -> storage key
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())

    @property
    def url(self) -> str:
        return get_storage().url(self.key)

    @property
    def variants(self) -> dict[str, str]:
        storage = get_storage()
        return {name: storage.url(key) for name, key in self.variant_keys.items()}
