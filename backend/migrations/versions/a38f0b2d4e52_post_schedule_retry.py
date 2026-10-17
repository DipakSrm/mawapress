"""posts scheduler retry bookkeeping

Revision ID: a38f0b2d4e52
Revises: f27e9a1c3d41
Create Date: 2026-10-18 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a38f0b2d4e52"
down_revision: Union[str, Sequence[str], None] = "f27e9a1c3d41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("posts", sa.Column("schedule_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("posts", sa.Column("schedule_last_error", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("schedule_retry_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posts", "schedule_retry_at")
    op.drop_column("posts", "schedule_last_error")
    op.drop_column("posts", "schedule_attempts")
