from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import Enqueuer, get_enqueuer
from app.core.storage import Storage, get_storage
from app.db.session import get_session
from app.modules.auth.deps import require_role
from app.modules.importer import service
from app.modules.importer.schemas import ImportOut
from app.modules.posts.schemas import Locale
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api/import", tags=["import"])
any_staff = require_role(Role.reporter)


@router.post("/docx", response_model=ImportOut, status_code=201)
async def import_docx(
    file: UploadFile = File(),
    locale: Annotated[Locale, Form()] = ...,
    category_id: Annotated[int, Form()] = ...,
    title: Annotated[str | None, Form(max_length=service.MAX_TITLE)] = None,
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
    enqueue: Enqueuer = Depends(get_enqueuer),
) -> ImportOut:
    raw = await file.read(service.MAX_DOCX_BYTES + 1)  # never buffer more than the cap plus one byte
    post, report = await service.import_docx(
        session, storage, enqueue, user,
        raw=raw, filename=file.filename, locale=locale, category_id=category_id, title=title,
    )
    return service.build_out(post, report)
