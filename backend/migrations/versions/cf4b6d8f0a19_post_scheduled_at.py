"""posts.scheduled_at

Revision ID: cf4b6d8f0a19
Revises: be3a5c7e9f08
Create Date: 2026-10-17 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "cf4b6d8f0a19"
down_revision: Union[str, Sequence[str], None] = "be3a5c7e9f08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("posts", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posts", "scheduled_at")
