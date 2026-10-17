"""redirects

Revision ID: 8b0d2f4a6c75
Revises: 7a9c1e3f5b64
Create Date: 2026-10-17 15:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8b0d2f4a6c75"
down_revision: Union[str, Sequence[str], None] = "7a9c1e3f5b64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "redirects",
        sa.Column("from_path", sa.String(length=300), nullable=False),
        sa.Column("to_path", sa.String(length=300), nullable=False),
        sa.Column("code", sa.SmallInteger(), nullable=False, server_default=sa.text("301")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("from_path"),
    )
    op.create_index(op.f("ix_redirects_to_path"), "redirects", ["to_path"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_redirects_to_path"), table_name="redirects")
    op.drop_table("redirects")
