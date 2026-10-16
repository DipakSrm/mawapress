from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text120 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
SlugIn = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Sort = Annotated[int, Field(ge=-10000, le=10000)]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_ne: Text120
    name_en: Text120
    slug: SlugIn | None = None  # defaults to make_slug(name_en)
    parent_id: int | None = None
    sort: Sort = 0
    seo_description: str | None = Field(default=None, max_length=320)


class CategoryUpdate(BaseModel):
    """The slug is immutable here: changing it would break every article URL in the category."""

    model_config = ConfigDict(extra="forbid")

    name_ne: Text120 | None = None
    name_en: Text120 | None = None
    parent_id: int | None = None  # send null explicitly to move to the root
    sort: Sort | None = None
    seo_description: str | None = Field(default=None, max_length=320)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    slug: str
    name_ne: str
    name_en: str
    sort: int
    seo_description: str | None


class CategoryNode(CategoryOut):
    children: list["CategoryNode"] = Field(default_factory=list)
