"""index on posts.featured_media_id

Revision ID: e16d8f0b2c30
Revises: d05c7e9a1b2f
Create Date: 2026-10-17 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e16d8f0b2c30"
down_revision: Union[str, Sequence[str], None] = "d05c7e9a1b2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("ix_posts_featured_media_id", "posts", ["featured_media_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_posts_featured_media_id", table_name="posts")
