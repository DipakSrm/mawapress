"""posts.view_count

Revision ID: f27e9a1c3d41
Revises: e16d8f0b2c30
Create Date: 2026-10-18 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f27e9a1c3d41"
down_revision: Union[str, Sequence[str], None] = "e16d8f0b2c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("posts", sa.Column("view_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posts", "view_count")
