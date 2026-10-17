from pydantic import BaseModel

from app.modules.posts.schemas import PostOut


class ImportReport(BaseModel):
    images: int
    warnings: list[str]


class ImportOut(BaseModel):
    post: PostOut
    report: ImportReport
