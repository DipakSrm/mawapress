import uuid
from datetime import datetime

from pydantic import BaseModel


class PublicCard(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    excerpt: str
    category_slug: str
    author_name: str
    published_at: datetime | None
    featured_image: str | None = None  # media and featured images arrive in M2b


class CardPage(BaseModel):
    items: list[PublicCard]
    total: int
    limit: int
    offset: int
