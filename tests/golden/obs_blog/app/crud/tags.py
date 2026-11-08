"""Repository for Tag (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.posts import Post
from app.models.tags import Tag


class TagRepository(_crud_base.Repository[Tag]):
    model = Tag
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("posts",)
    references = {}
    many_to_many = {"posts": Post}
