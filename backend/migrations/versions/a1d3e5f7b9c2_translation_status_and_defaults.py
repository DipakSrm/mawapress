"""translation status and server defaults

Revision ID: a1d3e5f7b9c2
Revises: c70c350a139d
Create Date: 2026-10-17 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1d3e5f7b9c2"
down_revision: Union[str, Sequence[str], None] = "c70c350a139d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

translation_status = postgresql.ENUM("draft", "published", name="translation_status", create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    # op.add_column does not emit CREATE TYPE, so create the enum explicitly.
    postgresql.ENUM("draft", "published", name="translation_status").create(op.get_bind(), checkfirst=True)
    op.add_column(
        "post_translations",
        sa.Column("status", translation_status, nullable=False, server_default="draft"),
    )
    op.add_column(
        "post_translations",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Translations of posts that are already live were public under M1 rules: keep them public.
    op.execute(
        """
        UPDATE post_translations AS t
        SET status = 'published', published_at = p.published_at
        FROM posts AS p
        WHERE p.id = t.post_id AND p.status = 'published'
        """
    )

    op.alter_column("posts", "status", server_default="draft")
    op.alter_column("posts", "created_at", server_default=sa.func.now())
    op.alter_column("posts", "updated_at", server_default=sa.func.now())
    op.alter_column("post_translations", "seo_auto", server_default=sa.text("'{}'::jsonb"))
    op.alter_column("users", "created_at", server_default=sa.func.now())
    op.alter_column("users", "is_active", server_default=sa.true())


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("users", "is_active", server_default=None)
    op.alter_column("users", "created_at", server_default=None)
    op.alter_column("post_translations", "seo_auto", server_default=None)
    op.alter_column("posts", "updated_at", server_default=None)
    op.alter_column("posts", "created_at", server_default=None)
    op.alter_column("posts", "status", server_default=None)

    op.drop_column("post_translations", "published_at")
    op.drop_column("post_translations", "status")
    sa.Enum(name="translation_status").drop(op.get_bind(), checkfirst=True)
