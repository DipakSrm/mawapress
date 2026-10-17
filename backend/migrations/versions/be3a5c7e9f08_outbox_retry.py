"""outbox retry/dead-letter columns

Revision ID: be3a5c7e9f08
Revises: ad2f4b6c8e97
Create Date: 2026-10-17 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "be3a5c7e9f08"
down_revision: Union[str, Sequence[str], None] = "ad2f4b6c8e97"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PENDING = "processed_at IS NULL AND dead_at IS NULL"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("outbox", sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("outbox", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox", sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_outbox_pending", "outbox", ["id"], unique=False, postgresql_where=sa.text(PENDING))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_outbox_pending", table_name="outbox", postgresql_where=sa.text(PENDING))
    op.drop_column("outbox", "dead_at")
    op.drop_column("outbox", "next_attempt_at")
    op.drop_column("outbox", "last_error")
    op.drop_column("outbox", "attempts")
