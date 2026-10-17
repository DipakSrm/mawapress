"""Import every model so Base.metadata is complete (used by Alembic and tests)."""

from app.db.base import Base
from app.db.outbox import OutboxEvent
from app.modules.auth.models import RefreshToken
from app.modules.posts.models import Post, PostRevision, PostTranslation
from app.modules.seo.models import Redirect
from app.modules.taxonomy.models import Category, Tag, post_tags
from app.modules.users.models import User

__all__ = ["Base", "Category", "OutboxEvent", "Post", "PostRevision", "PostTranslation", "Redirect", "RefreshToken", "Tag", "User", "post_tags"]
