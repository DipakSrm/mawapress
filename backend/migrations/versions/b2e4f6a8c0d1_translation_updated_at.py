"""per-translation updated_at

Revision ID: b2e4f6a8c0d1
Revises: a1d3e5f7b9c2
Create Date: 2026-10-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2e4f6a8c0d1"
down_revision: Union[str, Sequence[str], None] = "a1d3e5f7b9c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "post_translations",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        "UPDATE post_translations AS t SET updated_at = p.updated_at FROM posts AS p WHERE p.id = t.post_id"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("post_translations", "updated_at")
