from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.posts.models import Post, PostTranslation
from app.modules.public.feeds import PUBLISHED_AT, card_query, to_card
from app.modules.public.schemas import PublicCard

SIMPLE = literal_column("'simple'::regconfig")


async def search_posts(
    session: AsyncSession, locale: str, q: str, *, limit: int, offset: int
) -> tuple[list[PublicCard], int]:
    """Full-text match on title+body, or a fuzzy (trigram word-similarity) match on the title.

    websearch_to_tsquery never raises on user input; punctuation-only input becomes an empty
    query that matches nothing.
    """
    tsquery = func.websearch_to_tsquery(SIMPLE, q)
    match = or_(
        PostTranslation.search_vector.bool_op("@@")(tsquery),
        PostTranslation.title.bool_op("%>")(q),  # title %> q  ==  word_similarity(q, title) >= 0.6
    )
    rank = (func.ts_rank(PostTranslation.search_vector, tsquery) + func.word_similarity(q, PostTranslation.title)).label("rank")
    base = card_query(locale).where(match)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.add_columns(rank).order_by(rank.desc(), PUBLISHED_AT.desc(), Post.id.desc()).limit(limit).offset(offset)
    )
    return [to_card(row) for row in rows], total or 0
