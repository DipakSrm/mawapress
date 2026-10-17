"""posts.feedback_note, feedback_by and feedback_at (send-back feedback)

Revision ID: b4c6d8e0f1a2
Revises: a38f0b2d4e52
Create Date: 2026-10-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b4c6d8e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a38f0b2d4e52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("posts", sa.Column("feedback_note", sa.String(length=1000), nullable=True))
    op.add_column("posts", sa.Column("feedback_by", sa.Uuid(), nullable=True))
    op.add_column("posts", sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_posts_feedback_by_users", "posts", "users", ["feedback_by"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_posts_feedback_by_users", "posts", type_="foreignkey")
    op.drop_column("posts", "feedback_at")
    op.drop_column("posts", "feedback_by")
    op.drop_column("posts", "feedback_note")
