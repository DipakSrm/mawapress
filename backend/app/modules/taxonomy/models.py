from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", name="fk_categories_parent_id"))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name_ne: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))
    sort: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    seo_description: Mapped[str | None] = mapped_column(String(320))
