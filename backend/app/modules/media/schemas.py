import uuid

from pydantic import BaseModel, ConfigDict, Field


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    width: int
    height: int
    alt_ne: str | None
    alt_en: str | None
    caption: str | None
    variants: dict[str, str]


class MediaListOut(BaseModel):
    items: list[MediaOut]
    total: int
    limit: int
    offset: int


class MediaPatch(BaseModel):
    alt_ne: str | None = Field(default=None, max_length=300)
    alt_en: str | None = Field(default=None, max_length=300)
    caption: str | None = Field(default=None, max_length=2000)
