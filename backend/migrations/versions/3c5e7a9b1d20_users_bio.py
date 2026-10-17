"""users.bio and lower-case emails

Revision ID: 3c5e7a9b1d20
Revises: b2e4f6a8c0d1
Create Date: 2026-10-17 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "3c5e7a9b1d20"
down_revision: Union[str, Sequence[str], None] = "b2e4f6a8c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))
    # Emails are stored lower-case from now on; normalise older rows. A case-only
    # duplicate fails here on the unique index, loudly, which is what we want.
    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "bio")
