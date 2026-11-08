"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.models import _associations
from app.models._base import Base
from app.models.comments import Comment
from app.models.posts import Post
from app.models.tags import Tag
from app.models.users import User

__all__ = [
    "Base",
    "Comment",
    "Post",
    "Tag",
    "User",
    "_associations",
]
