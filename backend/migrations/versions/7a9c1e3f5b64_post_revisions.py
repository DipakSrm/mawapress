"""post_revisions

Revision ID: 7a9c1e3f5b64
Revises: 6f8b0d2e4a53
Create Date: 2026-10-17 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7a9c1e3f5b64"
down_revision: Union[str, Sequence[str], None] = "6f8b0d2e4a53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "post_revisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=2), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("seo_title", sa.String(length=120), nullable=True),
        sa.Column("seo_description", sa.String(length=320), nullable=True),
        sa.Column("excerpt", sa.String(length=300), nullable=True),
        sa.Column("editor_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["editor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_post_revisions_post_id_created_at", "post_revisions", ["post_id", "created_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_post_revisions_post_id_created_at", table_name="post_revisions")
    op.drop_table("post_revisions")
