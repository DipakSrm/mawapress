from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.posts.models import Post
from app.modules.seo.slug import is_valid_slug, make_slug
from app.modules.taxonomy.models import Category, Tag
from app.modules.taxonomy.schemas import CategoryCreate, CategoryNode, CategoryUpdate, TagCreate, TagUpdate

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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_tags(session: AsyncSession, q: str | None = None) -> list[Tag]:
    stmt = select(Tag).order_by(Tag.name_en, Tag.id).limit(100)
    q = q.strip() if q else None
    if q:
        pattern = f"%{_escape_like(q)}%"
        stmt = stmt.where(or_(
            Tag.name_en.ilike(pattern, escape="\\"),
            Tag.name_ne.ilike(pattern, escape="\\"),
            Tag.slug.ilike(pattern, escape="\\"),
        ))
    return list((await session.scalars(stmt)).all())


async def get_tag(session: AsyncSession, tag_id: int) -> Tag:
    tag = await session.get(Tag, tag_id)
    if tag is None:
        raise AppError(404, "TAG_NOT_FOUND", "Tag not found")
    return tag


async def get_tags(session: AsyncSession, ids: list[int]) -> list[Tag]:
    """Load tags by id for a post. Unknown ids are a client error (422), never silently dropped."""
    wanted = sorted(set(ids))
    if not wanted:
        return []
    tags = list((await session.scalars(select(Tag).where(Tag.id.in_(wanted)).order_by(Tag.id))).all())
    missing = sorted(set(wanted) - {t.id for t in tags})
    if missing:
        raise AppError(422, "TAG_NOT_FOUND", "Unknown tag ids", {"missing": missing})
    return tags


async def create_tag(session: AsyncSession, data: TagCreate) -> Tag:
    slug = data.slug if data.slug is not None else make_slug(data.name_en)
    if not is_valid_slug(slug):
        raise _invalid_slug()
    if await session.scalar(select(Tag.id).where(Tag.slug == slug)) is not None:
        raise _slug_taken()
    tag = Tag(slug=slug, name_ne=data.name_ne, name_en=data.name_en)
    try:
        async with session.begin_nested():
            session.add(tag)
            await session.flush()
    except IntegrityError as exc:
        raise _slug_taken() from exc
    await session.commit()
    return tag


async def update_tag(session: AsyncSession, tag_id: int, data: TagUpdate) -> Tag:
    tag = await get_tag(session, tag_id)
    if data.name_ne is not None:
        tag.name_ne = data.name_ne
    if data.name_en is not None:
        tag.name_en = data.name_en
    await session.commit()
    return tag


async def delete_tag(session: AsyncSession, tag_id: int) -> None:
    tag = await get_tag(session, tag_id)
    await session.delete(tag)  # post_tags rows go with it (ON DELETE CASCADE)
    await session.commit()
