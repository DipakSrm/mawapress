"""tags and post_tags

Revision ID: 5e7a9c1d3f42
Revises: 4d6f8b0c2e31
Create Date: 2026-10-17 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "5e7a9c1d3f42"
down_revision: Union[str, Sequence[str], None] = "4d6f8b0c2e31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name_ne", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "post_tags",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id", "tag_id"),
    )
    op.create_index("ix_post_tags_tag_id", "post_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_post_tags_tag_id", table_name="post_tags")
    op.drop_table("post_tags")
    op.drop_table("tags")
