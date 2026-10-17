"""refresh_tokens.token_version

Revision ID: ad2f4b6c8e97
Revises: 9c1e3a5b7d86
Create Date: 2026-10-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "ad2f4b6c8e97"
down_revision: Union[str, Sequence[str], None] = "9c1e3a5b7d86"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "refresh_tokens", sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0"))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("refresh_tokens", "token_version")
