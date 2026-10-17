from datetime import datetime

from sqlalchemy import DateTime, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Redirect(Base):
    __tablename__ = "redirects"

    from_path: Mapped[str] = mapped_column(String(300), primary_key=True)
    to_path: Mapped[str] = mapped_column(String(300), index=True)  # indexed for chain collapsing
    code: Mapped[int] = mapped_column(SmallInteger, default=301, server_default=text("301"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
