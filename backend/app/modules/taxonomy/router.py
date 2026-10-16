from fastapi import APIRouter, Depends, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_redis
from app.db.session import get_session
from app.modules.auth.deps import require_role
from app.modules.public.service import invalidate_feeds
from app.modules.taxonomy import service
from app.modules.taxonomy.models import Category
from app.modules.taxonomy.schemas import CategoryCreate, CategoryOut, CategoryUpdate
from app.modules.users.models import Role, User

router = APIRouter(prefix="/api", tags=["taxonomy"])
any_staff = require_role(Role.reporter)
editors = require_role(Role.editor)


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(user: User = Depends(any_staff), session: AsyncSession = Depends(get_session)) -> list[Category]:
    return await service.list_categories(session)


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryCreate,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Category:
    cat = await service.create_category(session, body)
    await invalidate_feeds(redis)
    return cat


@router.patch("/categories/{cat_id}", response_model=CategoryOut)
async def update_category(
    cat_id: int,
    body: CategoryUpdate,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Category:
    cat = await service.update_category(session, cat_id, body)
    await invalidate_feeds(redis)
    return cat


@router.delete("/categories/{cat_id}", status_code=204)
async def delete_category(
    cat_id: int,
    user: User = Depends(editors),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Response:
    await service.delete_category(session, cat_id)
    await invalidate_feeds(redis)
    return Response(status_code=204)
