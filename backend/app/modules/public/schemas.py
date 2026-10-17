import uuid
from datetime import datetime

from pydantic import BaseModel


class PublicImage(BaseModel):
    url: str
    width: int
    height: int
    alt: str  # the locale's alt text, else the caption, else the title
    variants: dict[str, str]


class PublicCard(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    excerpt: str
    category_slug: str
    author_name: str
    published_at: datetime | None
    image: PublicImage | None = None


class CardPage(BaseModel):
    items: list[PublicCard]
    total: int
    limit: int
    offset: int


class PublicCategory(BaseModel):
    id: int
    slug: str
    name: str  # in the requested locale
    seo_description: str | None


class HomeCategoryBlock(BaseModel):
    category: PublicCategory
    posts: list[PublicCard]


class HomeOut(BaseModel):
    breaking: list[PublicCard]
    categories: list[HomeCategoryBlock]


class CategoryFeedOut(BaseModel):
    category: PublicCategory
    items: list[PublicCard]
    total: int
    limit: int
    offset: int
