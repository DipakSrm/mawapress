"""card fields (is_breaking, excerpt, body_text) and full-text search

Revision ID: 6f8b0d2e4a53
Revises: 5e7a9c1d3f42
Create Date: 2026-10-17 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.modules.seo.generator import plain_text

# revision identifiers, used by Alembic.
revision: str = "6f8b0d2e4a53"
down_revision: Union[str, Sequence[str], None] = "5e7a9c1d3f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of posts.models.SEARCH_VECTOR_SQL as of this revision.
SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('simple'::regconfig, title), 'A') || "
    "setweight(to_tsvector('simple'::regconfig, body_text), 'B')"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("posts", sa.Column("is_breaking", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("post_translations", sa.Column("excerpt", sa.String(length=300), nullable=True))
    op.add_column("post_translations", sa.Column("body_text", sa.Text(), nullable=False, server_default=sa.text("''")))

    # body_text is derived in Python (captions dropped, entities unescaped), so backfill row by row.
    bind = op.get_bind()
    for row_id, html in bind.execute(sa.text("SELECT id, content_html FROM post_translations")).all():
        bind.execute(
            sa.text("UPDATE post_translations SET body_text = :body WHERE id = :id"),
            {"body": plain_text(html), "id": row_id},
        )

    # pg_trgm is a trusted extension (PG 13+), so the database owner may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column(
        "post_translations",
        sa.Column("search_vector", postgresql.TSVECTOR(), sa.Computed(SEARCH_VECTOR_SQL, persisted=True), nullable=True),
    )
    op.create_index(
        "ix_post_translations_search_vector", "post_translations", ["search_vector"],
        unique=False, postgresql_using="gin",
    )
    op.create_index(
        "ix_post_translations_title_trgm", "post_translations", ["title"],
        unique=False, postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Downgrade schema.

    pg_trgm is deliberately left installed: other schemas or a DBA may rely on it, and
    upgrade() uses CREATE EXTENSION IF NOT EXISTS, so a downgrade/upgrade round trip is safe.
    """
    op.drop_index("ix_post_translations_title_trgm", table_name="post_translations")
    op.drop_index("ix_post_translations_search_vector", table_name="post_translations")
    op.drop_column("post_translations", "search_vector")
    op.drop_column("post_translations", "body_text")
    op.drop_column("post_translations", "excerpt")
    op.drop_column("posts", "is_breaking")
