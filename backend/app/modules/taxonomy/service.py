from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.posts.models import Post
from app.modules.seo.slug import is_valid_slug, make_slug
from app.modules.taxonomy.models import Category
from app.modules.taxonomy.schemas import CategoryCreate, CategoryNode, CategoryUpdate

MAX_CATEGORY_DEPTH = 3  # root = 1


def _slug_taken() -> AppError:
    return AppError(409, "SLUG_TAKEN", "That slug is already in use")


def _invalid_slug() -> AppError:
    return AppError(422, "INVALID_SLUG", "Slug must be lower-case letters, digits and single hyphens, at most 80 chars")


async def all_categories(session: AsyncSession) -> dict[int, Category]:
    rows = await session.scalars(select(Category).order_by(Category.sort, Category.id))
    return {c.id: c for c in rows}


def _depth(cats: dict[int, Category], cat_id: int) -> int:
    depth, current = 0, cat_id
    while current is not None:
        depth += 1
        current = cats[current].parent_id
    return depth


def _height(cats: dict[int, Category], cat_id: int) -> int:
    children = [c.id for c in cats.values() if c.parent_id == cat_id]
    return 1 + max((_height(cats, child) for child in children), default=0)


def descendant_ids(cats: dict[int, Category], cat_id: int) -> set[int]:
    found = {cat_id}
    frontier = [cat_id]
    while frontier:
        parent = frontier.pop()
        for c in cats.values():
            if c.parent_id == parent and c.id not in found:
                found.add(c.id)
                frontier.append(c.id)
    return found


def _check_parent(cats: dict[int, Category], cat_id: int | None, parent_id: int) -> None:
    if parent_id not in cats:
        raise AppError(422, "CATEGORY_NOT_FOUND", "Parent category does not exist")
    if cat_id is not None and parent_id in descendant_ids(cats, cat_id):
        raise AppError(409, "CATEGORY_CYCLE", "A category cannot be moved under itself or its descendants")
    height = _height(cats, cat_id) if cat_id is not None else 1
    if _depth(cats, parent_id) + height > MAX_CATEGORY_DEPTH:
        raise AppError(409, "CATEGORY_TOO_DEEP", f"Categories nest at most {MAX_CATEGORY_DEPTH} levels deep")


async def list_categories(session: AsyncSession) -> list[Category]:
    return list((await all_categories(session)).values())


async def get_category(session: AsyncSession, cat_id: int) -> Category:
    cat = await session.get(Category, cat_id)
    if cat is None:
        raise AppError(404, "CATEGORY_NOT_FOUND", "Category not found")
    return cat


async def create_category(session: AsyncSession, data: CategoryCreate) -> Category:
    slug = data.slug if data.slug is not None else make_slug(data.name_en)
    if not is_valid_slug(slug):
        raise _invalid_slug()
    cats = await all_categories(session)
    if data.parent_id is not None:
        _check_parent(cats, None, data.parent_id)
    if any(c.slug == slug for c in cats.values()):
        raise _slug_taken()
    cat = Category(
        slug=slug,
        name_ne=data.name_ne,
        name_en=data.name_en,
        parent_id=data.parent_id,
        sort=data.sort,
        seo_description=data.seo_description or None,
    )
    try:
        async with session.begin_nested():
            session.add(cat)
            await session.flush()
    except IntegrityError as exc:
        raise _slug_taken() from exc
    await session.commit()
    return cat


async def update_category(session: AsyncSession, cat_id: int, data: CategoryUpdate) -> Category:
    cats = await all_categories(session)
    cat = cats.get(cat_id)
    if cat is None:
        raise AppError(404, "CATEGORY_NOT_FOUND", "Category not found")
    fields = data.model_fields_set
    if "parent_id" in fields and data.parent_id != cat.parent_id:
        if data.parent_id is not None:
            _check_parent(cats, cat.id, data.parent_id)
        cat.parent_id = data.parent_id
    if data.name_ne is not None:
        cat.name_ne = data.name_ne
    if data.name_en is not None:
        cat.name_en = data.name_en
    if data.sort is not None:
        cat.sort = data.sort
    if "seo_description" in fields:
        cat.seo_description = data.seo_description or None
    await session.commit()
    return cat


async def delete_category(session: AsyncSession, cat_id: int) -> None:
    cat = await get_category(session, cat_id)
    posts = await session.scalar(select(func.count()).select_from(Post).where(Post.category_id == cat_id))
    children = await session.scalar(select(func.count()).select_from(Category).where(Category.parent_id == cat_id))
    if posts or children:
        raise AppError(409, "CATEGORY_IN_USE", "Move its posts and child categories first",
                       {"posts": posts or 0, "children": children or 0})
    await session.delete(cat)
    await session.commit()


async def category_tree(session: AsyncSession) -> list[CategoryNode]:
    cats = await all_categories(session)  # ordered by sort, id, so siblings come out ordered
    nodes = {cid: CategoryNode.model_validate(c) for cid, c in cats.items()}
    roots: list[CategoryNode] = []
    for cid, c in cats.items():
        if c.parent_id is None:
            roots.append(nodes[cid])
        else:
            nodes[c.parent_id].children.append(nodes[cid])
    return roots
