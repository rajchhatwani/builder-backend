"""Repository for Post (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.posts import Post
from app.models.tags import Tag
from app.models.users import User


class PostRepository(_crud_base.Repository[Post]):
    model = Post
    soft_delete = False
    filterable = ("published", "title")
    sortable = ("created_at", "title")
    searchable = ("body", "title")
    eager = ("comments", "tags")
    references = {"author_id": User}
    many_to_many = {"tags": Tag}
