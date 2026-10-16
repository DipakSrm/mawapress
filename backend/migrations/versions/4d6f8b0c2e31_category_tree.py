"""category tree, sort and seo_description

Revision ID: 4d6f8b0c2e31
Revises: 3c5e7a9b1d20
Create Date: 2026-10-17 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4d6f8b0c2e31"
down_revision: Union[str, Sequence[str], None] = "3c5e7a9b1d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("categories", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_categories_parent_id", "categories", "categories", ["parent_id"], ["id"])
    op.add_column("categories", sa.Column("sort", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("categories", sa.Column("seo_description", sa.String(length=320), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("categories", "seo_description")
    op.drop_column("categories", "sort")
    op.drop_constraint("fk_categories_parent_id", "categories", type_="foreignkey")
    op.drop_column("categories", "parent_id")
