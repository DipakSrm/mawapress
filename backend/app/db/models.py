"""Import every model so Base.metadata is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.db.outbox import OutboxEvent
from app.modules.posts.models import Post, PostTranslation
from app.modules.taxonomy.models import Category, Tag, post_tags
from app.modules.users.models import User

__all__ = ["Base", "Category", "OutboxEvent", "Post", "PostTranslation", "Tag", "User", "post_tags"]
