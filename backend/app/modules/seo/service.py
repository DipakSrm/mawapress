from typing import NamedTuple

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.seo.models import Redirect

PERMANENT = 301


class SlugChange(NamedTuple):
    locale: str
    old_slug: str
    redirect_paths: list[str]  # every path whose redirect resolution changed


def article_path(locale: str, category_slug: str, slug: str) -> str:
    """Public article path; the canonical URL is site_url + this (spec §7)."""
    return f"/{locale}/{category_slug}/{slug}"


async def record_slug_change(session: AsyncSession, old_path: str, new_path: str) -> list[str]:
    """Point old_path at new_path with a 301, collapsing chains. Returns the affected from_paths.

    1. new_path is a live article now, so any redirect *from* it would shadow it: delete it.
       This is also what prevents a self-redirect when a slug goes back to an earlier value.
    2. Every redirect that pointed at old_path now points straight at new_path (A→B, B→C ⇒ A→C).
    3. Upsert old_path → new_path. An older row from old_path can exist when another article later
       took that slug; the newest move wins.
    """
    if old_path == new_path:
        return []
    await session.execute(delete(Redirect).where(Redirect.from_path == new_path))
    repointed = (await session.scalars(
        update(Redirect).where(Redirect.to_path == old_path).values(to_path=new_path).returning(Redirect.from_path)
    )).all()
    await session.execute(
        pg_insert(Redirect)
        .values(from_path=old_path, to_path=new_path, code=PERMANENT)
        .on_conflict_do_update(index_elements=[Redirect.from_path], set_={"to_path": new_path, "code": PERMANENT})
    )
    return sorted({old_path, new_path, *repointed})


async def resolve_redirect(session: AsyncSession, path: str) -> Redirect | None:
    return await session.get(Redirect, path)
