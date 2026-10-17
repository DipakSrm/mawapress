import uuid

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import Enqueuer, enqueue_quietly, get_enqueuer
from app.core.storage import MAX_UPLOAD_BYTES, Storage, get_storage
from app.db.session import get_session
from app.modules.auth.deps import require_role
from app.modules.media import service
from app.modules.media.models import Media
from app.modules.media.schemas import MediaListOut, MediaOut, MediaPatch
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api/media", tags=["media"])
any_staff = require_role(Role.reporter)
editors = require_role(Role.editor)


@router.post("", response_model=MediaOut, status_code=201)
async def upload_media(
    file: UploadFile = File(),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
    enqueue: Enqueuer = Depends(get_enqueuer),
) -> Media:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)  # never buffer more than the cap plus one byte
    media = await service.upload(session, storage, user, raw)
    await enqueue_quietly(enqueue, "make_variants", str(media.id))
    return media


@router.get("", response_model=MediaListOut)
async def list_media(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(any_staff),
    session: AsyncSession = Depends(get_session),
) -> MediaListOut:
    items, total = await service.list_media(session, q=q, limit=limit, offset=offset)
    return MediaListOut(items=items, total=total, limit=limit, offset=offset)


@router.patch("/{media_id}", response_model=MediaOut)
async def patch_media(
    media_id: uuid.UUID, body: MediaPatch, user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)
) -> Media:
    return await service.patch_media(session, user, media_id, body)


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    media_id: uuid.UUID,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    storage: Storage = Depends(get_storage),
) -> Response:
    await service.delete_media(session, storage, media_id)
    return Response(status_code=204)
