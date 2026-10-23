"""Repository for Post (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.posts import Post


class PostRepository(_crud_base.Repository[Post]):
    model = Post
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
