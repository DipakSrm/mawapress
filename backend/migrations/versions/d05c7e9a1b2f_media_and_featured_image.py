"""media table and posts.featured_media_id

Revision ID: d05c7e9a1b2f
Revises: cf4b6d8f0a19
Create Date: 2026-10-17 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d05c7e9a1b2f"
down_revision: Union[str, Sequence[str], None] = "cf4b6d8f0a19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("mime", sa.String(length=50), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("alt_ne", sa.String(length=300), nullable=True),
        sa.Column("alt_en", sa.String(length=300), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("variants", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_media_created_at", "media", ["created_at"])
    op.add_column("posts", sa.Column("featured_media_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_posts_featured_media_id_media", "posts", "media", ["featured_media_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_posts_featured_media_id_media", "posts", type_="foreignkey")
    op.drop_column("posts", "featured_media_id")
    op.drop_index("ix_media_created_at", table_name="media")
    op.drop_table("media")
